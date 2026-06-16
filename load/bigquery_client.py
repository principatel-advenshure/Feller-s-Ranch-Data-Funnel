"""
BigQuery client — handles connection, table creation,
staging and MERGE upsert logic for idempotency.
"""

import json
import os
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = "data-funnel-3015"
DATASET_ID = "fellers_ranch"
SCHEMA_DIR = "schema"


def get_client() -> bigquery.Client:
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path and os.path.exists(credentials_path):
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/bigquery"]
        )
        return bigquery.Client(project=PROJECT_ID, credentials=credentials)
    return bigquery.Client(project=PROJECT_ID)


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
    try:
        client.get_table(table_ref)
        print(f"✅ Table already exists: {table_name}")
    except Exception:
        client.create_table(table)
        print(f"✅ Table created: {table_name}")


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
        "dim_stores"
    ]

    print("🔧 Setting up BigQuery tables...")
    for table in tables:
        create_table_if_not_exists(table)
    print("✅ All tables ready!")


if __name__ == "__main__":
    setup_all_tables()