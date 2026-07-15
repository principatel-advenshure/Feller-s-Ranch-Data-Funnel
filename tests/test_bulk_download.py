"""
Tests for extract.bulk_operations.download_and_parse — Phase B JSONL parsing.

Fully offline: the hardened shopify_client session (bulk._SESSION) is replaced
with a fake that yields canned JSONL lines, so there is no real HTTP, no signed
URL fetch, and no BigQuery. We only assert the parent/child reconstruction and
the graceful handling of edge cases.
"""

import json

import pytest

from extract import bulk_operations as bulk


# --------------------------------------------------------------------------- #
# Fakes: stand in for the streaming requests session / response.
# --------------------------------------------------------------------------- #

class _FakeResponse:
    def __init__(self, lines, status_code=200, text=""):
        self._lines = lines
        self.status_code = status_code
        self.text = text

    def iter_lines(self, decode_unicode=False):
        # Real requests yields str when decode_unicode=True; mimic that.
        for line in self._lines:
            yield line


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._response


def _install_session(monkeypatch, lines, status_code=200, text=""):
    session = _FakeSession(_FakeResponse(lines, status_code=status_code, text=text))
    monkeypatch.setattr(bulk, "_SESSION", session)
    return session


# Sample JSONL records mirroring a real Shopify bulk orders export. Parents come
# before their children, and to-one relations (variant) are inlined on the child.
def _order(gid, name="#1001", amount="99.00"):
    return json.dumps({
        "id": gid,
        "name": name,
        "createdAt": "2023-05-01T10:00:00Z",
        "updatedAt": "2023-05-01T10:05:00Z",
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "totalPriceSet": {"shopMoney": {"amount": amount, "currencyCode": "USD"}},
        "subtotalPriceSet": {"shopMoney": {"amount": amount}},
        "totalDiscountsSet": {"shopMoney": {"amount": "0.00"}},
        "totalRefundedSet": {"shopMoney": {"amount": "0.00"}},
        "customer": {"id": "gid://shopify/Customer/456"},
    })


def _line_item(gid, parent_gid, title="Product", qty=2, sku="SKU1", price="49.50"):
    return json.dumps({
        "id": gid,
        "title": title,
        "quantity": qty,
        "variant": {
            "id": "gid://shopify/ProductVariant/101",
            "sku": sku,
            "price": price,
        },
        "__parentId": parent_gid,
    })


# --------------------------------------------------------------------------- #
# Parent / child separation
# --------------------------------------------------------------------------- #

def test_separates_parents_from_children_via_parent_id(monkeypatch):
    lines = [
        _order("gid://shopify/Order/1", name="#1001"),
        _line_item("gid://shopify/LineItem/11", "gid://shopify/Order/1", sku="A"),
        _line_item("gid://shopify/LineItem/12", "gid://shopify/Order/1", sku="B"),
        _order("gid://shopify/Order/2", name="#1002"),
        _line_item("gid://shopify/LineItem/21", "gid://shopify/Order/2", sku="C"),
    ]
    _install_session(monkeypatch, lines)

    orders, line_items = bulk.download_and_parse("https://signed.example/result.jsonl")

    # Two parents, three children.
    assert len(orders) == 2
    assert len(line_items) == 3

    # Orders keep their scalar fields (no __parentId).
    assert all("__parentId" not in o for o in orders)
    assert orders[0]["name"] == "#1001"

    # Children are nested back under their parent's lineItems.edges[].node,
    # exactly as normalize_orders() reads them.
    order1 = orders[0]
    nodes1 = [e["node"] for e in order1["lineItems"]["edges"]]
    assert len(nodes1) == 2
    assert {n["variant"]["sku"] for n in nodes1} == {"A", "B"}
    assert all(n["__parentId"] == "gid://shopify/Order/1" for n in nodes1)

    order2 = orders[1]
    nodes2 = [e["node"] for e in order2["lineItems"]["edges"]]
    assert len(nodes2) == 1
    assert nodes2[0]["variant"]["sku"] == "C"


def test_parsed_orders_feed_normalize_orders(monkeypatch):
    """The returned orders must be directly consumable by normalize_orders."""
    from transform.normalize_orders import normalize_orders

    lines = [
        _order("gid://shopify/Order/1", amount="99.00"),
        _line_item("gid://shopify/LineItem/11", "gid://shopify/Order/1", qty=2, price="49.50"),
    ]
    _install_session(monkeypatch, lines)

    orders, _ = bulk.download_and_parse("https://signed.example/result.jsonl")
    fact_orders, fact_lines = normalize_orders(orders)

    assert len(fact_orders) == 1
    assert fact_orders[0]["order_id"] == "gid://shopify/Order/1"
    assert fact_orders[0]["total_revenue"] == 99.00
    assert len(fact_lines) == 1
    assert fact_lines[0]["sku"] == "SKU1"
    assert fact_lines[0]["line_revenue"] == 99.0  # 2 * 49.50


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #

def test_empty_jsonl_returns_empty_lists(monkeypatch):
    _install_session(monkeypatch, [])

    orders, line_items = bulk.download_and_parse("https://signed.example/empty.jsonl")

    assert orders == []
    assert line_items == []


def test_blank_lines_are_ignored(monkeypatch):
    lines = ["", _order("gid://shopify/Order/1"), "", None]
    # Filter out None to keep the fake honest about what requests yields; the
    # function guards `if not raw_line` which covers "" too.
    lines = [l for l in lines if l is not None]
    lines.insert(0, "")
    _install_session(monkeypatch, lines)

    orders, line_items = bulk.download_and_parse("https://signed.example/x.jsonl")

    assert len(orders) == 1
    assert line_items == []


def test_orphan_line_item_is_skipped_not_crash(monkeypatch):
    """A child whose parent never appears must be dropped gracefully."""
    lines = [
        _order("gid://shopify/Order/1"),
        _line_item("gid://shopify/LineItem/11", "gid://shopify/Order/1"),
        # Parent 999 is never emitted → orphan.
        _line_item("gid://shopify/LineItem/99", "gid://shopify/Order/999"),
    ]
    _install_session(monkeypatch, lines)

    orders, line_items = bulk.download_and_parse("https://signed.example/x.jsonl")

    assert len(orders) == 1
    # Only the one linkable child survives; the orphan is skipped.
    assert len(line_items) == 1
    assert line_items[0]["id"] == "gid://shopify/LineItem/11"


def test_non_200_raises(monkeypatch):
    _install_session(monkeypatch, [], status_code=403, text="Forbidden")

    with pytest.raises(RuntimeError, match="Failed to download"):
        bulk.download_and_parse("https://signed.example/denied.jsonl")


def test_bytes_lines_are_decoded(monkeypatch):
    """Defensive: if the session yields bytes, we still parse."""
    lines = [_order("gid://shopify/Order/1").encode("utf-8")]
    _install_session(monkeypatch, lines)

    orders, line_items = bulk.download_and_parse("https://signed.example/x.jsonl")

    assert len(orders) == 1
    assert orders[0]["id"] == "gid://shopify/Order/1"
