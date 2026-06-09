from extract.shopify_client import run_query

def extract_orders(days_back=30):
    """
    Fetch all orders from Shopify with cursor-based pagination
    """
    all_orders = []
    has_next_page = True
    cursor = None

    print(f"📦 Fetching orders...")

    while has_next_page:
        # Build query with optional cursor for pagination
        after_clause = f', after: "{cursor}"' if cursor else ""

        query = f"""
        {{
            orders(first: 50, sortKey: CREATED_AT{after_clause}) {{
                pageInfo {{
                    hasNextPage
                    endCursor
                }}
                edges {{
                    node {{
                        id
                        name
                        createdAt
                        displayFinancialStatus
                        displayFulfillmentStatus
                        totalPriceSet {{
                            shopMoney {{
                                amount
                                currencyCode
                            }}
                        }}
                        subtotalPriceSet {{
                            shopMoney {{
                                amount
                            }}
                        }}
                        totalDiscountsSet {{
                            shopMoney {{
                                amount
                            }}
                        }}
                        totalRefundedSet {{
                            shopMoney {{
                                amount
                            }}
                        }}
                        customer {{
                            id
                            firstName
                            lastName
                            email
                        }}
                        lineItems(first: 20) {{
                            edges {{
                                node {{
                                    id
                                    title
                                    quantity
                                    variant {{
                                        id
                                        sku
                                        price
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
        orders_data = result["data"]["orders"]

        # Extract orders from edges
        orders = [edge["node"] for edge in orders_data["edges"]]
        all_orders.extend(orders)

        # Pagination — check if more pages exist
        has_next_page = orders_data["pageInfo"]["hasNextPage"]
        cursor = orders_data["pageInfo"]["endCursor"]

        print(f"   Fetched {len(all_orders)} orders so far...")

    print(f"✅ Total orders fetched: {len(all_orders)}")
    return all_orders


if __name__ == "__main__":
    orders = extract_orders()
    
    # Print first order as sample
    if orders:
        first = orders[0]
        print(f"\n📋 Sample order:")
        print(f"   ID: {first['name']}")
        print(f"   Date: {first['createdAt']}")
        print(f"   Total: {first['totalPriceSet']['shopMoney']['amount']} {first['totalPriceSet']['shopMoney']['currencyCode']}")
        print(f"   Status: {first['displayFinancialStatus']}")
        print(f"   Line items: {len(first['lineItems']['edges'])}")