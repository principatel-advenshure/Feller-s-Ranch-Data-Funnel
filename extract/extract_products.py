from extract.shopify_client import run_query

def extract_products():
    """
    Fetch all products and variants from Shopify with pagination
    """
    all_products = []
    has_next_page = True
    cursor = None

    print(f"🥩 Fetching products...")

    while has_next_page:
        after_clause = f', after: "{cursor}"' if cursor else ""

        query = f"""
        {{
            products(first: 50{after_clause}) {{
                pageInfo {{
                    hasNextPage
                    endCursor
                }}
                edges {{
                    node {{
                        id
                        title
                        handle
                        status
                        productType
                        vendor
                        createdAt
                        updatedAt
                        variants(first: 20) {{
                            edges {{
                                node {{
                                    id
                                    sku
                                    title
                                    price
                                    inventoryQuantity
                                    inventoryItem {{
                                        measurement {{
                                            weight {{
                                                value
                                                unit
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = run_query(query)
        products_data = result["data"]["products"]

        products = [edge["node"] for edge in products_data["edges"]]
        all_products.extend(products)

        has_next_page = products_data["pageInfo"]["hasNextPage"]
        cursor = products_data["pageInfo"]["endCursor"]

        print(f"   Fetched {len(all_products)} products so far...")

    print(f"✅ Total products fetched: {len(all_products)}")
    return all_products


if __name__ == "__main__":
    products = extract_products()

    # Print first product as sample
    if products:
        first = products[0]
        variants = [e["node"] for e in first["variants"]["edges"]]
        print(f"\n📋 Sample product:")
        print(f"   Name: {first['title']}")
        print(f"   Type: {first['productType']}")
        print(f"   Status: {first['status']}")
        print(f"   Variants: {len(variants)}")
        if variants:
            weight = variants[0]['inventoryItem']['measurement']['weight']
            print(f"   First variant SKU: {variants[0]['sku']}")
            print(f"   Price: ${variants[0]['price']}")
            print(f"   Weight: {weight['value']} {weight['unit']}")