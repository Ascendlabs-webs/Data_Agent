"""
Pre-built analytics queries.

- students (default): PDF mini-project — Predictive Analytics for
  Student Academic Performance (attendance, internal /50, assignment /20,
  prev_gpa, practical /50, study_pattern -> final_marks /100).
- grocery: legacy e-commerce demo, kept for backwards compatibility.
"""
from backend.database_tools import execute_query


# (title, chart_type, x_field, y_field, sql)
GROCERY_DEFINITIONS = [
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

# EDA angles from PDF slide 08: attendance<->final, internal as
# predictor, prev-GPA influence, distributions + study-pattern splits.
STUDENT_DEFINITIONS = [
    (
        "Average final marks by attendance band",
        "bar",
        "attendance_band",
        "avg_final",
        "SELECT CASE WHEN attendance >= 90 THEN '90-100' "
        "WHEN attendance >= 80 THEN '80-89' "
        "WHEN attendance >= 70 THEN '70-79' "
        "ELSE '50-69' END AS attendance_band, "
        "ROUND(AVG(final_marks), 1) AS avg_final "
        "FROM students GROUP BY attendance_band ORDER BY attendance_band",
    ),
    (
        "Average final marks by internal-marks band (/50)",
        "bar",
        "internal_band",
        "avg_final",
        "SELECT CASE WHEN internal_marks >= 45 THEN '45-50' "
        "WHEN internal_marks >= 40 THEN '40-44' "
        "WHEN internal_marks >= 35 THEN '35-39' "
        "ELSE '<35' END AS internal_band, "
        "ROUND(AVG(final_marks), 1) AS avg_final "
        "FROM students GROUP BY internal_band ORDER BY internal_band",
    ),
    (
        "Average final marks by study pattern",
        "bar",
        "study_pattern",
        "avg_final",
        "SELECT study_pattern, ROUND(AVG(final_marks), 1) AS avg_final "
        "FROM students GROUP BY study_pattern ORDER BY avg_final DESC",
    ),
    (
        "Average final marks by previous GPA band",
        "line",
        "gpa_band",
        "avg_final",
        "SELECT CASE WHEN prev_gpa >= 9 THEN '9-10' "
        "WHEN prev_gpa >= 8 THEN '8-9' "
        "WHEN prev_gpa >= 7 THEN '7-8' "
        "ELSE '<7' END AS gpa_band, "
        "ROUND(AVG(final_marks), 1) AS avg_final "
        "FROM students GROUP BY gpa_band ORDER BY gpa_band",
    ),
    (
        "Students by performance category (pie)",
        "pie",
        "category",
        "students",
        "SELECT CASE WHEN final_marks >= 85 THEN 'Excellent (85+)' "
        "WHEN final_marks >= 70 THEN 'Good (70-84)' "
        "WHEN final_marks >= 55 THEN 'Average (55-69)' "
        "ELSE 'At-risk (<55)' END AS category, "
        "COUNT(*) AS students FROM students GROUP BY category",
    ),
    (
        "Average final marks by practical-marks band (/50)",
        "line",
        "practical_band",
        "avg_final",
        "SELECT CASE WHEN practical_marks >= 45 THEN '45-50' "
        "WHEN practical_marks >= 40 THEN '40-44' "
        "WHEN practical_marks >= 35 THEN '35-39' "
        "ELSE '<35' END AS practical_band, "
        "ROUND(AVG(final_marks), 1) AS avg_final "
        "FROM students GROUP BY practical_band ORDER BY practical_band",
    ),
]


def get_analytics(db="students"):
    """Run predefined analytics queries and return chart specs."""
    definitions = STUDENT_DEFINITIONS if db == "students" else GROCERY_DEFINITIONS
    charts = []
    for title, chart_type, x_field, y_field, sql in definitions:
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


def get_stats(db="students"):
    """Return summary stats for the analytics dashboard header."""
    if db == "students":
        result = execute_query(
            "SELECT "
            "  COUNT(*) AS total_students, "
            "  ROUND(AVG(final_marks), 1) AS avg_final, "
            "  ROUND(AVG(attendance), 1) AS avg_attendance, "
            "  ROUND(AVG(prev_gpa), 2) AS avg_gpa "
            "FROM students",
            db,
        )
        if result.get("success") and result.get("data"):
            return result["data"][0]
        return {
            "total_students": 0,
            "avg_final": 0,
            "avg_attendance": 0,
            "avg_gpa": 0,
        }
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
