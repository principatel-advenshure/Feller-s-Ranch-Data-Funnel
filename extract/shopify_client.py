import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from auth.token_manager import get_valid_token

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# Shopify Admin API version. Bump deliberately and test in GraphiQL first.
API_VERSION = "2025-04"

# Network timeouts (seconds): (connect, read)
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 60

# How many times to retry a request that fails on a transient/connection error
MAX_CONNECTION_RETRIES = 5


def _build_session():
    """
    Build a requests Session with connection pooling and automatic retries
    for transient failures (connection drops, SSL EOF, 429s, 5xx).

    urllib3's Retry handles status-code retries and, via the adapter, retries
    on connection-level errors like the SSL UNEXPECTED_EOF we hit during long
    customer pulls.
    """
    session = requests.Session()

    retry = Retry(
        total=MAX_CONNECTION_RETRIES,
        connect=MAX_CONNECTION_RETRIES,
        read=MAX_CONNECTION_RETRIES,
        status=MAX_CONNECTION_RETRIES,
        backoff_factor=1.0,  # 0s, 1s, 2s, 4s, 8s between retries
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["POST", "GET"]),  # POST is not retried by default
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# Module-level session reused across all requests (keeps connections alive,
# which is both faster and more stable than a fresh connection per request).
_SESSION = _build_session()


def run_query(query, variables=None, store: str = "fellers_ranch"):
    """
    Run a GraphQL query against a specific Shopify store, with connection
    pooling, timeouts, and automatic retries on transient failures.
    """
    token, shop_url, _, _ = get_valid_token(store)

    url = f"https://{shop_url}/admin/api/{API_VERSION}/graphql.json"

    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": token,
    }

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    response = _SESSION.post(
        url,
        json=payload,
        headers=headers,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
    )

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