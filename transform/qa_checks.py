"""
QA checks before loading to BigQuery.
Flags data quality issues and unmapped SKUs.
Ensures pipeline is idempotent and clean.
"""


def run_qa_checks(fact_orders: list, fact_order_lines: list,
                  normalized_products: list, unmapped_products: list,
                  normalized_customers: list) -> dict:
    """
    Run QA checks across all normalized data.

    Args:
        fact_orders: Normalized orders
        fact_order_lines: Normalized order lines
        normalized_products: Products with canonical SKUs
        unmapped_products: Products without SKUs
        normalized_customers: Normalized customers

    Returns:
        dict: QA report with issues and summary
    """
    issues = []
    warnings = []

    # ── Orders checks ──
    orders_missing_customer = [
        o for o in fact_orders if not o.get("customer_id")
    ]
    if orders_missing_customer:
        warnings.append(
            f"⚠️  {len(orders_missing_customer)} orders have no customer linked"
        )

    orders_zero_revenue = [
        o for o in fact_orders if o.get("total_revenue", 0) == 0
    ]
    if orders_zero_revenue:
        warnings.append(
            f"⚠️  {len(orders_zero_revenue)} orders have $0 revenue"
        )

    # ── Order lines checks ──
    lines_missing_sku = [
        l for l in fact_order_lines if not l.get("sku") or l.get("sku") == "0"
    ]
    if lines_missing_sku:
        warnings.append(
            f"⚠️  {len(lines_missing_sku)} order lines have no SKU"
        )

    lines_zero_price = [
        l for l in fact_order_lines if l.get("unit_price", 0) == 0
    ]
    if lines_zero_price:
        warnings.append(
            f"⚠️  {len(lines_zero_price)} order lines have $0 price"
        )

    # ── Product checks ──
    if unmapped_products:
        issues.append(
            f"❌ {len(unmapped_products)} products have no canonical SKU — update Airtable mapping"
        )

    draft_products = [
        p for p in normalized_products if p.get("status") == "DRAFT"
    ]
    if draft_products:
        warnings.append(
            f"⚠️  {len(draft_products)} products are still in DRAFT status"
        )

    # ── Customer checks ──
    customers_unknown_name = [
        c for c in normalized_customers if c.get("full_name") == "Unknown"
    ]
    if customers_unknown_name:
        warnings.append(
            f"⚠️  {len(customers_unknown_name)} customers have no name"
        )

    customers_no_location = [
        c for c in normalized_customers if not c.get("country")
    ]
    if customers_no_location:
        warnings.append(
            f"⚠️  {len(customers_no_location)} customers have no location"
        )

    # ── Summary ──
    report = {
        "passed": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "summary": {
            "total_orders": len(fact_orders),
            "total_order_lines": len(fact_order_lines),
            "total_products_mapped": len(normalized_products),
            "total_products_unmapped": len(unmapped_products),
            "total_customers": len(normalized_customers),
        }
    }

    return report


if __name__ == "__main__":
    from extract.extract_orders import extract_orders
    from extract.extract_products import extract_products
    from extract.extract_customers import extract_customers
    from transform.normalize_orders import normalize_orders
    from transform.normalize_products import normalize_products
    from transform.normalize_customers import normalize_customers

    print("🔍 Running QA checks...\n")

    # Extract
    raw_orders = extract_orders()
    raw_products = extract_products()
    raw_customers = extract_customers()

    # Transform
    fact_orders, fact_order_lines = normalize_orders(raw_orders)
    normalized_products, unmapped_products = normalize_products(raw_products)
    normalized_customers = normalize_customers(raw_customers)

    # QA
    report = run_qa_checks(
        fact_orders, fact_order_lines,
        normalized_products, unmapped_products,
        normalized_customers
    )

    # Print report
    print("=" * 50)
    print("📊 QA REPORT")
    print("=" * 50)

    status = "✅ PASSED" if report["passed"] else "❌ FAILED"
    print(f"Status: {status}\n")

    if report["issues"]:
        print("🚨 Issues (must fix before loading):")
        for issue in report["issues"]:
            print(f"   {issue}")
        print()

    if report["warnings"]:
        print("⚠️  Warnings (review recommended):")
        for warning in report["warnings"]:
            print(f"   {warning}")
        print()

    print("📈 Summary:")
    for key, value in report["summary"].items():
        print(f"   {key}: {value}")
    print("=" * 50)