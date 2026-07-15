"""
Airtable extractor — pulls MASTER and Shopify <-> Canonical Map tables.
Used as a live reference in the transform layer — loaded first every run.

Airtable is OPTIONAL. If credentials are missing or set to a placeholder
(e.g. Fellers, which has no canonical SKU map), the extractor short-circuits
and returns empty results. Downstream normalize_products() already handles an
empty mapping by falling back to product names / existing SKUs.
"""

import os
import requests
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_credentials():
    """Read Airtable creds at call time (not import time)."""
    api_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    return api_key, base_id


def _airtable_configured() -> bool:
    """
    True only if both creds are present and not placeholders.
    Lets the pipeline run without Airtable (e.g. Shopify-only for Fellers).
    """
    api_key, base_id = _get_credentials()
    if not api_key or not base_id:
        return False
    if api_key.strip().lower() in ("placeholder", "") or base_id.strip().lower() in ("placeholder", ""):
        return False
    return True


def fetch_table(table_name: str) -> list:
    """
    Fetch all records from an Airtable table with pagination.
    Returns [] if Airtable is not configured.
    """
    if not _airtable_configured():
        print(f"ℹ️  Airtable not configured — skipping table: {table_name}")
        return []

    api_key, base_id = _get_credentials()
    base_url = f"https://api.airtable.com/v0/{base_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    all_records = []
    offset = None

    print(f"📋 Fetching Airtable table: {table_name}...")

    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset

        response = requests.get(
            f"{base_url}/{requests.utils.quote(table_name)}",
            headers=headers,
            params=params,
            timeout=(10, 60),
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
    """Fetch the MASTER product list. Returns [] if Airtable not configured."""
    return fetch_table("MASTER")


def extract_sku_mapping() -> dict:
    """
    Fetch Shopify <-> Canonical Map and return as a lookup dict.
    Format: {shopify_name: canonical_sku}

    Returns an empty dict if Airtable is not configured — downstream
    normalize_products() handles this by falling back to product names.
    """
    if not _airtable_configured():
        print("ℹ️  Airtable not configured — using empty SKU mapping (product names as fallback)")
        return {}

    records = fetch_table("Shopify <-> Canonical Map")

    mapping = {}
    for record in records:
        fields = {k.lstrip(""): v for k, v in record.get("fields", {}).items()}
        shopify_name = fields.get("Shopify Name") or fields.get("Shopify Product Name")
        canonical_sku = fields.get("Canonical SKU") or fields.get("SKU")

        if shopify_name and canonical_sku:
            mapping[shopify_name.strip()] = canonical_sku.strip()

    print(f"✅ SKU mapping built: {len(mapping)} entries")
    return mapping


if __name__ == "__main__":
    print("🔄 Testing Airtable connection...\n")

    master = extract_master()
    if master:
        sample = master[0].get("fields", {})
        print(f"\n📋 Sample MASTER record fields:")
        for key, value in list(sample.items())[:5]:
            print(f"   {key}: {value}")

    print()

    mapping = extract_sku_mapping()
    if mapping:
        sample_key = list(mapping.keys())[0]
        print(f"\n📋 Sample SKU mapping:")
        print(f"   {sample_key} → {mapping[sample_key]}")