"""
Tests for extract/bulk_operations.py — Shopify Bulk Operation submit + poll.

Everything is offline: extract.bulk_operations.run_query is mocked so no HTTP,
no credentials, and no real bulk operation is ever fired. time.sleep is stubbed
and time.monotonic is driven by a fake clock so the timeout path is exercised
without wall-clock waiting.

Scope note: Phase A stops at "print the result URL" — there is nothing here that
downloads or parses the JSONL, by design.
"""

import pytest

from extract import bulk_operations as bulk


# --------------------------------------------------------------------------- #
# build_orders_bulk_query
# --------------------------------------------------------------------------- #

def test_build_query_has_orders_and_nested_line_items():
    query = bulk.build_orders_bulk_query()

    assert "orders" in query
    assert "lineItems" in query
    # The nested connection must appear inside the orders node (2-level nesting).
    assert query.index("lineItems") > query.index("orders")
    # Same core fields the nightly extractor pulls.
    for field in ("createdAt", "updatedAt", "displayFinancialStatus", "sku"):
        assert field in query


def test_build_query_has_no_first_argument_on_any_connection():
    """Bulk rejects first:/last: on connections — especially lineItems."""
    query = bulk.build_orders_bulk_query()

    assert "lineItems(first" not in query
    assert "lineItems (first" not in query
    # No pagination args anywhere in the bulk document.
    assert "first:" not in query
    assert "last:" not in query


def test_build_query_full_history_has_no_filter():
    query = bulk.build_orders_bulk_query(updated_at=None)

    assert "updated_at" not in query
    assert "query:" not in query


def test_build_query_respects_updated_at_filter():
    query = bulk.build_orders_bulk_query(updated_at="2023-01-01T00:00:00Z")

    assert 'query: "updated_at:>=2023-01-01T00:00:00Z"' in query


# --------------------------------------------------------------------------- #
# submit_bulk_query
# --------------------------------------------------------------------------- #

def test_submit_returns_operation_id_on_success(monkeypatch):
    captured = {}

    def fake_run_query(query, variables=None, store="fellers_ranch"):
        captured["query"] = query
        return {
            "data": {
                "bulkOperationRunQuery": {
                    "bulkOperation": {
                        "id": "gid://shopify/BulkOperation/123",
                        "status": "CREATED",
                    },
                    "userErrors": [],
                }
            }
        }

    monkeypatch.setattr(bulk, "run_query", fake_run_query)

    op_id = bulk.submit_bulk_query(bulk.build_orders_bulk_query())

    assert op_id == "gid://shopify/BulkOperation/123"
    # The submitted mutation must wrap the inner query.
    assert "bulkOperationRunQuery" in captured["query"]
    assert "orders" in captured["query"]


def test_submit_raises_on_user_errors(monkeypatch):
    def fake_run_query(query, variables=None, store="fellers_ranch"):
        return {
            "data": {
                "bulkOperationRunQuery": {
                    "bulkOperation": None,
                    "userErrors": [
                        {"field": ["query"], "message": "A bulk query is already running"}
                    ],
                }
            }
        }

    monkeypatch.setattr(bulk, "run_query", fake_run_query)

    with pytest.raises(RuntimeError, match="already running"):
        bulk.submit_bulk_query("{ orders { edges { node { id } } } }")


def test_submit_raises_on_missing_payload(monkeypatch):
    monkeypatch.setattr(bulk, "run_query", lambda *a, **k: {"data": {}})

    with pytest.raises(RuntimeError, match="Unexpected"):
        bulk.submit_bulk_query("{ orders { edges { node { id } } } }")


# --------------------------------------------------------------------------- #
# poll_until_done
# --------------------------------------------------------------------------- #

def _node_response(status, **extra):
    node = {"id": "gid://shopify/BulkOperation/123", "status": status}
    node.update(extra)
    return {"data": {"node": node}}


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Never actually sleep during poll tests."""
    monkeypatch.setattr(bulk.time, "sleep", lambda _s: None)


def test_poll_returns_on_completed(monkeypatch):
    monkeypatch.setattr(
        bulk,
        "run_query",
        lambda *a, **k: _node_response(
            "COMPLETED", objectCount="42", url="https://storage.example/result.jsonl"
        ),
    )

    result = bulk.poll_until_done("gid://shopify/BulkOperation/123", interval=1, timeout=60)

    assert result["status"] == "COMPLETED"
    assert result["url"] == "https://storage.example/result.jsonl"
    assert result["objectCount"] == "42"


def test_poll_succeeds_after_running_then_completed(monkeypatch):
    responses = [
        _node_response("RUNNING", objectCount="10"),
        _node_response("RUNNING", objectCount="30"),
        _node_response("COMPLETED", objectCount="42", url="https://x/result.jsonl"),
    ]
    calls = {"n": 0}

    def fake_run_query(*a, **k):
        r = responses[calls["n"]]
        calls["n"] += 1
        return r

    monkeypatch.setattr(bulk, "run_query", fake_run_query)

    result = bulk.poll_until_done("gid://shopify/BulkOperation/123", interval=1, timeout=60)

    assert result["status"] == "COMPLETED"
    assert calls["n"] == 3


def test_poll_raises_on_failed(monkeypatch):
    monkeypatch.setattr(
        bulk,
        "run_query",
        lambda *a, **k: _node_response("FAILED", errorCode="INTERNAL_SERVER_ERROR"),
    )

    with pytest.raises(RuntimeError, match="FAILED"):
        bulk.poll_until_done("gid://shopify/BulkOperation/123", interval=1, timeout=60)


def test_poll_raises_on_canceled(monkeypatch):
    monkeypatch.setattr(
        bulk, "run_query", lambda *a, **k: _node_response("CANCELED")
    )

    with pytest.raises(RuntimeError, match="CANCELED"):
        bulk.poll_until_done("gid://shopify/BulkOperation/123", interval=1, timeout=60)


def test_poll_raises_timeout(monkeypatch):
    # Never terminal — always RUNNING.
    monkeypatch.setattr(
        bulk, "run_query", lambda *a, **k: _node_response("RUNNING", objectCount="1")
    )

    # Fake clock: start=0, then jumps past the timeout on the first elapsed check.
    ticks = iter([0, 5000, 5000, 5000])
    monkeypatch.setattr(bulk.time, "monotonic", lambda: next(ticks))

    with pytest.raises(TimeoutError, match="did not finish"):
        bulk.poll_until_done("gid://shopify/BulkOperation/123", interval=1, timeout=1800)


def test_poll_raises_when_node_missing(monkeypatch):
    monkeypatch.setattr(bulk, "run_query", lambda *a, **k: {"data": {"node": None}})

    with pytest.raises(RuntimeError, match="not found"):
        bulk.poll_until_done("gid://shopify/BulkOperation/does-not-exist", interval=1, timeout=60)
