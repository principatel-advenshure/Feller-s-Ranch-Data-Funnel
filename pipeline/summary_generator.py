"""
Generates a plain English business summary from pipeline data.
Runs at the end of each pipeline execution.
Stores summary in BigQuery for display in Looker Studio.
"""

from datetime import datetime, timezone


def generate_summary(fact_orders: list, fact_order_lines: list,
                     normalized_customers: list) -> dict:
    """
    Generate a plain English summary of key business metrics.

    Args:
        fact_orders: Normalized orders
        fact_order_lines: Normalized order lines
        normalized_customers: Normalized customers

    Returns:
        dict with summary text and key metrics
    """

    # ── Core metrics ──
    total_orders = len(fact_orders)
    net_sales = sum(o["total_revenue"] for o in fact_orders)
    gross_sales = sum(o["subtotal"] + o["discount_amount"] for o in fact_orders)
    total_discount = sum(o["discount_amount"] for o in fact_orders)
    total_refunds = sum(o["refund_amount"] for o in fact_orders)
    avg_order_value = net_sales / total_orders if total_orders > 0 else 0
    units_sold = sum(l["quantity"] for l in fact_order_lines)

    # ── Top product by sales ──
    product_sales = {}
    for line in fact_order_lines:
        name = line.get("product_title", "Unknown")
        product_sales[name] = product_sales.get(name, 0) + line.get("line_revenue", 0)
    top_product = max(product_sales, key=product_sales.get) if product_sales else "N/A"
    top_product_revenue = product_sales.get(top_product, 0)

    # ── Top product by units ──
    product_units = {}
    for line in fact_order_lines:
        name = line.get("product_title", "Unknown")
        product_units[name] = product_units.get(name, 0) + line.get("quantity", 0)
    top_unit_product = max(product_units, key=product_units.get) if product_units else "N/A"
    top_unit_count = product_units.get(top_unit_product, 0)

    # ── Customer metrics ──
    customers_with_orders = [c for c in normalized_customers if c.get("number_of_orders", 0) > 0]
    new_customers = [c for c in customers_with_orders if c.get("number_of_orders") == 1]
    returning_customers = [c for c in customers_with_orders if c.get("number_of_orders", 0) > 1]

    # ── Monthly breakdown ──
    monthly_sales = {}
    for order in fact_orders:
        created = order.get("created_at", "")
        if created:
            month = created[:7]  # YYYY-MM
            monthly_sales[month] = monthly_sales.get(month, 0) + order["total_revenue"]
    best_month = max(monthly_sales, key=monthly_sales.get) if monthly_sales else "N/A"
    best_month_revenue = monthly_sales.get(best_month, 0)

    # ── Build summary text ──
    summary_lines = []

    summary_lines.append(
        f"Fellers Ranch generated ${net_sales:,.2f} in net sales "
        f"across {total_orders} orders."
    )

    if best_month != "N/A":
        summary_lines.append(
            f"{best_month} was the strongest month with ${best_month_revenue:,.2f} in revenue."
        )

    summary_lines.append(
        f"Average order value is ${avg_order_value:,.2f} "
        f"with {units_sold} total units sold."
    )

    if top_product != "N/A":
        summary_lines.append(
            f"Top selling product by revenue is {top_product} "
            f"at ${top_product_revenue:,.2f}."
        )

    if top_unit_product != "N/A":
        summary_lines.append(
            f"Most ordered product is {top_unit_product} "
            f"with {top_unit_count} units sold."
        )

    if total_discount > 0:
        summary_lines.append(
            f"${total_discount:,.2f} in discounts were applied across all orders."
        )

    if total_refunds > 0:
        summary_lines.append(
            f"${total_refunds:,.2f} in refunds were issued this period."
        )

    if new_customers or returning_customers:
        summary_lines.append(
            f"{len(new_customers)} new customers and "
            f"{len(returning_customers)} returning customers placed orders."
        )

    summary_text = " ".join(summary_lines)

    return {
        "summary_id": "fellers_ranch_latest",
        "store": "fellers_ranch",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary_text": summary_text,
        "total_orders": total_orders,
        "net_sales": round(net_sales, 2),
        "gross_sales": round(gross_sales, 2),
        "avg_order_value": round(avg_order_value, 2),
        "units_sold": units_sold,
        "top_product": top_product,
        "top_product_revenue": round(top_product_revenue, 2),
        "total_refunds": round(total_refunds, 2),
        "total_discounts": round(total_discount, 2),
        "new_customers": len(new_customers),
        "returning_customers": len(returning_customers),
        "best_month": best_month,
        "best_month_revenue": round(best_month_revenue, 2),
    }


if __name__ == "__main__":
    from extract.extract_orders import extract_orders
    from extract.extract_customers import extract_customers
    from transform.normalize_orders import normalize_orders
    from transform.normalize_customers import normalize_customers

    print("🤖 Generating summary...")
    raw_orders = extract_orders()
    raw_customers = extract_customers()
    fact_orders, fact_order_lines = normalize_orders(raw_orders)
    normalized_customers = normalize_customers(raw_customers, fact_orders)

    summary = generate_summary(fact_orders, fact_order_lines, normalized_customers)

    print(f"\n📋 Summary:")
    print(f"   {summary['summary_text']}")
    print(f"\n📊 Key metrics:")
    print(f"   Total orders:    {summary['total_orders']}")
    print(f"   Net sales:       ${summary['net_sales']:,.2f}")
    print(f"   AOV:             ${summary['avg_order_value']:,.2f}")
    print(f"   Units sold:      {summary['units_sold']}")
    print(f"   Top product:     {summary['top_product']}")
    print(f"   Best month:      {summary['best_month']} (${summary['best_month_revenue']:,.2f})")