"""Notification interfaces."""
# notify.py
from .support_db import queue_outbox, record_event

def drain_outbox(conn, sender=print):
    rows = conn.execute("SELECT * FROM outbox WHERE status='pending'").fetchall()
    for r in rows:
        sender(f"[{r['channel']}] -> {r['recipient']}: {r['subject']}")
        conn.execute("UPDATE outbox SET status='sent', sent_at=datetime('now') WHERE id=?", (r["id"],))
        record_event(conn, f"outbox:{r['id']}", "notification_sent", {"to": r["recipient"]})
    conn.commit()
    return len(rows)