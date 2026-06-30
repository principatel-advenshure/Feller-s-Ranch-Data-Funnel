"""
Generates a plain English business summary covering both
online (Shopify) and B2B (QuickBooks) channels combined.
Runs at the end of each pipeline execution.
Stores summary in BigQuery for display on the Overview dashboard page.
"""

from datetime import datetime, timezone


def generate_summary(fact_orders: list, fact_order_lines: list,
                     normalized_customers: list, fact_b2b_invoices: list = None,
                     fact_b2b_lines: list = None) -> dict:
    """
    Generate a combined plain English summary covering both
    online (Shopify) and B2B (QuickBooks) channels.

    Args:
        fact_orders: Normalized Shopify orders
        fact_order_lines: Normalized Shopify order lines
        normalized_customers: Normalized Shopify customers
        fact_b2b_invoices: Normalized B2B invoices (optional)
        fact_b2b_lines: Normalized B2B invoice lines (optional)

    Returns:
        dict with summary text and key metrics
    """

    fact_b2b_invoices = fact_b2b_invoices or []
    fact_b2b_lines = fact_b2b_lines or []

    # ── Online metrics ──
    online_orders = len(fact_orders)
    online_net_sales = sum(o["total_revenue"] for o in fact_orders)
    online_gross_sales = sum(o["subtotal"] + o["discount_amount"] for o in fact_orders)
    online_discounts = sum(o["discount_amount"] for o in fact_orders)
    online_refunds = sum(o["refund_amount"] for o in fact_orders)
    online_units = sum(l["quantity"] for l in fact_order_lines)
    online_aov = online_net_sales / online_orders if online_orders > 0 else 0

    # Accurate new/returning based on fact_orders within this period —
    # NOT lifetime Shopify customer count from dim_customers
    order_emails = [o.get("customer_email") for o in fact_orders if o.get("customer_email")]
    email_counts = {}
    for email in order_emails:
        email_counts[email] = email_counts.get(email, 0) + 1
    new_customers = sum(1 for c in email_counts.values() if c == 1)
    returning_customers = sum(1 for c in email_counts.values() if c > 1)
    unique_online_customers = len(email_counts)

    # ── Online top product ──
    product_sales = {}
    for line in fact_order_lines:
        name = line.get("product_title", "Unknown")
        product_sales[name] = product_sales.get(name, 0) + line.get("line_revenue", 0)
    top_online_product = max(product_sales, key=product_sales.get) if product_sales else "N/A"
    top_online_product_revenue = product_sales.get(top_online_product, 0)

    # ── B2B metrics ──
    b2b_invoices = len(fact_b2b_invoices)
    b2b_revenue = sum(i["total_amount"] for i in fact_b2b_invoices)
    b2b_weight = sum(i["total_quantity"] for i in fact_b2b_invoices)
    b2b_customers = len({i["customer_name"] for i in fact_b2b_invoices})
    b2b_avg_invoice = b2b_revenue / b2b_invoices if b2b_invoices > 0 else 0

    customer_rev = {}
    for inv in fact_b2b_invoices:
        c = inv["customer_name"]
        customer_rev[c] = customer_rev.get(c, 0) + inv["total_amount"]
    top_b2b_customer = max(customer_rev, key=customer_rev.get) if customer_rev else "N/A"
    top_b2b_revenue = customer_rev.get(top_b2b_customer, 0)

    # ── Combined ──
    total_revenue = online_net_sales + b2b_revenue
    b2b_pct = round((b2b_revenue / total_revenue) * 100, 1) if total_revenue else 0
    online_pct = round(100 - b2b_pct, 1) if total_revenue else 0
    total_transactions = online_orders + b2b_invoices

    # ── Build summary text ──
    summary_lines = []

    summary_lines.append(
        f"Fellers Ranch generated ${total_revenue:,.2f} in total revenue "
        f"across {total_transactions} transactions in both channels."
    )

    summary_lines.append(
        f"B2B restaurant sales contributed ${b2b_revenue:,.2f} ({b2b_pct}%) "
        f"across {b2b_invoices} invoices from {b2b_customers} restaurant accounts, "
        f"averaging ${b2b_avg_invoice:,.2f} per invoice."
    )

    summary_lines.append(
        f"Online sales contributed ${online_net_sales:,.2f} ({online_pct}%) "
        f"across {online_orders} orders from {unique_online_customers} customers, "
        f"averaging ${online_aov:,.2f} per order."
    )

    summary_lines.append(
        f"{new_customers} new and {returning_customers} returning customers "
        f"placed online orders this period."
    )

    if top_b2b_customer != "N/A":
        summary_lines.append(
            f"Top B2B customer is {top_b2b_customer} at ${top_b2b_revenue:,.2f}."
        )

    if top_online_product != "N/A":
        summary_lines.append(
            f"Top online product is {top_online_product} at ${top_online_product_revenue:,.2f}."
        )

    summary_text = " ".join(summary_lines)

    return {
        "summary_id": "fellers_ranch_combined",
        "store": "fellers_ranch",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary_text": summary_text,
        "total_revenue": round(total_revenue, 2),
        "total_transactions": total_transactions,
        "online_revenue": round(online_net_sales, 2),
        "online_gross_sales": round(online_gross_sales, 2),
        "online_discounts": round(online_discounts, 2),
        "online_refunds": round(online_refunds, 2),
        "online_orders": online_orders,
        "online_units": online_units,
        "online_aov": round(online_aov, 2),
        "online_pct": online_pct,
        "new_customers": new_customers,
        "returning_customers": returning_customers,
        "unique_online_customers": unique_online_customers,
        "top_online_product": top_online_product,
        "top_online_product_revenue": round(top_online_product_revenue, 2),
        "b2b_revenue": round(b2b_revenue, 2),
        "b2b_invoices": b2b_invoices,
        "b2b_weight": round(b2b_weight, 2),
        "b2b_customers": b2b_customers,
        "b2b_avg_invoice": round(b2b_avg_invoice, 2),
        "b2b_pct": b2b_pct,
        "top_b2b_customer": top_b2b_customer,
        "top_b2b_revenue": round(top_b2b_revenue, 2),
    }


if __name__ == "__main__":
    from extract.extract_orders import extract_orders
    from extract.extract_customers import extract_customers
    from extract.extract_quickbooks import extract_all_b2b_sales
    from transform.normalize_orders import normalize_orders
    from transform.normalize_customers import normalize_customers
    from transform.normalize_quickbooks import normalize_quickbooks

    print("🤖 Generating combined summary...")

    raw_orders = extract_orders()
    raw_customers = extract_customers()
    raw_b2b = extract_all_b2b_sales()

    fact_orders, fact_order_lines = normalize_orders(raw_orders)
    normalized_customers = normalize_customers(raw_customers, fact_orders)
    fact_b2b_invoices, fact_b2b_lines, _ = normalize_quickbooks(raw_b2b)

    summary = generate_summary(
        fact_orders, fact_order_lines, normalized_customers,
        fact_b2b_invoices, fact_b2b_lines
    )

    print(f"\n📋 Summary:")
    print(f"   {summary['summary_text']}")
    print(f"\n📊 Key metrics:")
    print(f"   Total revenue:        ${summary['total_revenue']:,.2f}")
    print(f"   Online revenue:       ${summary['online_revenue']:,.2f} ({summary['online_pct']}%)")
    print(f"   B2B revenue:          ${summary['b2b_revenue']:,.2f} ({summary['b2b_pct']}%)")
    print(f"   Online orders:        {summary['online_orders']}")
    print(f"   B2B invoices:         {summary['b2b_invoices']}")
    print(f"   New customers:        {summary['new_customers']}")
    print(f"   Returning customers:  {summary['returning_customers']}")
    print(f"   Top B2B customer:     {summary['top_b2b_customer']} (${summary['top_b2b_revenue']:,.2f})")
    print(f"   Top online product:   {summary['top_online_product']} (${summary['top_online_product_revenue']:,.2f})")