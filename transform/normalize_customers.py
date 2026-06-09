"""
Normalize raw Shopify customer data.
Handles missing names, deduplicates by email,
and prepares for dim_customers in BigQuery.
Adds first_order_date from order history.
"""


def normalize_customers(raw_customers: list, fact_orders: list = None) -> list:
    """
    Normalize raw Shopify customers.

    Args:
        raw_customers: List of raw customers from extract_customers()
        fact_orders: Optional list of normalized orders to derive first_order_date

    Returns:
        List of normalized customer dicts
    """
    normalized = []
    seen_emails = set()

    # Build first_order_date lookup from orders if provided
    first_order_lookup = {}
    if fact_orders:
        for order in fact_orders:
            email = order.get("customer_email")
            if not email:
                continue
            order_date = order.get("created_at")
            if email not in first_order_lookup:
                first_order_lookup[email] = order_date
            else:
                # Keep the earliest date
                if order_date < first_order_lookup[email]:
                    first_order_lookup[email] = order_date

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

        # Get first order date from lookup
        first_order_date = first_order_lookup.get(email)

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
            "first_order_date": first_order_date,
            "created_at": customer.get("createdAt"),
            "updated_at": customer.get("updatedAt"),
            "store": "fellers_ranch"
        }
        normalized.append(normalized_customer)

    return normalized


if __name__ == "__main__":
    from extract.extract_customers import extract_customers
    from extract.extract_orders import extract_orders
    from transform.normalize_orders import normalize_orders

    print("🔄 Normalizing customers...")
    raw_customers = extract_customers()
    raw_orders = extract_orders()
    fact_orders, _ = normalize_orders(raw_orders)
    normalized = normalize_customers(raw_customers, fact_orders)

    with_orders = [c for c in normalized if c["number_of_orders"] > 0]
    with_names = [c for c in normalized if c["full_name"] != "Unknown"]
    with_location = [c for c in normalized if c["country"]]
    with_first_order = [c for c in normalized if c["first_order_date"]]

    print(f"\n✅ Total normalized:      {len(normalized)}")
    print(f"   With orders:          {len(with_orders)}")
    print(f"   With names:           {len(with_names)}")
    print(f"   With location:        {len(with_location)}")
    print(f"   With first_order_date:{len(with_first_order)}")

    if normalized:
        sample = next((c for c in normalized if c["first_order_date"]), normalized[0])
        print(f"\n📋 Sample customer with order:")
        print(f"   Name:             {sample['full_name']}")
        print(f"   Email:            {sample['email']}")
        print(f"   Orders:           {sample['number_of_orders']}")
        print(f"   First order date: {sample['first_order_date']}")