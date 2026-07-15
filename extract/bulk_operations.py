"""
Shopify Bulk Operations — submit + poll plumbing (Stage 3 Phase A).

This module builds the reusable machinery for a ONE-TIME historical backfill of
Shopify orders via the Bulk Operations API. Bulk Operations run a single GraphQL
query server-side and return the whole result set as a downloadable JSONL file,
which avoids the cursor-pagination cost of the nightly extractor for large pulls.

⚠️  PHASE A SCOPE — READ THIS
    This file STOPS at "print the result URL". It deliberately does NOT download
    the JSONL, parse it, or load anything into BigQuery. Those are Phase B/C and
    depend on decisions still pending with Mason (see module docstring TODO at
    bottom / tests/README + the Phase A summary).

⚠️  GraphiQL VALIDATION REQUIRED BEFORE PHASE B
    The bulk query built here has NOT been executed against a live store by an
    automated test (tests are fully mocked/offline). A human MUST paste the query
    printed by `python -m extract.bulk_operations` into Shopify's GraphiQL app,
    against the app's configured API version (extract.shopify_client.API_VERSION)
    with the app's real scopes, and confirm it validates and returns orders
    BEFORE this is trusted for a real backfill.

Nothing in this module runs on import — a real bulk operation is only submitted
when the CLI is invoked explicitly with `--submit`.
"""

import argparse
import json
import time

from extract.shopify_client import (
    API_VERSION,
    CONNECT_TIMEOUT,
    READ_TIMEOUT,
    _SESSION,
    run_query,
)


# Terminal states for a bulk operation. COMPLETED is success; the rest are
# failure modes we surface as errors rather than silently returning.
_SUCCESS_STATES = {"COMPLETED"}
_FAILURE_STATES = {"FAILED", "CANCELED", "EXPIRED"}
_TERMINAL_STATES = _SUCCESS_STATES | _FAILURE_STATES


def build_orders_bulk_query(updated_at=None) -> str:
    """
    Build the GraphQL query document for a bulk orders export.

    This returns the *inner* query (the document that goes inside the
    `bulkOperationRunQuery(query: "...")` mutation) — submit_bulk_query() wraps
    it into the mutation. Returning the inner query alone is also exactly what a
    human pastes into GraphiQL to validate it.

    Fields mirror extract/extract_orders.py so the backfill produces the same
    shape as the nightly incremental pull.

    Bulk Operation constraints honored here:
      * No `first:`/`last:` argument on ANY connection (bulk rejects them and
        streams every child as its own JSONL record, linked via __parentId).
      * <= 2 levels of nesting: orders -> lineItems is the single nested
        connection.

    Args:
        updated_at: optional cutoff string (e.g. "2023-01-01T00:00:00Z"). When
            provided, only orders updated on/after it are exported. None means
            full history (no filter clause) — the backfill default.
    """
    # Optional Shopify search filter. Note bulk queries still support `query:`
    # (a search-string arg), just not pagination args.
    if updated_at is None:
        orders_args = ""
    else:
        orders_args = f'(query: "updated_at:>={updated_at}")'

    # lineItems has NO `first:` — bulk returns all children as separate records.
    return f"""
{{
  orders{orders_args} {{
    edges {{
      node {{
        id
        name
        createdAt
        updatedAt
        displayFinancialStatus
        displayFulfillmentStatus
        totalPriceSet {{
          shopMoney {{
            amount
            currencyCode
          }}
        }}
        subtotalPriceSet {{
          shopMoney {{
            amount
          }}
        }}
        totalDiscountsSet {{
          shopMoney {{
            amount
          }}
        }}
        totalRefundedSet {{
          shopMoney {{
            amount
          }}
        }}
        customer {{
          id
        }}
        lineItems {{
          edges {{
            node {{
              id
              title
              quantity
              variant {{
                id
                sku
                price
              }}
            }}
          }}
        }}
      }}
    }}
  }}
}}
""".strip()


def submit_bulk_query(query: str) -> str:
    """
    Submit a bulk operation via the bulkOperationRunQuery mutation.

    Reuses extract.shopify_client.run_query (hardened session: retries,
    timeouts, connection pooling). Returns the bulk operation ID.

    Raises RuntimeError if Shopify returns userErrors or an unexpected payload.
    """
    # Embed the query as a GraphQL block string ("""...""") to avoid brittle
    # escaping of the inner document's quotes/newlines.
    mutation = f"""
mutation {{
  bulkOperationRunQuery(
    query: \"\"\"
{query}
\"\"\"
  ) {{
    bulkOperation {{
      id
      status
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()

    result = run_query(mutation)

    payload = (result or {}).get("data", {}).get("bulkOperationRunQuery")
    if payload is None:
        raise RuntimeError(f"❌ Unexpected bulkOperationRunQuery response: {result!r}")

    user_errors = payload.get("userErrors") or []
    if user_errors:
        raise RuntimeError(f"❌ Bulk operation submit failed with userErrors: {user_errors}")

    operation = payload.get("bulkOperation")
    if not operation or not operation.get("id"):
        raise RuntimeError(f"❌ Bulk operation submit returned no operation id: {payload!r}")

    operation_id = operation["id"]
    print(f"🚀 Bulk operation submitted: {operation_id} (status: {operation.get('status')})")
    return operation_id


def _fetch_operation(operation_id: str) -> dict:
    """Fetch the current state of a specific bulk operation via node(id:)."""
    query = f"""
{{
  node(id: "{operation_id}") {{
    ... on BulkOperation {{
      id
      status
      errorCode
      createdAt
      completedAt
      objectCount
      fileSize
      url
      partialDataUrl
    }}
  }}
}}
""".strip()

    result = run_query(query)
    node = (result or {}).get("data", {}).get("node")
    if node is None:
        raise RuntimeError(
            f"❌ Bulk operation not found (node id={operation_id!r}): {result!r}"
        )
    return node


def poll_until_done(operation_id: str, interval: int = 10, timeout: int = 1800) -> dict:
    """
    Poll a bulk operation until it reaches a terminal state or times out.

    Args:
        operation_id: the gid returned by submit_bulk_query.
        interval: seconds between polls.
        timeout: max seconds to wait before raising TimeoutError.

    Returns the final operation object (dict with url, objectCount, status, ...)
    when status is COMPLETED.

    Raises:
        RuntimeError on FAILED / CANCELED / EXPIRED.
        TimeoutError if the operation does not finish within `timeout`.
    """
    start = time.monotonic()

    while True:
        operation = _fetch_operation(operation_id)
        status = operation.get("status")
        object_count = operation.get("objectCount")
        print(f"⏳ Bulk operation {status} — objectCount={object_count}")

        if status in _SUCCESS_STATES:
            print(f"✅ Bulk operation COMPLETED — objectCount={object_count}")
            return operation

        if status in _FAILURE_STATES:
            raise RuntimeError(
                f"❌ Bulk operation ended in {status} "
                f"(errorCode={operation.get('errorCode')})"
            )

        elapsed = time.monotonic() - start
        if elapsed > timeout:
            raise TimeoutError(
                f"❌ Bulk operation {operation_id} did not finish within "
                f"{timeout}s (last status: {status}, objectCount={object_count})"
            )

        time.sleep(interval)


# --------------------------------------------------------------------------- #
# Phase B — download + parse the result JSONL
# --------------------------------------------------------------------------- #

# Print a progress line every this many parsed records.
_PROGRESS_EVERY = 500


def download_and_parse(url: str) -> tuple[list[dict], list[dict]]:
    """
    Stream the bulk-operation result JSONL from a signed URL and parse it into
    the exact shape transform.normalize_orders.normalize_orders() expects.

    Shopify Bulk Operations return ONE JSONL object per line. Because bulk
    queries forbid `first:` on connections, each order's line items are NOT
    inlined — every line item is emitted as its own record carrying a
    `__parentId` that points back at its order's gid. So:

      * A record WITHOUT `__parentId` is an ORDER (a parent).
      * A record WITH `__parentId` is a LINE ITEM (a child of that order).

    We reconstruct the nested connection normalize_orders() reads
    (`order["lineItems"]["edges"][i]["node"]`) by attaching each child to its
    parent's edges list. Shopify emits a parent before its children, so a single
    streaming pass suffices; a child whose parent was never seen is skipped
    gracefully (counted + warned, never a crash).

    Field names are left in Shopify's native camelCase (createdAt,
    displayFinancialStatus, totalPriceSet, ...) and IDs are left as GID strings
    (gid://shopify/Order/123) — that is exactly what normalize_orders() consumes,
    and fact_orders.order_id / fact_order_lines.line_item_id are STRING columns.

    Streams line by line (never buffers the whole file) via the hardened
    shopify_client session (retries + timeouts already configured).

    Args:
        url: the signed result URL from a COMPLETED bulk operation.

    Returns:
        (orders, line_items) where:
          * orders     — order dicts, each with a rebuilt lineItems.edges list,
                         ready to hand straight to normalize_orders().
          * line_items — the flat list of every line-item node (for counts /
                         summary / sample inspection).
    """
    print("⬇️  Streaming bulk result JSONL from signed URL...")
    response = _SESSION.get(
        url, stream=True, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"❌ Failed to download bulk result: HTTP {response.status_code} "
            f"{response.text[:500]!r}"
        )

    orders: list[dict] = []
    line_items: list[dict] = []
    orders_by_id: dict[str, dict] = {}
    orphan_count = 0
    record_count = 0

    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue  # skip blank/keepalive lines
        if isinstance(raw_line, bytes):  # defensive: decode_unicode not honored
            raw_line = raw_line.decode("utf-8")

        record = json.loads(raw_line)
        record_count += 1

        parent_id = record.get("__parentId")
        if parent_id is None:
            # Parent order. Seed an empty lineItems connection for its children
            # to slot into as they stream past.
            record["lineItems"] = {"edges": []}
            orders_by_id[record["id"]] = record
            orders.append(record)
        else:
            # Child line item. Link it to its parent order.
            parent = orders_by_id.get(parent_id)
            if parent is None:
                orphan_count += 1
                continue
            parent["lineItems"]["edges"].append({"node": record})
            line_items.append(record)

        if record_count % _PROGRESS_EVERY == 0:
            print(
                f"   ...parsed {record_count} records "
                f"({len(orders)} orders, {len(line_items)} line items)"
            )

    print(
        f"✅ Parsed {record_count} records: "
        f"{len(orders)} orders, {len(line_items)} line items"
    )
    if orphan_count:
        print(
            f"⚠️  Skipped {orphan_count} line item(s) with no matching parent "
            f"order (orphans)"
        )

    # Dump one of each so a human can verify the field mapping BEFORE any load.
    if orders:
        print("\n📋 Sample parsed ORDER dict (as fed to normalize_orders):")
        print(json.dumps(orders[0], indent=2, default=str))
    if line_items:
        print("\n📋 Sample parsed LINE ITEM dict:")
        print(json.dumps(line_items[0], indent=2, default=str))

    return orders, line_items


_GRAPHIQL_TODO = f"""
──────────────────────────────────────────────────────────────────────────────
📋 TODO (HUMAN, before Phase B): validate the query above in Shopify GraphiQL.
   • Open the Shopify Admin API GraphiQL app for the store.
   • Confirm it targets API version {API_VERSION} with the app's real scopes
     (read_orders / read_customers as needed).
   • Paste the query printed above and confirm it validates and returns orders.
   • Only after that is this bulk query trusted for a real backfill.
──────────────────────────────────────────────────────────────────────────────
""".strip()


def main(argv=None):
    """
    CLI entry. By default (no --submit) this ONLY prints the query + a GraphiQL
    validation TODO — it does not touch the network. Pass --submit to actually
    run the bulk operation and poll it to completion (prints the result URL;
    does NOT download it).
    """
    parser = argparse.ArgumentParser(
        description="Stage 3 Phase A — Shopify Bulk Operation submit + poll "
        "(read-only; prints result URL, does not download)."
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Actually submit the bulk operation and poll it. Without this "
        "flag, only the query + GraphiQL TODO are printed (no network).",
    )
    parser.add_argument(
        "--updated-at",
        default=None,
        help="Optional cutoff, e.g. 2023-01-01T00:00:00Z. Omit for full history.",
    )
    parser.add_argument("--interval", type=int, default=10, help="Poll interval (s).")
    parser.add_argument("--timeout", type=int, default=1800, help="Poll timeout (s).")
    args = parser.parse_args(argv)

    query = build_orders_bulk_query(updated_at=args.updated_at)

    print("=" * 78)
    print("Shopify Bulk Operations — orders backfill query (Phase A)")
    print("=" * 78)
    print(query)
    print()
    print(_GRAPHIQL_TODO)

    if not args.submit:
        print()
        print("ℹ️  Dry run — no operation submitted. Re-run with --submit to execute.")
        return

    print()
    print("🚀 --submit given: submitting bulk operation...")
    started = time.monotonic()
    operation_id = submit_bulk_query(query)
    operation = poll_until_done(
        operation_id, interval=args.interval, timeout=args.timeout
    )
    elapsed = time.monotonic() - started

    print()
    print("=" * 78)
    print("✅ Bulk operation finished (Phase A ends here — NOT downloaded)")
    print("=" * 78)
    print(f"   Operation ID: {operation.get('id')}")
    print(f"   Status:       {operation.get('status')}")
    print(f"   Object count: {operation.get('objectCount')}")
    print(f"   Elapsed:      {elapsed:.1f}s")
    print(f"   Result URL:   {operation.get('url')}")
    print()
    print("👉 Phase B (download + parse JSONL) and Phase C (load to BigQuery) are "
          "separate tasks — see the Phase A summary / Mason's open questions.")


if __name__ == "__main__":
    main()
