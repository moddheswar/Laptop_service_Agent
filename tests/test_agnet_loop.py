# tests/test_agent_loop.py
import json
import pytest
from app.agent import run_turn
from app.providers import ModelResponse
from app.runner import setup
from app.support_db import decide_approval

@pytest.fixture()
def conn(tmp_path):
    return setup(str(tmp_path / "test.db"))

class SequenceProvider:
    def __init__(self, responses):
        self.responses = list(responses)
    def respond(self, history, system_prompt, tools):
        assert tools, "tool specs must be passed to the model"
        return self.responses.pop(0)
        
def tc(tid, name, args):
    return ModelResponse(tool_calls=[{"id": tid, "name": name, "args": args}])

def test_multi_round_chaining(conn):
    p = SequenceProvider([
        tc("c1", "check_refund_eligibility", {"order_no": "ORD-1001"}),
        ModelResponse(content="Good news — ORD-1001 is within the refund window."),
    ])
    reply, _ = run_turn(conn, "ana@example.com", "can I refund ORD-1001?", p)
    assert "within the refund window" in reply
    assert conn.execute("SELECT COUNT(*) c FROM tool_runs WHERE status='done'").fetchone()["c"] == 1

def test_denial_is_fed_back_to_model(conn):
    p = SequenceProvider([
        tc("c1", "request_refund", {"order_no": "ORD-3001"}),   # shipped -> denied
        ModelResponse(content="That order hasn't been delivered yet, so it can't be refunded."),
    ])
    reply, _ = run_turn(conn, "ana@example.com", "refund ORD-3001", p)
    assert "hasn't been delivered" in reply
    assert conn.execute("SELECT COUNT(*) c FROM refunds").fetchone()["c"] == 0
    assert conn.execute("SELECT status FROM tool_runs").fetchone()["status"] == "denied"

def test_approval_round_trip(conn):
    p = SequenceProvider([
        tc("c1", "request_refund", {"order_no": "ORD-1001"}),   # full price -> approval
        ModelResponse(content="Your refund request is pending manager approval."),
    ])
    reply, _ = run_turn(conn, "ana@example.com", "refund ORD-1001 fully", p)
    assert "pending" in reply.lower()
    ap = conn.execute("SELECT * FROM approvals WHERE status='pending'").fetchone()
    result = decide_approval(conn, ap["id"], "manager@novabooks.example", True, "ok")
    assert result["status"] == "approved"
    assert conn.execute("SELECT COUNT(*) c FROM refunds").fetchone()["c"] == 1

def test_same_tool_call_id_never_executes_twice(conn):
    p = SequenceProvider([
        tc("same-id", "check_refund_eligibility", {"order_no": "ORD-1001"}),
        tc("same-id", "check_refund_eligibility", {"order_no": "ORD-1001"}),  # duplicate
        ModelResponse(content="done"),
    ])
    run_turn(conn, "ana@example.com", "check twice", p)
    assert conn.execute("SELECT COUNT(*) c FROM tool_runs").fetchone()["c"] == 1