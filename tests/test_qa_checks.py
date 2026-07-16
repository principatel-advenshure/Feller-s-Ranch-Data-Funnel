"""
Tests for transform/qa_checks.py — run_qa_checks() builds a QA report over the
normalized data.

Pure function, no I/O. Note the current contract: the report distinguishes
`issues` (hard failures — currently none are ever raised) from `warnings`
(soft data-quality flags: guest checkouts, missing SKUs, unmapped products,
draft products, nameless / location-less customers). `passed` is True iff there
are no `issues`, so on this data set it stays True even when warnings fire.
"""

from transform.qa_checks import run_qa_checks


def _clean_order(order_id="gid://shopify/Order/1", customer_id="gid://shopify/Customer/1"):
    return {"order_id": order_id, "customer_id": customer_id}


def _clean_line(sku="RIB-1"):
    return {"order_id": "gid://shopify/Order/1", "sku": sku}


def _clean_product(status="ACTIVE"):
    return {"canonical_sku": "RIB-1", "status": status}


def _clean_customer(name="Jane Doe", country="US"):
    return {"full_name": name, "country": country}


# --------------------------------------------------------------------------- #
# Passing / clean data
# --------------------------------------------------------------------------- #

def test_clean_data_passes_with_no_warnings():
    report = run_qa_checks(
        fact_orders=[_clean_order()],
        fact_order_lines=[_clean_line()],
        normalized_products=[_clean_product()],
        unmapped_products=[],
        normalized_customers=[_clean_customer()],
    )

    assert report["passed"] is True
    assert report["issues"] == []
    assert report["warnings"] == []


def test_summary_counts_are_correct():
    report = run_qa_checks(
        fact_orders=[_clean_order(), _clean_order(order_id="gid://shopify/Order/2")],
        fact_order_lines=[_clean_line()],
        normalized_products=[_clean_product()],
        unmapped_products=[{"canonical_sku": None}],
        normalized_customers=[_clean_customer()],
    )

    s = report["summary"]
    assert s["total_orders"] == 2
    assert s["total_order_lines"] == 1
    assert s["total_products_mapped"] == 1
    assert s["total_products_unmapped"] == 1
    assert s["total_customers"] == 1


# --------------------------------------------------------------------------- #
# Flagging missing / low-quality fields (warnings)
# --------------------------------------------------------------------------- #

def test_order_missing_customer_is_flagged():
    report = run_qa_checks(
        fact_orders=[_clean_order(customer_id=None)],
        fact_order_lines=[],
        normalized_products=[],
        unmapped_products=[],
        normalized_customers=[],
    )
    assert any("no customer" in w for w in report["warnings"])
    # still "passed" — this is a warning, not an issue.
    assert report["passed"] is True


def test_line_missing_sku_is_flagged():
    report = run_qa_checks(
        fact_orders=[],
        fact_order_lines=[_clean_line(sku=None), _clean_line(sku="0")],
        normalized_products=[],
        unmapped_products=[],
        normalized_customers=[],
    )
    assert any("no SKU" in w for w in report["warnings"])


def test_unmapped_products_flagged():
    report = run_qa_checks(
        fact_orders=[],
        fact_order_lines=[],
        normalized_products=[],
        unmapped_products=[{"canonical_sku": None}],
        normalized_customers=[],
    )
    assert any("canonical SKU" in w for w in report["warnings"])


def test_draft_products_flagged():
    report = run_qa_checks(
        fact_orders=[],
        fact_order_lines=[],
        normalized_products=[_clean_product(status="DRAFT")],
        unmapped_products=[],
        normalized_customers=[],
    )
    assert any("DRAFT" in w for w in report["warnings"])


def test_customers_missing_name_and_location_flagged():
    report = run_qa_checks(
        fact_orders=[],
        fact_order_lines=[],
        normalized_products=[],
        unmapped_products=[],
        normalized_customers=[_clean_customer(name="Unknown", country=None)],
    )
    assert any("no name" in w for w in report["warnings"])
    assert any("no location" in w for w in report["warnings"])


# --------------------------------------------------------------------------- #
# Empty input
# --------------------------------------------------------------------------- #

def test_empty_input_passes_with_zeroed_summary():
    report = run_qa_checks([], [], [], [], [])

    assert report["passed"] is True
    assert report["issues"] == []
    assert report["warnings"] == []
    assert report["summary"] == {
        "total_orders": 0,
        "total_order_lines": 0,
        "total_products_mapped": 0,
        "total_products_unmapped": 0,
        "total_customers": 0,
    }
