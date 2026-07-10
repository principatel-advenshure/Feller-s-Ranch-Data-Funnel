"""
Airtable extractor — pulls MASTER and Shopify <-> Canonical Map tables.
Used as a live reference in the transform layer — loaded first every run.
"""

import os
import requests
import time
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
BASE_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"

HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json"
}


def fetch_table(table_name: str) -> list:
    """
    Fetch all records from an Airtable table with pagination.

    Args:
        table_name: Exact table name as it appears in Airtable

    Returns:
        List of record dicts with id and fields
    """
    all_records = []
    offset = None

    print(f"📋 Fetching Airtable table: {table_name}...")

    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset

        response = requests.get(
            f"{BASE_URL}/{requests.utils.quote(table_name)}",
            headers=HEADERS,
            params=params
        )

        if response.status_code == 429:
            print("⚠️  Rate limited — waiting 30s...")
            time.sleep(30)
            continue

        if response.status_code != 200:
            raise Exception(
                f"❌ Airtable fetch failed for {table_name}: "
                f"{response.status_code} {response.text}"
            )

        data = response.json()
        records = data.get("records", [])
        all_records.extend(records)

        print(f"   Fetched {len(all_records)} records so far...")

        offset = data.get("offset")
        if not offset:
            break

        time.sleep(0.2)

    print(f"✅ Total records fetched from {table_name}: {len(all_records)}")
    return all_records


def extract_master() -> list:
    """Fetch the MASTER product list."""
    return fetch_table("MASTER")


def extract_sku_mapping() -> dict:
    """
    Fetch Shopify <-> Canonical Map and return as a lookup dict.
    Format: {shopify_name: canonical_sku}
    """
    records = fetch_table("Shopify <-> Canonical Map")

    mapping = {}
    for record in records:
        fields = {k.lstrip("﻿"): v for k, v in record.get("fields", {}).items()}
        shopify_name = fields.get("Shopify Name") or fields.get("Shopify Product Name")
        canonical_sku = fields.get("Canonical SKU") or fields.get("SKU")

        if shopify_name and canonical_sku:
            mapping[shopify_name.strip()] = canonical_sku.strip()

    print(f"✅ SKU mapping built: {len(mapping)} entries")
    return mapping


if __name__ == "__main__":
    print("🔄 Testing Airtable connection...\n")

    # Test MASTER table
    master = extract_master()
    if master:
        sample = master[0].get("fields", {})
        print(f"\n📋 Sample MASTER record fields:")
        for key, value in list(sample.items())[:5]:
            print(f"   {key}: {value}")

    print()

    # Test SKU mapping
    mapping = extract_sku_mapping()
    if mapping:
        sample_key = list(mapping.keys())[0]
        print(f"\n📋 Sample SKU mapping:")
        print(f"   {sample_key} → {mapping[sample_key]}")