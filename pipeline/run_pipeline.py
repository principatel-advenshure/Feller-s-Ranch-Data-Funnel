"""
Main pipeline entry point.
Runs full ETL: Extract → Transform → QA → Load
With retry logic, state tracking, and failure handling.
"""

import time
from pipeline.error_handler import (
    log, with_retry, save_state, is_step_completed,
    clear_state, get_pipeline_decision, send_alert
)
from auth.token_manager import refresh_token_if_needed
from extract.extract_orders import extract_orders
from extract.extract_products import extract_products
from extract.extract_customers import extract_customers
from extract.extract_inventory import extract_inventory
from extract.airtable_client import extract_sku_mapping
from extract.extract_quickbooks import extract_all_b2b_sales
from transform.normalize_orders import normalize_orders
from transform.normalize_products import normalize_products
from transform.normalize_customers import normalize_customers
from transform.variable_weight import resolve_variable_weight_orders
from transform.normalize_quickbooks import normalize_quickbooks
from transform.qa_checks import run_qa_checks
from load.bigquery_client import setup_all_tables, upsert_rows
from load.load_facts import load_fact_orders, load_fact_order_lines
from load.load_dims import load_dim_products, load_dim_customers, load_dim_stores
from load.load_b2b import load_fact_b2b_invoices, load_fact_b2b_invoice_lines
from pipeline.summary_generator import generate_summary


def safe_clear_staging(table_name: str):
    """Clear a dirty staging table safely before retrying."""
    try:
        from load.bigquery_client import get_client, get_table_ref
        client = get_client()
        staging_ref = get_table_ref(f"{table_name}_staging")
        client.query(f"DELETE FROM `{staging_ref}` WHERE TRUE").result()
        log("INFO", "staging", f"Cleared dirty staging table: {table_name}_staging")
    except Exception as e:
        log("WARNING", "staging", f"Could not clear staging for {table_name}", e)


def run_pipeline(resume: bool = False):
    """
    Run the full ETL pipeline with error handling.

    Args:   ps
    """
    start_time = time.time()

    if not resume:
        clear_state()

    log("INFO", "pipeline", "🚀 Starting Feller's Ranch Data Pipeline")
    print("=" * 50)

    try:
        # ── Step 0: Validate Shopify token ──
        log("INFO", "auth", "Validating Shopify token...")
        with_retry(refresh_token_if_needed, "auth", "fellers_ranch")
        log("SUCCESS", "auth", "Token valid — proceeding")

        # ── Step 1: Setup tables ──
        if not is_step_completed("setup"):
            log("INFO", "setup", "Setting up BigQuery tables...")
            with_retry(setup_all_tables, "setup")
            save_state("setup", "completed")
        else:
            log("INFO", "setup", "Skipping — already completed")

        # ── Step 2: Extract ──
        raw_orders = raw_products = raw_customers = raw_inventory = None

        if not is_step_completed("extract_orders"):
            log("INFO", "extract", "Extracting orders...")
            raw_orders = with_retry(extract_orders, "extract_orders")
            save_state("extract_orders", "completed")
        else:
            log("INFO", "extract_orders", "Skipping — already completed")
            raw_orders = extract_orders()

        if not is_step_completed("extract_products"):
            log("INFO", "extract", "Extracting products...")
            raw_products = with_retry(extract_products, "extract_products")
            save_state("extract_products", "completed")
        else:
            log("INFO", "extract_products", "Skipping — already completed")
            raw_products = extract_products()

        if not is_step_completed("extract_customers"):
            log("INFO", "extract", "Extracting customers...")
            raw_customers = with_retry(extract_customers, "extract_customers")
            save_state("extract_customers", "completed")
        else:
            log("INFO", "extract_customers", "Skipping — already completed")
            raw_customers = extract_customers()

        if not is_step_completed("extract_inventory"):
            log("INFO", "extract", "Extracting inventory...")
            raw_inventory = with_retry(extract_inventory, "extract_inventory")
            save_state("extract_inventory", "completed")
        else:
            log("INFO", "extract_inventory", "Skipping — already completed")
            raw_inventory = extract_inventory()

        # ── Step 3: Transform ──
        if not is_step_completed("transform"):
            log("INFO", "transform", "Transforming data...")
            fact_orders, fact_order_lines = normalize_orders(raw_orders)
            sku_mapping = extract_sku_mapping()
            normalized_products, unmapped_products = normalize_products(raw_products, sku_mapping)
            normalized_customers = normalize_customers(raw_customers, fact_orders)
            standard_lines, variable_lines = resolve_variable_weight_orders(fact_order_lines)
            all_lines = standard_lines + variable_lines
            save_state("transform", "completed")
        else:
            log("INFO", "transform", "Skipping — already completed")
            fact_orders, fact_order_lines = normalize_orders(raw_orders)
            sku_mapping = extract_sku_mapping()
            normalized_products, unmapped_products = normalize_products(raw_products, sku_mapping)
            normalized_customers = normalize_customers(raw_customers, fact_orders)
            standard_lines, variable_lines = resolve_variable_weight_orders(fact_order_lines)
            all_lines = standard_lines + variable_lines

        # ── Step 4: QA checks ──
        if not is_step_completed("qa_checks"):
            log("INFO", "qa", "Running QA checks...")
            report = run_qa_checks(
                fact_orders, all_lines,
                normalized_products, unmapped_products,
                normalized_customers
            )
            status = "✅ PASSED" if report["passed"] else "⚠️ WARNINGS FOUND"
            log("INFO", "qa", f"QA Status: {status}")
            for issue in report["issues"]:
                log("WARNING", "qa", issue)
            for warning in report["warnings"]:
                log("WARNING", "qa", warning)
            save_state("qa_checks", "completed")

        # ── Step 5: Load Shopify data ──
        load_steps = {
            "load_fact_orders": (
                load_fact_orders, [fact_orders], "fact_orders"
            ),
            "load_fact_order_lines": (
                load_fact_order_lines, [all_lines], "fact_order_lines"
            ),
            "load_dim_products": (
                load_dim_products, [normalized_products, unmapped_products], "dim_products"
            ),
            "load_dim_customers": (
                load_dim_customers, [normalized_customers], "dim_customers"
            ),
            "load_dim_stores": (
                load_dim_stores, [], "dim_stores"
            ),
        }

        for step_name, (func, args, table_name) in load_steps.items():
            if is_step_completed(step_name):
                log("INFO", step_name, "Skipping — already completed")
                continue

            log("INFO", step_name, f"Loading {table_name}...")
            safe_clear_staging(table_name)

            try:
                with_retry(func, step_name, *args)
                save_state(step_name, "completed")

            except Exception as e:
                log("ERROR", step_name, f"Failed to load {table_name}", e)
                safe_clear_staging(table_name)
                decision = get_pipeline_decision(step_name)

                if decision == "restart":
                    log("INFO", "pipeline",
                        "Restarting pipeline from scratch...")
                    clear_state()
                    run_pipeline(resume=False)
                    return
                else:
                    log("INFO", "pipeline",
                        f"Continuing pipeline — skipping {table_name}")
                    save_state(step_name, "failed")
                    continue

        # ── Step 5b: Load B2B QuickBooks data ──
        if not is_step_completed("load_b2b"):
            log("INFO", "load_b2b", "Loading QuickBooks B2B data...")
            raw_b2b = extract_all_b2b_sales()
            fact_b2b_invoices, fact_b2b_lines, _ = normalize_quickbooks(raw_b2b)
            safe_clear_staging("fact_b2b_invoices")
            safe_clear_staging("fact_b2b_invoice_lines")
            load_fact_b2b_invoices(fact_b2b_invoices)
            load_fact_b2b_invoice_lines(fact_b2b_lines)
            save_state("load_b2b", "completed")
            log("SUCCESS", "load_b2b",
                f"B2B loaded — {len(fact_b2b_invoices)} invoices · {len(fact_b2b_lines)} lines")
        else:
            log("INFO", "load_b2b", "Skipping — already completed")

        # ── Step 6: Generate summary ──
        log("INFO", "summary", "Generating pipeline summary...")
        summary = generate_summary(fact_orders, all_lines, normalized_customers, fact_b2b_invoices, fact_b2b_lines)
        upsert_rows("pipeline_summary", [summary], key_field="summary_id")
        log("SUCCESS", "summary", f"Summary saved — {summary['summary_text'][:80]}...")

        # ── Done ──
        elapsed = round(time.time() - start_time, 2)
        log("SUCCESS", "pipeline", f"Pipeline completed in {elapsed}s")
        print("=" * 50)
        print(f"✅ Pipeline completed in {elapsed}s")
        print(f"   Orders:       {len(fact_orders)}")
        print(f"   Lines:        {len(all_lines)}")
        print(f"   Products:     {len(normalized_products) + len(unmapped_products)}")
        print(f"   Customers:    {len(normalized_customers)}")
        print(f"   B2B invoices: {len(fact_b2b_invoices)}")
        print(f"   B2B lines:    {len(fact_b2b_lines)}")
        print("=" * 50)

        # Clear state on success
        clear_state()

    except Exception as e:
        log("ERROR", "pipeline", "Pipeline failed unexpectedly", e)
        send_alert("pipeline", e)
        raise


if __name__ == "__main__":
    import sys
    resume = "--resume" in sys.argv
    run_pipeline(resume=resume)