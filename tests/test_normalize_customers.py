"""
Tests for transform/normalize_customers.py — raw Shopify customers → dim_customers.

Pure function, no I/O. Covers the dim_customers shape, graceful handling of
missing optional fields (phone, defaultAddress, names), and the empty case.
Dedup-by-id / dedup-by-email and first_order_date derivation are also exercised
lightly since they're the same code path.
"""

from transform.normalize_customers import normalize_customers


def _raw_customer(
    cid="gid://shopify/Customer/1",
    email="buyer@example.com",
    first="Jane",
    last="Doe",
    phone="+15551234567",
    address={"city": "Austin", "province": "TX", "country": "US"},
    number_of_orders=3,
    amount="250.00",
    currency="USD",
):
    return {
        "id": cid,
        "email": email,
        "firstName": first,
        "lastName": last,
        "phone": phone,
        "defaultAddress": address,
        "numberOfOrders": number_of_orders,
        "amountSpent": {"amount": amount, "currencyCode": currency},
        "createdAt": "2025-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
    }


# --------------------------------------------------------------------------- #
# dim_customers shape
# --------------------------------------------------------------------------- #

def test_returns_expected_dim_customers_shape():
    result = normalize_customers([_raw_customer()])

    assert len(result) == 1
    c = result[0]

    for key in (
        "customer_id", "email", "full_name", "first_name", "last_name", "phone",
        "city", "province", "country", "number_of_orders", "total_spent",
        "currency", "first_order_date", "created_at", "updated_at", "store",
    ):
        assert key in c

    assert c["customer_id"] == "gid://shopify/Customer/1"
    assert c["email"] == "buyer@example.com"
    assert c["full_name"] == "Jane Doe"
    assert c["city"] == "Austin"
    assert c["province"] == "TX"
    assert c["country"] == "US"
    assert c["number_of_orders"] == 3
    assert c["total_spent"] == 250.0
    assert isinstance(c["total_spent"], float)
    assert c["currency"] == "USD"
    assert c["store"] == "fellers_ranch"


def test_email_is_normalized_to_lowercase_and_trimmed():
    result = normalize_customers([_raw_customer(email="  BUYER@Example.COM  ")])
    assert result[0]["email"] == "buyer@example.com"


# --------------------------------------------------------------------------- #
# Missing optional fields
# --------------------------------------------------------------------------- #

def test_missing_phone_and_address_handled_gracefully():
    result = normalize_customers([_raw_customer(phone=None, address=None)])
    c = result[0]

    assert c["phone"] is None
    assert c["city"] is None
    assert c["province"] is None
    assert c["country"] is None


def test_missing_names_fall_back_to_unknown():
    result = normalize_customers([_raw_customer(first=None, last=None)])
    c = result[0]

    assert c["full_name"] == "Unknown"
    assert c["first_name"] is None
    assert c["last_name"] is None


def test_missing_number_of_orders_defaults_to_zero():
    raw = _raw_customer()
    del raw["numberOfOrders"]

    result = normalize_customers([raw])
    assert result[0]["number_of_orders"] == 0


# --------------------------------------------------------------------------- #
# Filtering / dedup
# --------------------------------------------------------------------------- #

def test_customer_without_email_is_skipped():
    result = normalize_customers([_raw_customer(email=None)])
    assert result == []


def test_duplicate_ids_deduped():
    dup = _raw_customer(cid="gid://shopify/Customer/1", email="a@example.com")
    result = normalize_customers([dup, dict(dup)])
    assert len(result) == 1


def test_duplicate_emails_deduped():
    result = normalize_customers([
        _raw_customer(cid="gid://shopify/Customer/1", email="same@example.com"),
        _raw_customer(cid="gid://shopify/Customer/2", email="SAME@example.com"),
    ])
    assert len(result) == 1


# --------------------------------------------------------------------------- #
# first_order_date derivation
# --------------------------------------------------------------------------- #

def test_first_order_date_pulled_from_fact_orders():
    fact_orders = [
        {"customer_email": "buyer@example.com", "created_at": "2026-03-01T00:00:00Z"},
        {"customer_email": "buyer@example.com", "created_at": "2026-01-01T00:00:00Z"},
    ]
    result = normalize_customers([_raw_customer(email="buyer@example.com")], fact_orders)

    # earliest of the two order dates wins
    assert result[0]["first_order_date"] == "2026-01-01T00:00:00Z"


def test_first_order_date_none_when_no_orders():
    result = normalize_customers([_raw_customer()])
    assert result[0]["first_order_date"] is None


# --------------------------------------------------------------------------- #
# Empty input
# --------------------------------------------------------------------------- #

def test_empty_list_returns_empty_list():
    assert normalize_customers([]) == []
