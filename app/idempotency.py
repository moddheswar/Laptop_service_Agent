"""Idempotency handling for repeated requests."""
import json
import uuid

def make_key(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join(str(p) for p in parts)))

def begin_tool_run(conn, key, conversation_id, name, args):
    row = conn.execute("SELECT * FROM tool_runs WHERE idempotency_key=?", (key,)).fetchone()
    if row:
        return row["id"], False
    cur = conn.execute(
        """
        INSERT INTO tool_runs(idempotency_key, conversation_id, name, input_json, status)
        VALUES (?,?,?,?, 'running')
        """,
        (key, conversation_id, name, json.dumps(args)),
    )
    conn.commit()
    return cur.lastrowid, True

def finish_tool_run(conn, run_id, status, output=None, error=None):
    conn.execute(
        """
        UPDATE tool_runs SET status=?, output_json=?, error=?, completed_at=datetime('now') WHERE id=?
        """,
        (status, json.dumps(output) if output is not None else None, error, run_id),
    )
    conn.commit()