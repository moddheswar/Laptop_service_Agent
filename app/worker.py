"""Background worker support."""
# worker.py
import time
from . import config
from .notify import drain_outbox
from .support_db import connect, init_db, queue_outbox, record_event

def escalate_high_severity(conn):
    """Worker duty: high-severity open tickets go to the human support team once."""
    rows = conn.execute(
        "SELECT * FROM tickets WHERE severity='high' AND status='open'"
    ).fetchall()
    for r in rows:
        queue_outbox(conn, config.ESCALATION_EMAIL, f"ESCALATION {r['ticket_no']}",
                     f"{r['kind']}: {r['subject']}\n{r['description']}")
        conn.execute("UPDATE tickets SET status='escalated' WHERE id=?", (r["id"],))
        record_event(conn, f"ticket:{r['id']}", "ticket_escalated", {"ticket_no": r["ticket_no"]})
    conn.commit()
    return len(rows)

def process_once(conn):
    n1 = drain_outbox(conn)
    n2 = escalate_high_severity(conn)
    return n1 + n2

def run(interval=2):
    conn = connect()
    init_db(conn)
    while True:
        n = process_once(conn)
        if n:
            print(f"worker: processed {n} item(s)")
        time.sleep(interval)