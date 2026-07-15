from datetime import datetime, timedelta, timezone

from extract.shopify_client import run_query


def extract_orders(days_back=30):
    """
    Fetch orders from Shopify with cursor-based pagination.

    days_back:
        - int  -> only fetch orders UPDATED within the last `days_back` days
                  (incremental / nightly run)
        - None -> no date filter, fetch every accessible order
                  (one-time historical backfill)

    We filter on updated_at (not created_at) so that orders edited after
    creation are still picked up on incremental runs.
    """
    all_orders = []
    has_next_page = True
    cursor = None

    # Build the optional Shopify search filter from days_back
    if days_back is None:
        filter_clause = ""
        print("📦 Fetching orders (full backfill — no date filter)...")
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        # NOTE: the search string is single-quoted inside the GraphQL query
        filter_clause = f', query: "updated_at:>={cutoff_str}"'
        print(f"📦 Fetching orders updated since {cutoff_str} (last {days_back} days)...")

    while has_next_page:
        # Cursor for pagination
        after_clause = f', after: "{cursor}"' if cursor else ""

        query = f"""
        {{
            orders(first: 50, sortKey: UPDATED_AT{after_clause}{filter_clause}) {{
                pageInfo {{
                    hasNextPage
                    endCursor
                }}
                edges {{
                    node {{
                        id
                        name
                        createdAt
                        updatedAt
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

        orders = [edge["node"] for edge in orders_data["edges"]]
        all_orders.extend(orders)

        has_next_page = orders_data["pageInfo"]["hasNextPage"]
        cursor = orders_data["pageInfo"]["endCursor"]

        print(f"   Fetched {len(all_orders)} orders so far...")

    print(f"✅ Total orders fetched: {len(all_orders)}")
    return all_orders


if __name__ == "__main__":
    orders = extract_orders()

    if orders:
        first = orders[0]
        print(f"\n📋 Sample order:")
        print(f"   ID: {first['name']}")
        print(f"   Date: {first['createdAt']}")
        print(f"   Total: {first['totalPriceSet']['shopMoney']['amount']} {first['totalPriceSet']['shopMoney']['currencyCode']}")
        print(f"   Status: {first['displayFinancialStatus']}")
        print(f"   Line items: {len(first['lineItems']['edges'])}")