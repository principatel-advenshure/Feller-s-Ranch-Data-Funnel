"""
Load fact tables into BigQuery.
Handles fact_orders and fact_order_lines.
"""

from load.bigquery_client import upsert_rows


def load_fact_orders(fact_orders: list):
    """Load normalized orders into fact_orders table."""
    print(f"📤 Loading {len(fact_orders)} orders into BigQuery...")
    upsert_rows("fact_orders", fact_orders, key_field="order_id")


def load_fact_order_lines(fact_order_lines: list):
    """Load normalized order lines into fact_order_lines table."""
    print(f"📤 Loading {len(fact_order_lines)} order lines into BigQuery...")
    upsert_rows("fact_order_lines", fact_order_lines, key_field="line_item_id")


if __name__ == "__main__":
    from extract.extract_orders import extract_orders
    from transform.normalize_orders import normalize_orders
    from transform.variable_weight import resolve_variable_weight_orders

    print("🔄 Running fact load...\n")

    raw_orders = extract_orders()
    fact_orders, fact_order_lines = normalize_orders(raw_orders)
    standard_lines, variable_lines = resolve_variable_weight_orders(fact_order_lines)

    # Add is_variable_weight flag to all lines
    all_lines = standard_lines + variable_lines

    load_fact_orders(fact_orders)
    load_fact_order_lines(all_lines)

    print("\n✅ Fact tables loaded successfully!")