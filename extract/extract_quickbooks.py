"""
QuickBooks Sales by Item Detail CSV extractor.
Parses exported CSV files from QuickBooks Desktop via Google Sheets conversion.

Report structure:
  - Row 1: column headers (Type, Date, Num, Memo, Name, Qty, U/M, Sales Price, Amount, Balance)
           with double empty columns between each
  - Category rows: e.g. "Inventory"
  - Product group header rows: SKU + product name
  - Invoice transaction rows: Type='Invoice'
  - Subtotal rows: start with 'Total'
  - Grand Total row
"""

import os
import csv
from datetime import datetime
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


QB_DATA_DIR = os.getenv(
    "QB_DATA_DIR",
    "/Users/principatel/Documents/Projects/FR B2B data"
)

TRANSACTION_TYPES = {"Invoice", "Credit Memo", "Sales Receipt", "Cash Sale"}


def _to_float(val: str):
    if not val or not val.strip():
        return None
    try:
        return float(val.replace(",", "").strip())
    except ValueError:
        return None


def _parse_date(val: str):
    if not val or not val.strip():
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(val.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return val.strip()


def parse_csv(filepath: str) -> list:
    """
    Parse one QuickBooks Sales by Item Detail CSV file.
    Returns a flat list of dicts — one per invoice line item.
    """
    records = []
    current_product = None
    col = {}

    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)

        for row_idx, row in enumerate(reader):

            # Skip completely empty rows
            non_empty = [v.strip() for v in row if v.strip()]
            if not non_empty:
                continue

            # ── Find column header row ──
            if not col and "Type" in row and "Date" in row and "Amount" in row:
                col = {v.strip(): i for i, v in enumerate(row) if v.strip()}
                continue

            # Skip until we find headers
            if not col:
                continue

            type_val = row[col["Type"]].strip() if "Type" in col else ""

            # ── Skip subtotal and grand total rows ──
            if type_val.lower().startswith("total") or "grand total" in type_val.lower():
                continue

                    # ── Skip category rows (Inventory, Other Charges) ──
            # Product group headers have empty Type but value in column 2
            if not type_val:
                # Check column index 2 for product name
                product_val = row[2].strip() if len(row) > 2 else ""
                if product_val and not product_val.lower().startswith("total"):
                    current_product = product_val
                continue

            if type_val and type_val not in TRANSACTION_TYPES:
                date_val = row[col["Date"]].strip() if "Date" in col else ""
                if not date_val:
                    continue

            # ── Real transaction rows ──
            if type_val not in TRANSACTION_TYPES:
                continue

            records.append({
                "invoice_num":          row[col["Num"]].strip() if "Num" in col else "",
                "date":                 _parse_date(row[col["Date"]]) if "Date" in col else None,
                "customer_name":        row[col["Name"]].strip() if "Name" in col else "",
                "product_description":  current_product or "",
                "memo":                 row[col["Memo"]].strip() if "Memo" in col else "",
                "quantity":             _to_float(row[col["Qty"]]) if "Qty" in col else None,
                "unit_of_measure":      row[col["U/M"]].strip() if "U/M" in col else "",
                "unit_price":           _to_float(row[col["Sales Price"]]) if "Sales Price" in col else None,
                "line_amount":          _to_float(row[col["Amount"]]) if "Amount" in col else None,
                "source_file":          os.path.basename(filepath),
            })

    return records


def extract_b2b_sales(filename: str) -> list:
    """Load a named CSV file from the QB data directory."""
    path = os.path.join(QB_DATA_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Not found: {path}")
    return parse_csv(path)


def extract_all_b2b_sales() -> list:
    """Extract all available monthly CSV files."""
    all_records = []
    files = [
        "Fellers April 2026 Sales Detail.csv",
        "Fellers May 2026 Sales Detail.csv",
    ]
    for filename in files:
        path = os.path.join(QB_DATA_DIR, filename)
        if os.path.exists(path):
            records = parse_csv(path)
            all_records.extend(records)
            print(f"✅ {filename} — {len(records)} records")
        else:
            print(f"⚠️  {filename} — not found, skipping")
    return all_records


if __name__ == "__main__":
    files = {
        "April": "Fellers April 2026 Sales Detail.csv",
        "May":   "Fellers May 2026 Sales Detail.csv",
    }

    for month, filename in files.items():
        print(f"\n{'='*55}")
        print(f"  {month}: {filename}")
        print(f"{'='*55}")

        try:
            rows = extract_b2b_sales(filename)
        except FileNotFoundError as e:
            print(f"  ⚠️  {e}")
            continue
        except Exception as e:
            print(f"  ❌  Parse error: {e}")
            import traceback
            traceback.print_exc()
            continue

        if not rows:
            print("  ⚠️  No transaction rows found")
            continue

        invoices  = {r["invoice_num"] for r in rows}
        customers = {r["customer_name"] for r in rows}
        products  = {r["product_description"] for r in rows if r["product_description"]}
        total_amt = sum(r["line_amount"] or 0 for r in rows)
        date_min  = min(r["date"] for r in rows if r["date"])
        date_max  = max(r["date"] for r in rows if r["date"])

        print(f"  Line items   : {len(rows)}")
        print(f"  Invoices     : {len(invoices)}")
        print(f"  Customers    : {len(customers)}")
        print(f"  Products     : {len(products)}")
        print(f"  Date range   : {date_min} → {date_max}")
        print(f"  Total amount : ${total_amt:,.2f}")

        print(f"\n  Sample rows (first 3):")
        for r in rows[:3]:
            print(f"    Invoice {r['invoice_num']} | {r['date']} | {r['customer_name']}")
            print(f"      {r['product_description']} | qty={r['quantity']} "
                  f"{r['unit_of_measure']} @ ${r['unit_price']} = ${r['line_amount']}")

        print(f"\n  Top customers:")
        customer_revenue = {}
        for r in rows:
            c = r["customer_name"]
            customer_revenue[c] = customer_revenue.get(c, 0) + (r["line_amount"] or 0)
        for c, rev in sorted(customer_revenue.items(), key=lambda x: -x[1])[:5]:
            print(f"    {c}: ${rev:,.2f}")