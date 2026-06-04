from extract.shopify_client import run_query

def extract_inventory():
    """
    Fetch inventory levels for all locations
    """
    all_inventory = []
    has_next_page = True
    cursor = None

    print(f"📊 Fetching inventory...")

    while has_next_page:
        after_clause = f', after: "{cursor}"' if cursor else ""

        query = f"""
        {{
            inventoryItems(first: 50{after_clause}) {{
                pageInfo {{
                    hasNextPage
                    endCursor
                }}
                edges {{
                    node {{
                        id
                        sku
                        tracked
                        createdAt
                        updatedAt
                        inventoryLevels(first: 5) {{
                            edges {{
                                node {{
                                    id
                                    quantities(names: ["available", "on_hand"]) {{
                                        name
                                        quantity
                                    }}
                                    location {{
                                        id
                                        name
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
        inventory_data = result["data"]["inventoryItems"]

        items = [edge["node"] for edge in inventory_data["edges"]]
        all_inventory.extend(items)

        has_next_page = inventory_data["pageInfo"]["hasNextPage"]
        cursor = inventory_data["pageInfo"]["endCursor"]

        print(f"   Fetched {len(all_inventory)} inventory items so far...")

    print(f"✅ Total inventory items fetched: {len(all_inventory)}")
    return all_inventory


if __name__ == "__main__":
    inventory = extract_inventory()

    if inventory:
        # Find first item with inventory levels
        sample = next((i for i in inventory if i["inventoryLevels"]["edges"]), inventory[0])
        print(f"\n📋 Sample inventory item:")
        print(f"   SKU: {sample['sku']}")
        print(f"   Tracked: {sample['tracked']}")
        levels = sample["inventoryLevels"]["edges"]
        if levels:
            level = levels[0]["node"]
            print(f"   Location: {level['location']['name']}")
            for q in level["quantities"]:
                print(f"   {q['name']}: {q['quantity']}")