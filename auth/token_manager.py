"""
Token manager for Shopify stores.
Loads access tokens and credentials from .env using store prefixes.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Store prefix mapping — add new stores here
STORE_PREFIXES = {
    "fellers_ranch": "FLRS",
    "conger_pos_1":  "CGAL1",
    "conger_pos_2":  "CGAL2",
    "conger_online": "CGAL3",
}

def get_valid_token(store: str = "fellers_ranch"):
    """
    Load access token and credentials for a given store.

    Args:
        store: Store key from STORE_PREFIXES
               e.g. "fellers_ranch", "conger_pos_1"

    Returns:
        tuple: (access_token, shop_url, client_id, client_secret)
    """
    prefix = STORE_PREFIXES.get(store)
    if not prefix:
        raise Exception(f"❌ Unknown store: {store}. Add it to STORE_PREFIXES.")

    token         = os.getenv(f"{prefix}_TOKEN")
    shop_url      = os.getenv(f"{prefix}_URL")
    client_id     = os.getenv(f"{prefix}_SHOPIFY_CLIENT_ID")
    client_secret = os.getenv(f"{prefix}_SHOPIFY_CLIENT_SECRET")

    if not token:
        raise Exception(f"❌ No token found for {store}. Add {prefix}_TOKEN to .env")
    if not shop_url:
        raise Exception(f"❌ No URL found for {store}. Add {prefix}_URL to .env")
    if not client_id:
        raise Exception(f"❌ No client ID found for {store}. Add {prefix}_SHOPIFY_CLIENT_ID to .env")
    if not client_secret:
        raise Exception(f"❌ No client secret found for {store}. Add {prefix}_SHOPIFY_CLIENT_SECRET to .env")

    print(f"✅ Credentials loaded for {store}")
    return token, shop_url, client_id, client_secret

def refresh_token_if_needed(store: str = "fellers_ranch"):
    """
    Validate token is still working by making a lightweight test query.
    Fails fast with a clear error if token is expired or revoked.
    """
    import requests

    token, shop_url, client_id, client_secret = get_valid_token(store)

    try:
        response = requests.post(
            f"https://{shop_url}/admin/api/2024-01/graphql.json",
            json={"query": "{ shop { name } }"},
            headers={"X-Shopify-Access-Token": token},
            timeout=10
        )
        if response.status_code == 401:
            raise Exception(
                f"Token for {store} is expired or revoked. "
                f"Regenerate it and update {store.upper()}_TOKEN in .env"
            )
        if response.status_code != 200:
            raise Exception(
                f"Unexpected response validating token for {store}: "
                f"{response.status_code}"
            )
        print(f"✅ Token valid for {store}")

    except requests.exceptions.Timeout:
        raise Exception(f"❌ Token validation timed out for {store}")
    except requests.exceptions.ConnectionError:
        raise Exception(f"❌ Cannot reach Shopify for {store} — check network")

if __name__ == "__main__":
    token, shop_url, client_id, client_secret = get_valid_token("fellers_ranch")
    print(f"Token preview:  {token[:10]}...")
    print(f"Shop URL:       {shop_url}")
    print(f"Client ID:      {client_id[:6]}...")