"""
Normalize raw Shopify customer data.
Handles missing names, deduplicates by email,
and prepares for dim_customers in BigQuery.
"""


def normalize_customers(raw_customers: list) -> list:
    """
    Normalize raw Shopify customers.

    Args:
        raw_customers: List of raw customers from extract_customers()

    Returns:
        List of normalized customer dicts
    """
    normalized = []
    seen_emails = set()

    for customer in raw_customers:
        email = (customer.get("email") or "").strip().lower()

        # Skip if no email
        if not email:
            continue

        # Deduplicate by email
        if email in seen_emails:
            continue
        seen_emails.add(email)

        # Handle missing names
        first_name = customer.get("firstName") or ""
        last_name = customer.get("lastName") or ""
        full_name = f"{first_name} {last_name}".strip() or "Unknown"

        # Handle missing address
        address = customer.get("defaultAddress")
        city = address.get("city") if address else None
        province = address.get("province") if address else None
        country = address.get("country") if address else None

        normalized_customer = {
            "customer_id": customer["id"],
            "email": email,
            "full_name": full_name,
            "first_name": first_name or None,
            "last_name": last_name or None,
            "phone": customer.get("phone"),
            "city": city,
            "province": province,
            "country": country,
            "number_of_orders": int(customer.get("numberOfOrders", 0)),
            "total_spent": float(customer["amountSpent"]["amount"]),
            "currency": customer["amountSpent"]["currencyCode"],
            "created_at": customer.get("createdAt"),
            "updated_at": customer.get("updatedAt"),
            "store": "fellers_ranch"
        }
        normalized.append(normalized_customer)

    return normalized


if __name__ == "__main__":
    from extract.extract_customers import extract_customers

    print("🔄 Normalizing customers...")
    raw_customers = extract_customers()

    normalized = normalize_customers(raw_customers)

    # Stats
    with_orders = [c for c in normalized if c["number_of_orders"] > 0]
    with_names = [c for c in normalized if c["full_name"] != "Unknown"]
    with_location = [c for c in normalized if c["country"]]

    print(f"\n✅ Total normalized:    {len(normalized)}")
    print(f"   With orders:        {len(with_orders)}")
    print(f"   With names:         {len(with_names)}")
    print(f"   With location:      {len(with_location)}")

    if normalized:
        sample = normalized[0]
        print(f"\n📋 Sample customer:")
        print(f"   Name:     {sample['full_name']}")
        print(f"   Email:    {sample['email']}")
        print(f"   Orders:   {sample['number_of_orders']}")
        print(f"   Spent:    ${sample['total_spent']} {sample['currency']}")
        print(f"   Location: {sample['city']}, {sample['province']}, {sample['country']}")