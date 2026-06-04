"""
Identify and resolve variable weight products.
Shopify workaround creates temporary products with 12h expiry
calculated from unit price and weight.
These need to be caught and processed before they disappear.
"""


def is_variable_weight(product_title: str) -> bool:
    """
    Detect if a product is a temporary variable weight product.
    These are created via barcode scanning workaround.
    """
    if not product_title:
        return False

    # Keywords that indicate a variable weight temp product
    indicators = [
        "per lb",
        "per pound",
        "per kg",
        "/lb",
        "/kg",
        "variable",
        "by weight",
        "custom weight",
        "temp",
    ]

    title_lower = product_title.lower()
    return any(indicator in title_lower for indicator in indicators)


def resolve_variable_weight_orders(fact_order_lines: list) -> tuple:
    """
    Separate variable weight line items from standard ones.

    Args:
        fact_order_lines: Normalized order lines from normalize_orders()

    Returns:
        tuple: (standard_lines, variable_weight_lines)
    """
    standard = []
    variable = []

    for line in fact_order_lines:
        if is_variable_weight(line.get("product_title", "")):
            variable_line = {**line, "is_variable_weight": True}
            variable.append(variable_line)
        else:
            standard_line = {**line, "is_variable_weight": False}
            standard.append(standard_line)

    return standard, variable


if __name__ == "__main__":
    from extract.extract_orders import extract_orders
    from transform.normalize_orders import normalize_orders

    print("🔄 Checking for variable weight products...")
    raw_orders = extract_orders()
    fact_orders, fact_order_lines = normalize_orders(raw_orders)

    standard, variable = resolve_variable_weight_orders(fact_order_lines)

    print(f"\n✅ Standard line items:        {len(standard)}")
    print(f"⚖️  Variable weight line items: {len(variable)}")

    if variable:
        print(f"\n📋 Sample variable weight item:")
        sample = variable[0]
        print(f"   Product: {sample['product_title']}")
        print(f"   Qty:     {sample['quantity']}")
        print(f"   Price:   ${sample['unit_price']}")
    else:
        print("\n✅ No variable weight products found in current orders")
        print("   (They may have already expired or none exist yet)")