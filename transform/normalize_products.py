"""
Normalize raw Shopify product data into canonical format.
Maps raw product names to canonical SKUs using Airtable mapping.
Flags products with missing SKUs for review.
"""

def normalize_products(raw_products: list, sku_mapping: dict = {}) -> tuple:
    """
    Normalize raw Shopify products.

    Args:
        raw_products: List of raw products from extract_products()
        sku_mapping: Dict of {raw_name: canonical_sku} from Airtable
                     Empty dict until Airtable is connected

    Returns:
        tuple: (normalized_products, unmapped_products)
    """
    normalized = []
    unmapped = []

    for product in raw_products:
        variants = [e["node"] for e in product["variants"]["edges"]]

        for variant in variants:
            raw_name = product["title"]
            raw_sku = variant.get("sku", "")

            # Try to get canonical SKU from Airtable mapping
            canonical_sku = sku_mapping.get(raw_name) or sku_mapping.get(raw_sku)

            # If no mapping found, flag it
            if not canonical_sku:
                if raw_sku:
                    canonical_sku = raw_sku  # use existing SKU if available
                else:
                    canonical_sku = None  # will be flagged as unmapped

            # Get weight safely
            try:
                weight_data = variant["inventoryItem"]["measurement"]["weight"]
                weight_value = weight_data["value"]
                weight_unit = weight_data["unit"]
            except (KeyError, TypeError):
                weight_value = None
                weight_unit = None

            normalized_product = {
                "shopify_product_id": product["id"],
                "shopify_variant_id": variant["id"],
                "raw_name": raw_name,
                "canonical_sku": canonical_sku,
                "variant_title": variant.get("title"),
                "price": float(variant.get("price", 0)),
                "inventory_quantity": variant.get("inventoryQuantity", 0),
                "weight_value": weight_value,
                "weight_unit": weight_unit,
                "product_type": product.get("productType"),
                "vendor": product.get("vendor"),
                "status": product.get("status"),
                "created_at": product.get("createdAt"),
                "updated_at": product.get("updatedAt"),
                "store": "fellers_ranch"
            }

            if canonical_sku is None:
                unmapped.append(normalized_product)
            else:
                normalized.append(normalized_product)

    return normalized, unmapped


if __name__ == "__main__":
    from extract.extract_products import extract_products

    print("🔄 Normalizing products...")
    raw_products = extract_products()

    normalized, unmapped = normalize_products(raw_products)

    print(f"\n✅ Normalized: {len(normalized)} product variants")
    print(f"⚠️  Unmapped:   {len(unmapped)} product variants (no SKU)")

    if normalized:
        sample = normalized[0]
        print(f"\n📋 Sample normalized product:")
        print(f"   Raw name:      {sample['raw_name']}")
        print(f"   Canonical SKU: {sample['canonical_sku']}")
        print(f"   Price:         ${sample['price']}")
        print(f"   Weight:        {sample['weight_value']} {sample['weight_unit']}")
        print(f"   Status:        {sample['status']}")

    if unmapped:
        print(f"\n⚠️  Sample unmapped product:")
        print(f"   Raw name: {unmapped[0]['raw_name']}")
        print(f"   These need SKUs added in Airtable")