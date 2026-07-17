from datetime import datetime, timedelta, timezone
from extract.shopify_client import run_query

def extract_customers(days_back=30, since=None):
    """
    Fetch customers from Shopify with pagination.

    days_back:
        - int  -> only fetch customers UPDATED within the last N days
        - None -> no date filter (full backfill)
    """
    all_customers = []
    has_next_page = True
    cursor = None

    if since is not None:
        filter_clause = f', query: "updated_at:>={since}"'
        print(f"👥 Fetching customers updated since {since} (watermark mode)...")
    elif days_back is None:
        filter_clause = ""
        print(f"👥 Fetching customers (full backfill — no date filter)...")
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        filter_clause = f', query: "updated_at:>={cutoff_str}"'
        print(f"👥 Fetching customers updated since {cutoff_str} (last {days_back} days)...")

    while has_next_page:
        after_clause = f', after: "{cursor}"' if cursor else ""

        query = f"""
        {{
            customers(first: 25{after_clause}{filter_clause}) {{
                pageInfo {{
                    hasNextPage
                    endCursor
                }}
                edges {{
                    node {{
                        id
                        firstName
                        lastName
                        email
                        phone
                        createdAt
                        updatedAt
                        numberOfOrders
                        amountSpent {{
                            amount
                            currencyCode
                        }}
                        defaultAddress {{
                            city
                            province
                            country
                        }}
                    }}
                }}
            }}
        }}
        """

        result = run_query(query)
        customers_data = result["data"]["customers"]

        customers = [edge["node"] for edge in customers_data["edges"]]
        all_customers.extend(customers)

        has_next_page = customers_data["pageInfo"]["hasNextPage"]
        cursor = customers_data["pageInfo"]["endCursor"]

        print(f"   Fetched {len(all_customers)} customers so far...")


    print(f"✅ Total customers fetched: {len(all_customers)}")
    return all_customers


if __name__ == "__main__":
    customers = extract_customers()

    if customers:
        first = customers[0]
        print(f"\n📋 Sample customer:")
        print(f"   Name: {first['firstName']} {first['lastName']}")
        print(f"   Email: {first['email']}")
        print(f"   Orders: {first['numberOfOrders']}")
        print(f"   Total spent: {first['amountSpent']['amount']} {first['amountSpent']['currencyCode']}")
        location = first.get('defaultAddress')
        if location:
            print(f"   Location: {location['city']}, {location['province']}, {location['country']}")