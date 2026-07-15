"""
scripts/backfill_orders.py — Stage 3 Phase B+C driver.

One-time historical backfill of Shopify orders into BigQuery. Ties the three
phases together:

    Phase A  submit bulk op + poll to COMPLETED        (extract.bulk_operations)
    Phase B  download + parse the result JSONL          (download_and_parse)
    Phase C  normalize + idempotent upsert into BigQuery (normalize_orders +
                                                          load.bigquery_client)

Two mutually-exclusive entry modes:

    --url <signed-url>   Skip submit/poll and load an EXISTING result URL. Use
                         this to re-run a load (idempotent) or to consume a URL
                         produced by an earlier `--submit` / Phase A run.
    --submit             Submit a fresh bulk operation, poll it to completion,
                         then download + load its result.

Idempotency: every load goes through load.bigquery_client.upsert_rows (staging
table + MERGE), batched in chunks of 500 rows. Re-running with the same URL
loads 0 net-new rows.

Run from anywhere (repo root is added to sys.path below):

    python scripts/backfill_orders.py --url "https://storage.googleapis.com/..."
    python scripts/backfill_orders.py --submit
"""

import argparse
import os
import sys
import time

# Make the repo root importable so `extract.` / `transform.` / `load.` resolve
# no matter what directory this script is launched from.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from extract.bulk_operations import (  # noqa: E402
    build_orders_bulk_query,
    download_and_parse,
    poll_until_done,
    submit_bulk_query,
)
from load.bigquery_client import (  # noqa: E402
    create_table_if_not_exists,
    get_client,
    get_table_ref,
    upsert_rows,
)
from transform.normalize_orders import normalize_orders  # noqa: E402
from transform.variable_weight import resolve_variable_weight_orders  # noqa: E402


# Chunk size for staged MERGE upserts — never load everything in one call.
BATCH_SIZE = 500


def _count(client, table: str, key_field: str) -> tuple[int, int]:
    """Return (total_rows, distinct_keys) for a table."""
    ref = get_table_ref(table)
    query = (
        f"SELECT COUNT(*) AS total, "
        f"COUNT(DISTINCT {key_field}) AS distinct_keys "
        f"FROM `{ref}`"
    )
    row = list(client.query(query).result())[0]
    return int(row["total"]), int(row["distinct_keys"])


def _upsert_in_batches(table: str, rows: list, key_field: str) -> None:
    """Upsert rows through the MERGE path in fixed-size batches."""
    if not rows:
        upsert_rows(table, rows, key_field=key_field)  # prints the empty warning
        return

    total = len(rows)
    for start in range(0, total, BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        print(
            f"   📦 {table}: batch rows {start + 1}-{start + len(batch)} "
            f"of {total}"
        )
        upsert_rows(table, batch, key_field=key_field)


def run_backfill(url: str, operation_id: str | None, started: float) -> None:
    """
    Phase B + C: download + parse `url`, normalize, and idempotently load into
    BigQuery, then print a summary with before/after row counts.
    """
    # --- Phase B: download + parse (prints sample dicts for human review) ---
    orders, line_items = download_and_parse(url)

    # --- Normalize (reuse the nightly transform) ---
    # `orders` already carry rebuilt lineItems.edges, so normalize_orders reads
    # them exactly as it reads the incremental pull.
    fact_orders, fact_order_lines = normalize_orders(orders)

    # Mirror the production load path (load/load_facts.py): tag variable-weight
    # lines so the is_variable_weight column is populated.
    standard_lines, variable_lines = resolve_variable_weight_orders(fact_order_lines)
    all_lines = standard_lines + variable_lines

    print(
        f"\n🧮 Normalized: {len(fact_orders)} fact_orders, "
        f"{len(all_lines)} fact_order_lines "
        f"({len(variable_lines)} variable-weight)"
    )

    # --- Phase C: load into BigQuery (idempotent MERGE, batched) ---
    client = get_client()
    # Ensure main tables exist (idempotent). upsert_rows only creates staging.
    create_table_if_not_exists("fact_orders")
    create_table_if_not_exists("fact_order_lines")

    print("\n🔎 Counting rows BEFORE load...")
    orders_before = _count(client, "fact_orders", "order_id")
    lines_before = _count(client, "fact_order_lines", "line_item_id")

    print("\n📤 Loading fact_orders...")
    _upsert_in_batches("fact_orders", fact_orders, key_field="order_id")
    print("\n📤 Loading fact_order_lines...")
    _upsert_in_batches("fact_order_lines", all_lines, key_field="line_item_id")

    print("\n🔎 Counting rows AFTER load...")
    orders_after = _count(client, "fact_orders", "order_id")
    lines_after = _count(client, "fact_order_lines", "line_item_id")

    elapsed = time.monotonic() - started

    # --- Summary ---
    print("\n" + "=" * 78)
    print("✅ Backfill complete")
    print("=" * 78)
    print(f"   Operation ID:         {operation_id or 'N/A (--url re-run)'}")
    print(f"   Result URL:           {url[:80]}...")
    print(f"   Parsed orders:        {len(orders)}")
    print(f"   Parsed line items:    {len(line_items)}")
    print(f"   Normalized orders:    {len(fact_orders)}")
    print(f"   Normalized lines:     {len(all_lines)}")
    print(f"   Elapsed:              {elapsed:.1f}s")
    print("   ── BigQuery row counts (total / distinct key) ──")
    print(
        f"   fact_orders:          {orders_before[0]} → {orders_after[0]} "
        f"(distinct order_id: {orders_after[1]})"
    )
    print(
        f"   fact_order_lines:     {lines_before[0]} → {lines_after[0]} "
        f"(distinct line_item_id: {lines_after[1]})"
    )
    net_orders = orders_after[0] - orders_before[0]
    net_lines = lines_after[0] - lines_before[0]
    print(f"   Net new orders:       {net_orders}")
    print(f"   Net new lines:        {net_lines}")

    # --- Idempotency check: total == distinct in fact_orders ---
    print("\n🔐 Idempotency check (fact_orders): total vs distinct order_id...")
    if orders_after[0] == orders_after[1]:
        print(
            f"   ✅ PASS — {orders_after[0]} rows == {orders_after[1]} distinct "
            f"order_id (no duplicates)"
        )
    else:
        print(
            f"   ❌ FAIL — {orders_after[0]} rows != {orders_after[1]} distinct "
            f"order_id (duplicates present!)"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Stage 3 Phase B+C — download, parse, and load the Shopify "
        "bulk-operation orders export into BigQuery (idempotent)."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--url",
        help="Signed result URL of an already-COMPLETED bulk operation. Skips "
        "submit/poll and goes straight to download + load.",
    )
    mode.add_argument(
        "--submit",
        action="store_true",
        help="Submit a fresh bulk operation, poll to completion, then download "
        "+ load its result.",
    )
    parser.add_argument(
        "--updated-at",
        default=None,
        help="(--submit only) cutoff, e.g. 2023-01-01T00:00:00Z. "
        "Omit for full history.",
    )
    parser.add_argument("--interval", type=int, default=10, help="Poll interval (s).")
    parser.add_argument("--timeout", type=int, default=1800, help="Poll timeout (s).")
    args = parser.parse_args(argv)

    started = time.monotonic()
    operation_id = None

    if args.submit:
        print("🚀 --submit: submitting a fresh bulk operation...")
        query = build_orders_bulk_query(updated_at=args.updated_at)
        operation_id = submit_bulk_query(query)
        operation = poll_until_done(
            operation_id, interval=args.interval, timeout=args.timeout
        )
        operation_id = operation.get("id")
        url = operation.get("url")
        if not url:
            raise RuntimeError(
                f"❌ Bulk operation {operation_id} COMPLETED but returned no url: "
                f"{operation!r}"
            )
        print(f"   Result URL: {url}")
    else:
        url = args.url

    run_backfill(url, operation_id, started)


if __name__ == "__main__":
    main()
