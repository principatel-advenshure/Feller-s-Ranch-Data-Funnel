"""
Load dimension tables into BigQuery.
Handles dim_products, dim_customers, dim_stores.
"""

from load.bigquery_client import upsert_rows


def load_dim_products(normalized_products: list, unmapped_products: list):
    """Load all products into dim_products table."""
    all_products = normalized_products + unmapped_products
    print(f"📤 Loading {len(all_products)} products into BigQuery...")
    upsert_rows("dim_products", all_products, key_field="shopify_product_id")


def load_dim_customers(normalized_customers: list):
    """Load normalized customers into dim_customers table."""
    print(f"📤 Loading {len(normalized_customers)} customers into BigQuery...")
    upsert_rows("dim_customers", normalized_customers, key_field="customer_id")


def load_dim_stores():
    """Load store reference data into dim_stores table."""
    stores = [
        {
            "store_id": "fellers_ranch_online",
            "store_name": "Fellers Ranch Online",
            "entity": "Fellers Ranch",
            "channel": "online",
            "shopify_instance": "fellers-ranch.myshopify.com"
        },
        {
            "store_id": "conger_pos_1",
            "store_name": "Conger Meats POS 1",
            "entity": "Conger Meats",
            "channel": "pos",
            "shopify_instance": "TBD"
        },
        {
            "store_id": "conger_pos_2",
            "store_name": "Conger Meats POS 2",
            "entity": "Conger Meats",
            "channel": "pos",
            "shopify_instance": "TBD"
        },
        {
            "store_id": "conger_online",
            "store_name": "Conger Meats Online",
            "entity": "Conger Meats",
            "channel": "online",
            "shopify_instance": "TBD"
        }
    ]
    print(f"📤 Loading {len(stores)} stores into BigQuery...")
    upsert_rows("dim_stores", stores, key_field="store_id")


if __name__ == "__main__":
    from extract.extract_products import extract_products
    from extract.extract_customers import extract_customers
    from transform.normalize_products import normalize_products
    from transform.normalize_customers import normalize_customers

    print("🔄 Running dimension load...\n")

    # Products
    raw_products = extract_products()
    normalized_products, unmapped_products = normalize_products(raw_products)
    load_dim_products(normalized_products, unmapped_products)

    # Customers
    raw_customers = extract_customers()
    normalized_customers = normalize_customers(raw_customers)
    load_dim_customers(normalized_customers)

    # Stores
    load_dim_stores()

    print("\n✅ Dimension tables loaded successfully!")