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

## What's **not** covered (yet)

- The rest of `extract/` (`extract_customers`, `extract_products`,
  `extract_inventory`, `extract_quickbooks`) and `extract/shopify_client.py`
  (retry/session logic, token auth).
- The `transform/` layer (SKU normalization, dedup, dim/fact shaping).
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
