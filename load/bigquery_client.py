"""
BigQuery client — handles connection, table creation,
staging and MERGE upsert logic for idempotency.
"""

import json
import os
from google.cloud import bigquery
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


PROJECT_ID = os.environ.get("GCP_PROJECT", "data-funnel-3015")
DATASET_ID = "fellers_ranch"
SCHEMA_DIR = "schema"


# Module-level singleton. A BigQuery Client (and its service-account
# credentials) caches its OAuth access token and only refreshes near expiry, so
# reusing ONE client keeps token exchanges to a minimum. Building a fresh client
# per call re-signs a JWT and hits Google's token endpoint every time, which
# under rapid repeated calls (e.g. a batched backfill upserting many chunks)
# gets throttled and surfaces as `invalid_grant: Invalid JWT Signature`.
_CLIENT = None


def get_client() -> bigquery.Client:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path and os.path.exists(credentials_path):
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/bigquery"]
        )
        _CLIENT = bigquery.Client(project=PROJECT_ID, credentials=credentials)
    else:
        _CLIENT = bigquery.Client(project=PROJECT_ID)
    return _CLIENT


def get_table_ref(table_name: str) -> str:
    return f"{PROJECT_ID}.{DATASET_ID}.{table_name}"


def load_schema(table_name: str) -> list:
    # Strip _staging suffix to get base schema file
    base_name = table_name.replace("_staging", "")
    schema_path = os.path.join(SCHEMA_DIR, f"{base_name}.json")
    with open(schema_path, "r") as f:
        schema_json = json.load(f)
    return [
        bigquery.SchemaField(
            name=field["name"],
            field_type=field["type"],
            mode=field.get("mode", "NULLABLE")
        )
        for field in schema_json
    ]


def create_table_if_not_exists(table_name: str):
    client = get_client()
    table_ref = get_table_ref(table_name)
    schema = load_schema(table_name)
    table = bigquery.Table(table_ref, schema=schema)
    # exists_ok=True makes this idempotent: no 409 if the table already exists,
    # and no fragile get_table/except guess.
    client.create_table(table, exists_ok=True)
    print(f"✅ Table ready: {table_name}")


def upsert_rows(table_name: str, rows: list, key_field: str):
    """
    Idempotent upsert using staging table + MERGE pattern.
    Uses load jobs instead of streaming to avoid buffer issues.
    Deduplicates staging before merge to handle multiple variants.

    Steps:
    1. Load rows into staging table (WRITE_TRUNCATE clears it first)
    2. MERGE staging into main table using ROW_NUMBER dedup
    3. Clear staging table
    """
    if not rows:
        print(f"⚠️  No rows to upsert for {table_name}")
        return

    client = get_client()
    staging_table = f"{table_name}_staging"
    staging_ref = get_table_ref(staging_table)
    main_ref = get_table_ref(table_name)

    # Step 1 — Create staging table if not exists
    create_table_if_not_exists(staging_table)

    # Step 2 — Load rows into staging using load job
    # WRITE_TRUNCATE automatically clears staging before loading
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        schema=load_schema(table_name)
    )
    load_job = client.load_table_from_json(
        rows,
        get_table_ref(staging_table),
        job_config=job_config
    )
    load_job.result()
    print(f"📥 Staged {len(rows)} rows into {staging_table}")

    # Step 3 — Build MERGE query with deduplication
    fields = list(rows[0].keys())
    fields_list = ", ".join(fields)
    set_clause = ", ".join([
        f"T.{f} = S.{f}" for f in fields if f != key_field
    ])
    insert_values = ", ".join([f"S.{f}" for f in fields])

    merge_query = f"""
    MERGE `{main_ref}` T
    USING (
        SELECT * EXCEPT(row_num)
        FROM (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY {key_field}
                    ORDER BY {key_field}
                ) as row_num
            FROM `{staging_ref}`
        )
        WHERE row_num = 1
    ) S
    ON T.{key_field} = S.{key_field}
    WHEN MATCHED THEN
        UPDATE SET {set_clause}
    WHEN NOT MATCHED THEN
        INSERT ({fields_list})
        VALUES ({insert_values})
    """

    # Step 4 — Run MERGE
    client.query(merge_query).result()
    print(f"✅ Merged {len(rows)} rows into {table_name}")

    # Step 5 — Clear staging after merge
    client.query(f"DELETE FROM `{staging_ref}` WHERE TRUE").result()
    print(f"🧹 Staging table cleared")


def setup_all_tables():
    """
    Create all main tables if they don't exist.
    Staging tables are created automatically during upsert.
    """
    tables = [
        "fact_orders",
        "fact_order_lines",
        "dim_products",
        "dim_customers",
        "dim_stores",
        "pipeline_summary",
        "fact_b2b_invoices",
        "fact_b2b_invoice_lines",
        "pipeline_control",
    ]

    print("🔧 Setting up BigQuery tables...")
    for table in tables:
        create_table_if_not_exists(table)
    print("✅ All tables ready!")




def read_watermark(key: str = "nightly_watermark"):
    """
    Read the last successful watermark from pipeline_control.
    Returns an ISO-format UTC timestamp string, or None if no watermark exists yet.
    """
    import google.cloud.bigquery as bq_module
    client = get_client()
    table_ref = get_table_ref("pipeline_control")
    query = f"""
        SELECT last_successful_watermark
        FROM `{table_ref}`
        WHERE control_key = @key
        LIMIT 1
    """
    job_config = bq_module.QueryJobConfig(query_parameters=[
        bq_module.ScalarQueryParameter("key", "STRING", key)
    ])
    results = list(client.query(query, job_config=job_config).result())
    if not results or results[0].last_successful_watermark is None:
        return None
    ts = results[0].last_successful_watermark
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def write_watermark(watermark_ts: str, order_count: int, key: str = "nightly_watermark"):
    """
    Upsert the watermark row in pipeline_control after a successful run.
    watermark_ts: ISO-format UTC string (e.g. "2026-07-16T11:14:10Z")
    """
    import google.cloud.bigquery as bq_module
    from datetime import datetime, timezone
    client = get_client()
    table_ref = get_table_ref("pipeline_control")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    merge_query = f"""
    MERGE `{table_ref}` T
    USING (SELECT @key AS control_key) S
    ON T.control_key = S.control_key
    WHEN MATCHED THEN
        UPDATE SET
            last_successful_watermark = TIMESTAMP(@watermark_ts),
            last_run_at = TIMESTAMP(@now),
            last_run_order_count = @order_count
    WHEN NOT MATCHED THEN
        INSERT (control_key, last_successful_watermark, last_run_at, last_run_order_count)
        VALUES (@key, TIMESTAMP(@watermark_ts), TIMESTAMP(@now), @order_count)
    """
    job_config = bq_module.QueryJobConfig(query_parameters=[
        bq_module.ScalarQueryParameter("key", "STRING", key),
        bq_module.ScalarQueryParameter("watermark_ts", "STRING", watermark_ts),
        bq_module.ScalarQueryParameter("now", "STRING", now),
        bq_module.ScalarQueryParameter("order_count", "INT64", order_count),
    ])
    client.query(merge_query, job_config=job_config).result()
    print(f"✅ Watermark saved: {watermark_ts} ({order_count} orders)")

if __name__ == "__main__":
    setup_all_tables()