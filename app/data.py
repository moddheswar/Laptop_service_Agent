"""Data models and access helpers."""
# data.py
from datetime import datetime, timedelta, timezone
from .support_db import record_event

def _dt(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")

def seed(conn):
    if conn.execute("SELECT id FROM customers LIMIT 1").fetchone():
        return
    conn.executemany(
        "INSERT INTO customers(email, name) VALUES (?,?)",
        [("ana@example.com", "Ana"), ("bob@example.com", "Bob")],
    )
    ana = conn.execute("SELECT id FROM customers WHERE email='ana@example.com'").fetchone()["id"]
    bob = conn.execute("SELECT id FROM customers WHERE email='bob@example.com'").fetchone()["id"]
    conn.executemany(
        """
        INSERT INTO orders(order_no, customer_id, model, status, price_cents, purchased_at, delivered_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        [
            ("ORD-1001", ana, "NovaBook 14", "delivered", 119900, _dt(12), _dt(10)),  # in window
            ("ORD-3001", ana, "NovaBook 14", "shipped", 119900, _dt(2), None),        # not delivered
            ("ORD-2001", bob, "NovaBook Pro 16", "delivered", 249900, _dt(45), _dt(42)),  # outside window
        ],
    )
    conn.executemany(
        "INSERT INTO kb_articles(issue_key, title, steps_json) VALUES (?,?,?)",
        [
            ("battery", "Battery drains fast",
             '["Run battery health check in NovaCare app", "Limit background apps", "If health <80%, book a service"]'),
            ("wifi", "Wi-Fi keeps disconnecting",
             '["Forget and rejoin the network", "Update Wi-Fi driver via NovaCare", "Reset network settings"]'),
            ("slow", "Laptop is slow",
             '["Check startup apps", "Free disk space to >20%", "Run NovaCare performance scan"]'),
            ("screen", "Screen flickering",
             '["Update graphics driver", "Check refresh rate settings", "Boot into safe mode to isolate"]'),
        ],
    )
    record_event(conn, "system", "seeded", {"customers": 2, "orders": 3, "kb": 4})
    conn.commit()