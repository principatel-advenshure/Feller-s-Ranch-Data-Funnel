# Tests

Offline unit tests for the highest-risk, recently-fixed pipeline logic. They
make **no** network calls (Shopify / Airtable / BigQuery are all mocked) and
require **no** real credentials or `.env` — every test drives the environment
with `monkeypatch`.

## How to run

From the repo root, using the project virtualenv:

```bash
.venv/bin/python -m pytest tests/ -v
```

or, if `pytest` is on your `PATH`:

```bash
pytest
```

`pytest` is listed in the dev section of `requirements.txt`
(`pip install -r requirements.txt` installs it). It is **not** needed by the
Cloud Function at runtime.

## What's covered

| File | Module under test | What it verifies |
| --- | --- | --- |
| `test_extract_orders.py` | `extract/extract_orders.py` | `days_back=N` injects `query: "updated_at:>=<cutoff>"` with a cutoff ~N days before now (UTC); `days_back=None` produces no filter clause (full backfill); `sortKey: UPDATED_AT` in both modes; cursor pagination is threaded across pages. |
| `test_airtable_client.py` | `extract/airtable_client.py` | `_airtable_configured()` is `False` when creds are missing, partially set, or the literal `"placeholder"` (case-insensitive, whitespace-trimmed), and `True` only when both are real; `extract_sku_mapping()` / `fetch_table()` return empty **without** raising or hitting the network when unconfigured. |
| `test_bigquery_client.py` | `load/bigquery_client.py` | `upsert_rows([])` is a no-op (never builds a client); the MERGE `ON` clause uses `key_field`; the dedup `ROW_NUMBER() ... PARTITION BY key_field ... WHERE row_num = 1` is present; `UPDATE SET` excludes the key while `INSERT` includes it; staging is cleared after merge. |
| `test_bulk_operations.py` | `extract/bulk_operations.py` | `build_orders_bulk_query()` includes the orders connection + nested `lineItems` with the same core fields as the nightly extractor, puts **no** `first:`/`last:` on any connection, and respects the optional `updated_at` filter (none = full history); `submit_bulk_query()` returns the operation id on success and raises on `userErrors` / malformed payloads; `poll_until_done()` returns on `COMPLETED`, raises on `FAILED`/`CANCELED`, raises `TimeoutError` past the deadline, and raises on a missing node. All `run_query`/`time.sleep`/`time.monotonic` calls are mocked — no network, no waiting. |
| `test_shopify_client.py` | `extract/shopify_client.py` | `run_query()` returns the parsed JSON body on a 200, builds the URL from `shop_url` + the pinned `API_VERSION`, forwards the token into `X-Shopify-Access-Token`, passes the `(connect, read)` timeout tuple, and includes `variables` only when supplied; it raises on a non-200 status and on GraphQL `errors` in a 200 body. The module-level `_SESSION` is a reused singleton (never rebuilt per call) with a urllib3 `Retry` that retries POST on 429/5xx. `API_VERSION` is pinned to `2026-07`. `get_valid_token` and `_SESSION.post` are mocked — no auth, no HTTP. |
| `test_normalize_orders.py` | `transform/normalize_orders.py` | Valid orders produce the `fact_orders` shape (snake_case keys, `store`/`channel` constants, GID kept verbatim in `order_id`); monetary strings (`"99.00"`) parse to `float`, discounts/refunds default to `0.0` when absent; financial/fulfillment statuses map through; null / missing `customer` yields `None` ids without crashing; `$0` orders are filtered out; `[]` → `([], [])`; line items expand into the `fact_order_lines` shape with `line_revenue = quantity * unit_price` rounded to 2 dp, and a null `variant` degrades to `None`/`0.0`. |
| `test_normalize_customers.py` | `transform/normalize_customers.py` | Returns the `dim_customers` shape with correct types; email lower-cased + trimmed; missing `phone` / `defaultAddress` / names degrade to `None` / `"Unknown"`; missing `numberOfOrders` defaults to `0`; customers with no email are skipped; dedup by id and by (case-insensitive) email; `first_order_date` derived from `fact_orders` (earliest wins) or `None`; `[]` → `[]`. |
| `test_normalize_products.py` | `transform/normalize_products.py` | SKU fallback ladder: empty mapping falls back to the variant's own sku; a mapping hit by raw name or by raw sku uses the canonical SKU; a variant with no sku and no mapping is flagged into `unmapped` with `canonical_sku=None`; mapped vs unmapped split correctly; product/variant shape + types, weight extraction (and graceful `None` when the measurement is absent); multiple variants → multiple rows; `[]` → `([], [])`. |
| `test_qa_checks.py` | `transform/qa_checks.py` | Clean data passes with no warnings and `passed=True`; summary counts match input sizes; warnings fire for orders with no customer, lines with no/`"0"` SKU, unmapped products, `DRAFT` products, and customers with no name / no location; because these are `warnings` (not `issues`), `passed` stays `True`; empty input passes with a zeroed summary. |

## What's **not** covered (yet)

- The rest of `extract/` (`extract_customers`, `extract_products`,
  `extract_inventory`, `extract_quickbooks`). `extract/shopify_client.py` is now
  covered for the `run_query` happy path, error paths, and session/retry config;
  the token-refresh flow inside `auth/token_manager` (which `get_valid_token`
  calls) is still mocked out, not exercised.
- `transform/` is covered for `normalize_orders`, `normalize_customers`,
  `normalize_products`, and `qa_checks`. Any other transform helpers (e.g. B2B
  shaping) are not.
- `load/load_facts.py`, `load/load_dims.py`, `load/load_b2b.py` and the actual
  BigQuery load-job execution path (mocked out here).
- `run_pipeline.py` / `main.py` orchestration and the Cloud Function entrypoint
  (out of scope per the task).
- No integration tests — everything here is a pure unit test with mocked I/O.

## Notes for future refactors

These modules were straightforward to test because credentials and network
calls are read/made at *call time* behind small functions. A few friction
points worth noting:

- **`extract_orders` builds one large f-string query inline.** Tests assert on
  substrings of that string. Extracting query-building into a small pure helper
  (e.g. `build_orders_query(cursor, filter_clause)`) would make assertions less
  brittle and let the filter logic be tested without the pagination loop.
- **`bigquery_client.upsert_rows` mixes SQL construction with execution.** We
  had to patch `get_client`, `create_table_if_not_exists`, and `load_schema`
  together to isolate the MERGE SQL. Splitting out a pure
  `build_merge_query(main_ref, staging_ref, fields, key_field)` would make the
  idempotency logic directly unit-testable with no mocking.
- Modules print progress to stdout; that's fine for tests but means log output
  is the only observability. Structured logging would help future assertions.
