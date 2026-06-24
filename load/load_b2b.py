"""
Load B2B QuickBooks invoice data into BigQuery.
"""

from load.bigquery_client import upsert_rows


def load_fact_b2b_invoices(fact_invoices: list):
    """Load normalized B2B invoices into fact_b2b_invoices table."""
    print(f"📤 Loading {len(fact_invoices)} B2B invoices into BigQuery...")
    upsert_rows("fact_b2b_invoices", fact_invoices, key_field="invoice_id")


def load_fact_b2b_invoice_lines(fact_lines: list):
    """Load normalized B2B invoice lines into fact_b2b_invoice_lines table."""
    print(f"📤 Loading {len(fact_lines)} B2B invoice lines into BigQuery...")
    upsert_rows("fact_b2b_invoice_lines", fact_lines, key_field="line_id")


if __name__ == "__main__":
    from extract.extract_quickbooks import extract_all_b2b_sales
    from transform.normalize_quickbooks import normalize_quickbooks

    print("🔄 Running B2B load...\n")

    raw_records = extract_all_b2b_sales()
    fact_invoices, fact_lines, skipped = normalize_quickbooks(raw_records)

    load_fact_b2b_invoices(fact_invoices)
    load_fact_b2b_invoice_lines(fact_lines)

    print(f"\n✅ B2B data loaded successfully!")
    print(f"   Invoices:    {len(fact_invoices)}")
    print(f"   Line items:  {len(fact_lines)}")
    print(f"   Skipped:     {len(skipped)}")