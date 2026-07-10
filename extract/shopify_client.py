import requests
from auth.token_manager import get_valid_token
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


API_VERSION = "2024-01"

def run_query(query, variables=None, store: str = "fellers_ranch"):
    """
    Run a GraphQL query against a specific Shopify store
    """
    token, shop_url, _, _ = get_valid_token(store)

    url = f"https://{shop_url}/admin/api/{API_VERSION}/graphql.json"

    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": token
    }

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    response = requests.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        raise Exception(f"❌ Query failed: {response.status_code} {response.text}")

    data = response.json()

    if "errors" in data:
        raise Exception(f"❌ GraphQL error: {data['errors']}")

    return data


if __name__ == "__main__":
    test_query = """
    {
        shop {
            name
            email
            currencyCode
        }
    }
    """

    result = run_query(test_query, store="fellers_ranch")
    shop = result["data"]["shop"]
    print(f"✅ Connected to: {shop['name']}")
    print(f"   Email: {shop['email']}")
    print(f"   Currency: {shop['currencyCode']}")