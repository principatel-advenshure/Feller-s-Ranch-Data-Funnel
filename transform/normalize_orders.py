"""
Normalize raw Shopify order data into a clean flat structure
ready for loading into BigQuery fact_orders and fact_order_lines.
Filters out $0 orders (draft orders / shipping label requests).
"""


def normalize_orders(raw_orders: list) -> tuple:
    """
    Normalize raw Shopify orders into fact_orders and fact_order_lines.
    Filters out $0 orders as confirmed by Mason — these are draft orders
    or shipping label requests, not real sales.

    Args:
        raw_orders: List of raw orders from extract_orders()

    Returns:
        tuple: (fact_orders, fact_order_lines)
    """
    fact_orders = []
    fact_order_lines = []

    # Filter out $0 orders before processing
    zero_orders = [
        o for o in raw_orders
        if float(o["totalPriceSet"]["shopMoney"]["amount"]) == 0
    ]
    if zero_orders:
        print(f"⚠️  Filtered out {len(zero_orders)} $0 orders "
              f"(draft orders / shipping labels — not real sales)")

    valid_orders = [
        o for o in raw_orders
        if float(o["totalPriceSet"]["shopMoney"]["amount"]) > 0
    ]

    for order in valid_orders:
        # Clean customer data safely
        customer = order.get("customer")
        customer_id = customer.get("id") if customer else None
        customer_email = customer.get("email") if customer else None

        # Clean order
        fact_order = {
            "order_id": order["id"],
            "order_name": order["name"],
            "created_at": order["createdAt"],
            "financial_status": order.get("displayFinancialStatus"),
            "fulfillment_status": order.get("displayFulfillmentStatus"),
            "total_revenue": float(order["totalPriceSet"]["shopMoney"]["amount"]),
            "subtotal": float(order["subtotalPriceSet"]["shopMoney"]["amount"]),
            "currency": order["totalPriceSet"]["shopMoney"]["currencyCode"],
            "customer_id": customer_id,
            "customer_email": customer_email,
            "store": "fellers_ranch",
            "channel": "online",
            "discount_amount": float(order.get("totalDiscountsSet", {}).get("shopMoney", {}).get("amount", 0)),
            "refund_amount": float(order.get("totalRefundedSet", {}).get("shopMoney", {}).get("amount", 0))
        }
        fact_orders.append(fact_order)

        # Clean line items
        line_items = [e["node"] for e in order["lineItems"]["edges"]]
        for item in line_items:
            variant = item.get("variant")
            variant_id = variant.get("id") if variant else None
            sku = variant.get("sku") if variant else None
            price = float(variant.get("price", 0)) if variant else 0.0

            fact_line = {
                "order_id": order["id"],
                "line_item_id": item["id"],
                "product_title": item["title"],
                "variant_id": variant_id,
                "sku": sku,
                "quantity": item["quantity"],
                "unit_price": price,
                "line_revenue": round(item["quantity"] * price, 2),
                "store": "fellers_ranch"
            }
            fact_order_lines.append(fact_line)

    return fact_orders, fact_order_lines


if __name__ == "__main__":
    from extract.extract_orders import extract_orders

    print("🔄 Normalizing orders...")
    raw_orders = extract_orders()

    fact_orders, fact_order_lines = normalize_orders(raw_orders)

    print(f"\n✅ fact_orders:      {len(fact_orders)} rows")
    print(f"✅ fact_order_lines: {len(fact_order_lines)} rows")

    if fact_orders:
        sample = fact_orders[0]
        print(f"\n📋 Sample order:")
        print(f"   Order ID:    {sample['order_name']}")
        print(f"   Date:        {sample['created_at']}")
        print(f"   Revenue:     ${sample['total_revenue']} {sample['currency']}")
        print(f"   Status:      {sample['financial_status']}")
        print(f"   Customer:    {sample['customer_email']}")

    if fact_order_lines:
        sample_line = fact_order_lines[0]
        print(f"\n📋 Sample order line:")
        print(f"   Product:     {sample_line['product_title']}")
        print(f"   SKU:         {sample_line['sku']}")
        print(f"   Quantity:    {sample_line['quantity']}")
        print(f"   Unit price:  ${sample_line['unit_price']}")
        print(f"   Line total:  ${sample_line['line_revenue']}")