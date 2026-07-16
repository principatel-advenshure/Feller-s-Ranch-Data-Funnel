"""
Tests for transform/normalize_orders.py — raw Shopify orders → fact_orders +
fact_order_lines.

Pure functions, no I/O: normalize_orders() takes the raw list and returns two
lists. Nothing here touches the network, BigQuery, or credentials.

Business rules under test (see the module docstring / Mason's call):
  - $0 orders are draft orders / shipping labels and are dropped;
    the module actually keeps only orders with amount > 1.
  - Monetary strings ("99.00") are parsed to floats.
  - Missing customer must not crash — customer_id/email fall back to None.
"""

from transform.normalize_orders import normalize_orders


# --------------------------------------------------------------------------- #
# Builders — minimal valid raw-order shapes (as returned by extract_orders)
# --------------------------------------------------------------------------- #

def _money(amount, currency="USD"):
    return {"shopMoney": {"amount": amount, "currencyCode": currency}}


def _line_edge(line_id, title, qty, price, sku="SKU-1", variant_id="gid://shopify/ProductVariant/1"):
    return {
        "node": {
            "id": line_id,
            "title": title,
            "quantity": qty,
            "variant": {
                "id": variant_id,
                "sku": sku,
                "price": price,
            },
        }
    }


def _raw_order(
    order_id="gid://shopify/Order/1001",
    name="#1001",
    amount="99.00",
    subtotal="90.00",
    financial="PAID",
    fulfillment="FULFILLED",
    customer={"id": "gid://shopify/Customer/1", "email": "buyer@example.com"},
    lines=None,
    discount="5.00",
    refund="0.00",
):
    if lines is None:
        lines = [_line_edge("gid://shopify/LineItem/1", "Ribeye", 2, "45.00")]
    return {
        "id": order_id,
        "name": name,
        "createdAt": "2026-01-15T10:00:00Z",
        "displayFinancialStatus": financial,
        "displayFulfillmentStatus": fulfillment,
        "totalPriceSet": _money(amount),
        "subtotalPriceSet": _money(subtotal),
        "totalDiscountsSet": _money(discount),
        "totalRefundedSet": _money(refund),
        "customer": customer,
        "lineItems": {"edges": lines},
    }


# --------------------------------------------------------------------------- #
# fact_orders shape / types
# --------------------------------------------------------------------------- #

def test_valid_order_returns_expected_fact_orders_shape():
    fact_orders, _ = normalize_orders([_raw_order()])

    assert len(fact_orders) == 1
    o = fact_orders[0]

    # order_id keeps the full GID (the module does not strip it).
    assert o["order_id"] == "gid://shopify/Order/1001"
    assert o["order_name"] == "#1001"
    assert o["created_at"] == "2026-01-15T10:00:00Z"

    # snake_case keys present.
    for key in (
        "financial_status", "fulfillment_status", "total_revenue", "subtotal",
        "currency", "customer_id", "customer_email", "store", "channel",
        "discount_amount", "refund_amount",
    ):
        assert key in o

    # constants
    assert o["store"] == "fellers_ranch"
    assert o["channel"] == "online"
    assert o["currency"] == "USD"


def test_monetary_amounts_parsed_to_float():
    fact_orders, _ = normalize_orders([_raw_order(amount="99.00", subtotal="90.00",
                                                  discount="5.00", refund="1.50")])
    o = fact_orders[0]

    assert o["total_revenue"] == 99.0
    assert isinstance(o["total_revenue"], float)
    assert o["subtotal"] == 90.0
    assert o["discount_amount"] == 5.0
    assert o["refund_amount"] == 1.5


def test_financial_and_fulfillment_status_mapped():
    fact_orders, _ = normalize_orders(
        [_raw_order(financial="PARTIALLY_REFUNDED", fulfillment="UNFULFILLED")]
    )
    o = fact_orders[0]

    assert o["financial_status"] == "PARTIALLY_REFUNDED"
    assert o["fulfillment_status"] == "UNFULFILLED"


def test_discount_and_refund_default_to_zero_when_absent():
    raw = _raw_order()
    del raw["totalDiscountsSet"]
    del raw["totalRefundedSet"]

    fact_orders, _ = normalize_orders([raw])
    o = fact_orders[0]

    assert o["discount_amount"] == 0.0
    assert o["refund_amount"] == 0.0


# --------------------------------------------------------------------------- #
# Missing / null customer
# --------------------------------------------------------------------------- #

def test_null_customer_does_not_crash():
    fact_orders, _ = normalize_orders([_raw_order(customer=None)])
    o = fact_orders[0]

    assert o["customer_id"] is None
    assert o["customer_email"] is None


def test_missing_customer_key_does_not_crash():
    raw = _raw_order()
    del raw["customer"]  # key entirely absent, exercised via .get()

    fact_orders, _ = normalize_orders([raw])
    assert fact_orders[0]["customer_id"] is None


# --------------------------------------------------------------------------- #
# Empty / filtered input
# --------------------------------------------------------------------------- #

def test_empty_orders_returns_two_empty_lists():
    result = normalize_orders([])
    assert result == ([], [])


def test_zero_dollar_orders_are_filtered_out():
    orders = [
        _raw_order(order_id="gid://shopify/Order/1", amount="0.00"),
        _raw_order(order_id="gid://shopify/Order/2", amount="99.00"),
    ]
    fact_orders, fact_lines = normalize_orders(orders)

    assert len(fact_orders) == 1
    assert fact_orders[0]["order_id"] == "gid://shopify/Order/2"


# --------------------------------------------------------------------------- #
# fact_order_lines
# --------------------------------------------------------------------------- #

def test_line_items_extracted_into_fact_order_lines():
    lines = [
        _line_edge("gid://shopify/LineItem/1", "Ribeye", 2, "45.00", sku="RIB-1"),
        _line_edge("gid://shopify/LineItem/2", "Brisket", 1, "30.00", sku="BRI-1"),
    ]
    fact_orders, fact_lines = normalize_orders([_raw_order(lines=lines)])

    assert len(fact_lines) == 2
    line = fact_lines[0]

    assert line["order_id"] == "gid://shopify/Order/1001"
    assert line["line_item_id"] == "gid://shopify/LineItem/1"
    assert line["product_title"] == "Ribeye"
    assert line["sku"] == "RIB-1"
    assert line["quantity"] == 2
    assert line["unit_price"] == 45.0
    # line_revenue = quantity * unit_price, rounded to 2 dp.
    assert line["line_revenue"] == 90.0
    assert line["store"] == "fellers_ranch"


def test_line_revenue_is_rounded_to_two_places():
    lines = [_line_edge("gid://shopify/LineItem/9", "Odd", 3, "3.333")]
    _, fact_lines = normalize_orders([_raw_order(lines=lines)])

    # 3 * 3.333 = 9.999 → rounded to 10.0
    assert fact_lines[0]["line_revenue"] == 10.0


def test_line_item_with_null_variant_falls_back_gracefully():
    line = {
        "node": {
            "id": "gid://shopify/LineItem/1",
            "title": "Mystery item",
            "quantity": 2,
            "variant": None,
        }
    }
    _, fact_lines = normalize_orders([_raw_order(lines=[line])])

    fl = fact_lines[0]
    assert fl["variant_id"] is None
    assert fl["sku"] is None
    assert fl["unit_price"] == 0.0
    assert fl["line_revenue"] == 0.0
