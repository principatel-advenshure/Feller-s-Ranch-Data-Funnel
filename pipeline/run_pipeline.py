"""
Main pipeline entry point.
Runs full ETL: Extract → Transform → QA → Load
"""

import time
from extract.extract_orders import extract_orders
from extract.extract_products import extract_products
from extract.extract_customers import extract_customers
from extract.extract_inventory import extract_inventory
from transform.normalize_orders import normalize_orders
from transform.normalize_products import normalize_products
from transform.normalize_customers import normalize_customers
from transform.variable_weight import resolve_variable_weight_orders
from transform.qa_checks import run_qa_checks
from load.bigquery_client import setup_all_tables
from load.load_facts import load_fact_orders, load_fact_order_lines
from load.load_dims import load_dim_products, load_dim_customers, load_dim_stores


def run_pipeline():
    start_time = time.time()
    print("🚀 Starting Feller's Ranch Data Pipeline")
    print("=" * 50)

    # ── Step 1: Setup tables ──
    print("\n📋 Step 1 — Setting up BigQuery tables...")
    setup_all_tables()

    # ── Step 2: Extract ──
    print("\n📤 Step 2 — Extracting data from Shopify...")
    raw_orders = extract_orders()
    raw_products = extract_products()
    raw_customers = extract_customers()
    raw_inventory = extract_inventory()

    # ── Step 3: Transform ──
    print("\n🔄 Step 3 — Transforming data...")
    fact_orders, fact_order_lines = normalize_orders(raw_orders)
    normalized_products, unmapped_products = normalize_products(raw_products)
    normalized_customers = normalize_customers(raw_customers)
    standard_lines, variable_lines = resolve_variable_weight_orders(fact_order_lines)
    all_lines = standard_lines + variable_lines

    # ── Step 4: QA ──
    print("\n🔍 Step 4 — Running QA checks...")
    report = run_qa_checks(
        fact_orders, all_lines,
        normalized_products, unmapped_products,
        normalized_customers
    )

    print(f"   Status: {'✅ PASSED' if report['passed'] else '⚠️ WARNINGS FOUND'}")
    for issue in report["issues"]:
        print(f"   {issue}")
    for warning in report["warnings"]:
        print(f"   {warning}")

    # ── Step 5: Load ──
    print("\n💾 Step 5 — Loading data into BigQuery...")
    load_fact_orders(fact_orders)
    load_fact_order_lines(all_lines)
    load_dim_products(normalized_products, unmapped_products)
    load_dim_customers(normalized_customers)
    load_dim_stores()

    # ── Done ──
    elapsed = round(time.time() - start_time, 2)
    print("\n" + "=" * 50)
    print(f"✅ Pipeline completed in {elapsed}s")
    print(f"   Orders loaded:    {len(fact_orders)}")
    print(f"   Order lines:      {len(all_lines)}")
    print(f"   Products loaded:  {len(normalized_products) + len(unmapped_products)}")
    print(f"   Customers loaded: {len(normalized_customers)}")
    print("=" * 50)


if __name__ == "__main__":
    run_pipeline()