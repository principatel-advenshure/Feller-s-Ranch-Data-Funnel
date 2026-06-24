"""
Normalize raw QuickBooks B2B invoice data into a clean flat structure
ready for loading into BigQuery fact_b2b_invoices table.
"""


def normalize_quickbooks(raw_records: list) -> tuple:
    """
    Normalize raw QuickBooks invoice records.

    Args:
        raw_records: List of raw records from extract_quickbooks.py

    Returns:
        tuple: (fact_b2b_invoices, fact_b2b_invoice_lines)
    """
    fact_invoices = {}
    fact_invoice_lines = []
    skipped = []

    for record in raw_records:

        # ── Skip records with missing critical fields ──
        if not record.get("invoice_num"):
            skipped.append({"reason": "missing invoice_num", "record": record})
            continue
        if not record.get("customer_name"):
            skipped.append({"reason": "missing customer_name", "record": record})
            continue
        if not record.get("date"):
            skipped.append({"reason": "missing date", "record": record})
            continue

        invoice_num = record["invoice_num"].strip()
        customer = record["customer_name"].strip()
        date = record["date"]
        line_amount = record.get("line_amount") or 0.0
        quantity = record.get("quantity")
        unit_price = record.get("unit_price")
        product = record.get("product_description", "").strip()
        memo = record.get("memo", "").strip()
        uom = record.get("unit_of_measure", "").strip()
        source = record.get("source_file", "")

        # ── Derive month from date ──
        month = date[:7] if date else None  # YYYY-MM

        # ── Build unique line item ID ──
        line_idx = len(fact_invoice_lines)
        line_id = f"{invoice_num}_{line_idx}"

        # ── Aggregate invoice-level facts ──
        if invoice_num not in fact_invoices:
            fact_invoices[invoice_num] = {
                "invoice_id": invoice_num,
                "date": date,
                "month": month,
                "customer_name": customer,
                "total_amount": 0.0,
                "total_quantity": 0.0,
                "line_item_count": 0,
                "store": "fellers_ranch",
                "source": source
            }

        fact_invoices[invoice_num]["total_amount"] = round(
            fact_invoices[invoice_num]["total_amount"] + line_amount, 2
        )
        if quantity:
            fact_invoices[invoice_num]["total_quantity"] = round(
                fact_invoices[invoice_num]["total_quantity"] + quantity, 2
            )
        fact_invoices[invoice_num]["line_item_count"] += 1

        # ── Build line item ──
        fact_invoice_lines.append({
            "line_id": line_id,
            "invoice_id": invoice_num,
            "date": date,
            "month": month,
            "customer_name": customer,
            "product_description": product or memo or "Unknown",
            "memo": memo,
            "quantity": quantity,
            "unit_of_measure": uom or None,
            "unit_price": unit_price,
            "line_amount": line_amount,
            "store": "fellers_ranch",
            "source": source
        })

    fact_invoices_list = list(fact_invoices.values())

    return fact_invoices_list, fact_invoice_lines, skipped


if __name__ == "__main__":
    from extract.extract_quickbooks import extract_all_b2b_sales

    print("🔄 Normalizing QuickBooks B2B data...\n")
    raw_records = extract_all_b2b_sales()

    fact_invoices, fact_lines, skipped = normalize_quickbooks(raw_records)

    print(f"\n{'='*55}")
    print(f"📊 NORMALIZATION SUMMARY")
    print(f"{'='*55}")
    print(f"  fact_b2b_invoices:      {len(fact_invoices)} rows")
    print(f"  fact_b2b_invoice_lines: {len(fact_lines)} rows")
    print(f"  Skipped records:        {len(skipped)}")

    if fact_invoices:
        total_revenue = sum(i["total_amount"] for i in fact_invoices)
        total_weight = sum(i["total_quantity"] for i in fact_invoices)
        customers = {i["customer_name"] for i in fact_invoices}
        months = {i["month"] for i in fact_invoices}

        print(f"\n  Total B2B revenue:  ${total_revenue:,.2f}")
        print(f"  Total weight sold:  {total_weight:,.1f} lbs")
        print(f"  Unique customers:   {len(customers)}")
        print(f"  Months covered:     {sorted(months)}")

        print(f"\n📋 Sample invoice:")
        sample = fact_invoices[0]
        for k, v in sample.items():
            print(f"   {k}: {v}")

        print(f"\n📋 Sample line item:")
        sample_line = fact_lines[0]
        for k, v in sample_line.items():
            print(f"   {k}: {v}")

        print(f"\n🏆 Top customers by revenue:")
        customer_rev = {}
        for inv in fact_invoices:
            c = inv["customer_name"]
            customer_rev[c] = customer_rev.get(c, 0) + inv["total_amount"]
        for c, rev in sorted(customer_rev.items(), key=lambda x: -x[1])[:5]:
            print(f"   {c}: ${rev:,.2f}")

    if skipped:
        print(f"\n⚠️  Skipped records:")
        for s in skipped[:3]:
            print(f"   {s['reason']}: {s['record']}")