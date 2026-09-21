"""Support database access layer."""
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
ORDER_RE = re.compile(r"ORD-\d+", re.I)

def connect(path=None):
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db(conn):
    conn.executescript((SCHEMA_DIR / "agent.sql").read_text())
    conn.executescript((SCHEMA_DIR / "append_only.sql").read_text())
    conn.commit()

def record_event(conn, aggregate, event_type, payload):
    conn.execute(
        "INSERT INTO events(aggregate, event_type, payload_json) VALUES (?,?,?)",
        (aggregate, event_type, json.dumps(payload)),
    )

# ---- conversations ----
def create_conversation(conn, customer_id, variant):
    cur = conn.execute(
        "INSERT INTO conversations(customer_id, variant) VALUES (?,?)", (customer_id, variant)
    )
    conn.commit()
    return cur.lastrowid

def conversation_variant(conn, conversation_id):
    return conn.execute(
        "SELECT variant FROM conversations WHERE id=?", (conversation_id,)
    ).fetchone()["variant"]

def add_message(conn, conversation_id, role, content="", tool_call_id=None,
                tool_name=None, tool_calls_json=None):
    conn.execute(
        """
        INSERT INTO messages(conversation_id, role, content, tool_call_id, tool_name, tool_calls_json)
        VALUES (?,?,?,?,?,?)
        """,
        (conversation_id, role, content, tool_call_id, tool_name, tool_calls_json),
    )
    conn.commit()

def history_for_llm(conn, conversation_id, limit=40):
    """
    Provider-agnostic history from the DB.
    Items: {role, content}
    assistant items may add: tool_calls=[{id,name,args}]
    tool items add: tool_call_id, tool_name
    """
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    out = []
    for r in reversed(rows):
        item = {"role": r["role"], "content": r["content"]}
        if r["tool_calls_json"]:
            tcs = json.loads(r["tool_calls_json"])
            item["tool_calls"] = [
                {"id": t["id"], "name": t["function"]["name"],
                 "args": json.loads(t["function"]["arguments"] or "{}"),
                 **({"thought_signature": t["thought_signature"]}
                    if t.get("thought_signature") else {})}
                for t in tcs
            ]
        if r["role"] == "tool":
            item["tool_call_id"] = r["tool_call_id"]
            item["tool_name"] = r["tool_name"]
        out.append(item)
    return out

def recent_messages(conn, conversation_id, limit=20):
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]

# ---- customers / orders ----
def get_customer_by_email(conn, email):
    return conn.execute("SELECT * FROM customers WHERE email=?", (email,)).fetchone()

def get_order_for_customer(conn, order_no, customer_id):
    return conn.execute(
        "SELECT * FROM orders WHERE upper(order_no)=upper(?) AND customer_id=?",
        (order_no, customer_id),
    ).fetchone()

def extract_order_no(text):
    m = ORDER_RE.search(text or "")
    return m.group(0).upper() if m else None

# ---- KB / tickets ----
def kb_search(conn, issue_text):
    rows = conn.execute("SELECT * FROM kb_articles").fetchall()
    text = (issue_text or "").lower()
    for r in rows:
        if r["issue_key"] in text:
            return {"issue": r["issue_key"], "title": r["title"], "steps": json.loads(r["steps_json"])}
    return {"issue": None, "title": None, "steps": []}

def create_ticket(conn, customer_id, kind, subject, description="", severity="low"):
    cur = conn.execute(
        """
        INSERT INTO tickets(customer_id, kind, subject, description, severity)
        VALUES (?,?,?,?,?)
        """,
        (customer_id, kind, subject, description, severity),
    )
    ticket_id = cur.lastrowid
    ticket_no = f"TCK-{1000 + ticket_id}"
    conn.execute("UPDATE tickets SET ticket_no=? WHERE id=?", (ticket_no, ticket_id))
    customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    record_event(conn, f"ticket:{ticket_id}", "ticket_opened",
                 {"kind": kind, "severity": severity, "subject": subject})
    queue_outbox(conn, config.ESCALATION_EMAIL,
                 f"[{severity}] {kind} ticket {ticket_no}",
                 f"{customer['name']} <{customer['email']}>: {subject}\n{description}")
    conn.commit()
    return {"ticket_no": ticket_no, "kind": kind, "severity": severity, "status": "open"}

def open_ticket_count(conn, customer_id):
    return conn.execute(
        "SELECT COUNT(*) c FROM tickets WHERE customer_id=? AND status IN ('open','in_progress','escalated')",
        (customer_id,),
    ).fetchone()["c"]

# ---- refunds ----
def refund_eligibility(conn, order):
    if order["status"] != "delivered" or not order["delivered_at"]:
        return False, f"Order status is '{order['status']}' — only delivered orders qualify."
    delivered = datetime.fromisoformat(order["delivered_at"])
    if delivered.tzinfo is None:
        delivered = delivered.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - delivered).days
    if days > config.REFUND_WINDOW_DAYS:
        return False, f"Delivered {days} days ago — refund window is {config.REFUND_WINDOW_DAYS} days."
    return True, "Within refund window."

def create_refund(conn, order_id, amount_cents, reason):
    order = conn.execute("SELECT o.*, c.email FROM orders o JOIN customers c ON c.id=o.customer_id WHERE o.id=?",
                         (order_id,)).fetchone()
    refund_no = f"RFD-{order['order_no']}-{amount_cents}"
    cur = conn.execute(
        "INSERT INTO refunds(refund_no, order_id, amount_cents, reason) VALUES (?,?,?,?)",
        (refund_no, order_id, amount_cents, reason),
    )
    record_event(conn, f"refund:{cur.lastrowid}", "refund_processed",
                 {"order_id": order_id, "amount_cents": amount_cents})
    queue_outbox(conn, order["email"], f"Refund {refund_no} processed",
                 f"Your refund of ${amount_cents/100:.2f} for {order['order_no']} is on its way.")
    conn.commit()
    return {"refund_no": refund_no, "amount": amount_cents / 100, "status": "processed"}

# ---- approvals ----
def create_approval(conn, tool_run_id, kind, payload):
    cur = conn.execute(
        "INSERT INTO approvals(tool_run_id, kind, payload_json) VALUES (?,?,?)",
        (tool_run_id, kind, json.dumps(payload)),
    )
    conn.commit()
    return cur.lastrowid

def decide_approval(conn, approval_id, decided_by, approved, reason=""):
    a = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    if not a or a["status"] != "pending":
        raise ValueError("Approval not pending.")
    status = "approved" if approved else "rejected"
    conn.execute(
        "UPDATE approvals SET status=?, decided_by=?, reason=?, decided_at=datetime('now') WHERE id=?",
        (status, decided_by, reason, approval_id),
    )
    record_event(conn, f"approval:{approval_id}", f"approval_{status}", {"by": decided_by})
    if approved and a["kind"] == "refund":
        p = json.loads(a["payload_json"])
        conn.commit()
        return {"status": status, **create_refund(conn, p["order_id"], p["amount_cents"], p["reason"])}
    conn.commit()
    return {"status": status}

# ---- outbox / facts ----
def queue_outbox(conn, recipient, subject, body, channel="email"):
    conn.execute(
        "INSERT INTO outbox(channel, recipient, subject, body) VALUES (?,?,?,?)",
        (channel, recipient, subject, body),
    )

def set_fact(conn, conversation_id, key, value):
    conn.execute(
        """
        INSERT INTO memory_facts(conversation_id, key, value) VALUES (?,?,?)
        ON CONFLICT(conversation_id, key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')
        """,
        (conversation_id, key, value),
    )
    conn.commit()

def get_facts(conn, conversation_id):
    rows = conn.execute(
        "SELECT key, value FROM memory_facts WHERE conversation_id=?", (conversation_id,)
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}

    