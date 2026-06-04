import time
from extract.shopify_client import run_query

def extract_customers():
    """
    Fetch all customers from Shopify with pagination
    """
    all_customers = []
    has_next_page = True
    cursor = None

    print(f"👥 Fetching customers...")

    while has_next_page:
        after_clause = f', after: "{cursor}"' if cursor else ""

        query = f"""
        {{
            customers(first: 25{after_clause}) {{
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

        # Small delay to avoid rate limiting
        time.sleep(0.5)

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