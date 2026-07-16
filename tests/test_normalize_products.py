"""
Tests for transform/normalize_products.py — raw Shopify products → normalized
variants, split into (normalized, unmapped).

Pure function, no I/O. Covers the SKU-mapping fallback ladder:
  1. canonical SKU from Airtable mapping (by raw name, then by raw sku)
  2. else the variant's own sku if present
  3. else None → flagged as unmapped
"""

from transform.normalize_products import normalize_products


def _variant(
    vid="gid://shopify/ProductVariant/1",
    sku="RIB-1",
    title="Default",
    price="45.00",
    inventory=10,
    weight={"value": 1.2, "unit": "POUNDS"},
):
    inventory_item = {}
    if weight is not None:
        inventory_item = {"measurement": {"weight": weight}}
    return {
        "node": {
            "id": vid,
            "sku": sku,
            "title": title,
            "price": price,
            "inventoryQuantity": inventory,
            "inventoryItem": inventory_item,
        }
    }


def _raw_product(
    pid="gid://shopify/Product/1",
    title="Ribeye Steak",
    variants=None,
    product_type="Meat",
    vendor="Feller's Ranch",
    status="ACTIVE",
):
    if variants is None:
        variants = [_variant()]
    return {
        "id": pid,
        "title": title,
        "productType": product_type,
        "vendor": vendor,
        "status": status,
        "createdAt": "2025-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "variants": {"edges": variants},
    }


# --------------------------------------------------------------------------- #
# SKU mapping fallback ladder
# --------------------------------------------------------------------------- #

def test_empty_mapping_falls_back_to_variant_sku():
    normalized, unmapped = normalize_products([_raw_product()], sku_mapping={})

    assert len(normalized) == 1
    assert unmapped == []
    # falls back to the variant's own sku
    assert normalized[0]["canonical_sku"] == "RIB-1"


def test_matching_mapping_by_name_uses_canonical_sku():
    normalized, _ = normalize_products(
        [_raw_product(title="Ribeye Steak")],
        sku_mapping={"Ribeye Steak": "CANON-RIB"},
    )
    assert normalized[0]["canonical_sku"] == "CANON-RIB"


def test_matching_mapping_by_sku_uses_canonical_sku():
    normalized, _ = normalize_products(
        [_raw_product(variants=[_variant(sku="RAW-99")])],
        sku_mapping={"RAW-99": "CANON-99"},
    )
    assert normalized[0]["canonical_sku"] == "CANON-99"


def test_unmapped_product_with_no_sku_is_flagged():
    normalized, unmapped = normalize_products(
        [_raw_product(variants=[_variant(sku="")])],
        sku_mapping={},
    )
    assert normalized == []
    assert len(unmapped) == 1
    assert unmapped[0]["canonical_sku"] is None


def test_normalized_and_unmapped_split_correctly():
    products = [
        _raw_product(pid="gid://shopify/Product/1", variants=[_variant(sku="HAS-SKU")]),
        _raw_product(pid="gid://shopify/Product/2", variants=[_variant(sku="")]),
    ]
    normalized, unmapped = normalize_products(products, sku_mapping={})

    assert len(normalized) == 1
    assert len(unmapped) == 1
    assert normalized[0]["canonical_sku"] == "HAS-SKU"
    assert unmapped[0]["canonical_sku"] is None


# --------------------------------------------------------------------------- #
# Shape / types / weight handling
# --------------------------------------------------------------------------- #

def test_normalized_product_shape_and_types():
    normalized, _ = normalize_products([_raw_product()], sku_mapping={})
    p = normalized[0]

    for key in (
        "shopify_product_id", "shopify_variant_id", "raw_name", "canonical_sku",
        "variant_title", "price", "inventory_quantity", "weight_value",
        "weight_unit", "product_type", "vendor", "status", "created_at",
        "updated_at", "store",
    ):
        assert key in p

    assert p["shopify_product_id"] == "gid://shopify/Product/1"
    assert p["raw_name"] == "Ribeye Steak"
    assert p["price"] == 45.0
    assert isinstance(p["price"], float)
    assert p["inventory_quantity"] == 10
    assert p["weight_value"] == 1.2
    assert p["weight_unit"] == "POUNDS"
    assert p["store"] == "fellers_ranch"


def test_missing_weight_data_handled_gracefully():
    normalized, _ = normalize_products(
        [_raw_product(variants=[_variant(weight=None)])],
        sku_mapping={},
    )
    p = normalized[0]
    assert p["weight_value"] is None
    assert p["weight_unit"] is None


def test_multiple_variants_produce_multiple_rows():
    product = _raw_product(variants=[
        _variant(vid="gid://shopify/ProductVariant/1", sku="A"),
        _variant(vid="gid://shopify/ProductVariant/2", sku="B"),
    ])
    normalized, _ = normalize_products([product], sku_mapping={})
    assert len(normalized) == 2


# --------------------------------------------------------------------------- #
# Empty input
# --------------------------------------------------------------------------- #

def test_empty_products_returns_two_empty_lists():
    assert normalize_products([]) == ([], [])


def test_empty_products_with_default_mapping_arg():
    # sku_mapping defaults to {} — call with no mapping at all.
    assert normalize_products([]) == ([], [])
