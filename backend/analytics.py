"""
Pre-built analytics queries for the grocery database.

Returns a list of chart specifications the frontend renders
instantly on the Analytics Dashboard — no LLM calls needed.
"""
from backend.database_tools import execute_query


# (title, chart_type, x_field, y_field, sql)
DEFINITIONS = [
    (
        "Monthly revenue trend",
        "line",
        "month",
        "revenue",
        "SELECT strftime('%Y-%m', o.order_date) AS month, "
        "ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue "
        "FROM order_items oi "
        "JOIN orders o ON o.order_id = oi.order_id "
        "GROUP BY month ORDER BY month",
    ),
    (
        "Revenue by category",
        "bar",
        "category",
        "revenue",
        "SELECT p.category, "
        "ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue "
        "FROM order_items oi "
        "JOIN products p ON p.product_id = oi.product_id "
        "GROUP BY p.category ORDER BY revenue DESC",
    ),
    (
        "Sales quantity by category",
        "bar",
        "category",
        "quantity",
        "SELECT p.category, SUM(oi.quantity) AS quantity "
        "FROM order_items oi "
        "JOIN products p ON p.product_id = oi.product_id "
        "GROUP BY p.category ORDER BY quantity DESC",
    ),
    (
        "Top 10 products by revenue",
        "bar",
        "product",
        "revenue",
        "SELECT p.product_name AS product, "
        "ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue "
        "FROM order_items oi "
        "JOIN products p ON p.product_id = oi.product_id "
        "GROUP BY p.product_name ORDER BY revenue DESC LIMIT 10",
    ),
    (
        "Revenue by product category (pie)",
        "pie",
        "category",
        "revenue",
        "SELECT p.category, "
        "ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue "
        "FROM order_items oi "
        "JOIN products p ON p.product_id = oi.product_id "
        "GROUP BY p.category ORDER BY revenue DESC",
    ),
    (
        "Daily sales trend",
        "line",
        "date",
        "revenue",
        "SELECT o.order_date AS date, "
        "ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue "
        "FROM order_items oi "
        "JOIN orders o ON o.order_id = oi.order_id "
        "GROUP BY o.order_date ORDER BY o.order_date",
    ),
]


def get_analytics(db="grocery"):
    """
    Run all predefined analytics queries and return chart specs.

    Returns:
        Dictionary with a 'charts' list, each containing:
        title, type, x_field, y_field, data (list of row dicts).
    """
    charts = []
    for title, chart_type, x_field, y_field, sql in DEFINITIONS:
        result = execute_query(sql, db)
        if result.get("success"):
            charts.append({
                "title": title,
                "type": chart_type,
                "x_field": x_field,
                "y_field": y_field,
                "data": result.get("data", []),
            })
    return {"charts": charts}


def get_stats(db="grocery"):
    """
    Return summary stats for the analytics dashboard header.
    """
    result = execute_query(
        "SELECT "
        "  (SELECT COUNT(*) FROM products) AS total_products, "
        "  (SELECT COUNT(*) FROM orders) AS total_orders, "
        "  (SELECT COUNT(*) FROM customers) AS total_customers, "
        "  (ROUND(SUM(oi.quantity * oi.unit_price), 2)) AS total_revenue "
        "FROM order_items oi",
        db,
    )
    if result.get("success") and result.get("data"):
        return result["data"][0]
    return {
        "total_products": 0,
        "total_orders": 0,
        "total_customers": 0,
        "total_revenue": 0,
    }
