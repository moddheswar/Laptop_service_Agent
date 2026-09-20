import json
import random

from . import config, idempotency
from .domain import Decision
from .memory import Memory
from .support_db import (
    add_message, create_approval, create_conversation, get_customer_by_email,
    get_order_for_customer, history_for_llm, record_event,
)
from .tools.support import SPECS, TOOLS
from .verdict import judge

def _execute_tool_call(conn, customer, conversation_id, call):
    """Runs ONE tool call behind verdict + idempotency. Returns the dict fed back to the LLM."""
    name, args = call["name"], call.get("args", {})
    key = idempotency.make_key(conversation_id, call["id"])  # tool_call id = natural idempotency key
    run_id, fresh = idempotency.begin_tool_run(conn, key, conversation_id, name, args)

    if not fresh:  # replay — return stored result, never re-execute side effects
        row = conn.execute("SELECT output_json, status FROM tool_runs WHERE id=?", (run_id,)).fetchone()
        return json.loads(row["output_json"] or "{}"), row["status"]

    record_event(conn, f"conversation:{conversation_id}", "tool_started", {"name": name, "args": args})
    verdict = judge(conn, customer, name, args)

    if verdict.decision == Decision.DENY:
        output = {"ok": False, "denied": True, "error": verdict.reason}
        idempotency.finish_tool_run(conn, run_id, "denied", output)
        return output, "denied"

    if verdict.decision == Decision.APPROVAL:
        order = get_order_for_customer(conn, args["order_no"], customer["id"])
        amount = args.get("amount_cents") or order["price_cents"]
        approval_id = create_approval(conn, run_id, "refund",
                                      {"order_id": order["id"], "amount_cents": amount,
                                       "reason": args.get("reason", "")})
        output = {"ok": True, "status": "pending_approval", "approval_id": approval_id,
                  "message": verdict.reason}
        idempotency.finish_tool_run(conn, run_id, "waiting_approval", output)
        conn.execute("UPDATE conversations SET status='waiting_approval' WHERE id=?", (conversation_id,))
        conn.commit()
        return output, "waiting_approval"

    ctx = {"conn": conn, "customer": customer, "conversation_id": conversation_id, "tool_run_id": run_id}
    try:
        output = {"ok": True, **TOOLS[name](ctx, **args)}
        idempotency.finish_tool_run(conn, run_id, "done", output)
        record_event(conn, f"conversation:{conversation_id}", "tool_done", {"name": name})
        return output, "done"
    except Exception as e:
        output = {"ok": False, "error": str(e)}
        idempotency.finish_tool_run(conn, run_id, "failed", output)
        return output, "failed"

def run_turn(conn, email, user_text, provider, conversation_id=None, system_prompt=""):
    customer = get_customer_by_email(conn, email)
    if customer is None:
        raise ValueError(f"Unknown customer: {email}")

    if conversation_id is None:
        conversation_id = create_conversation(conn, customer["id"], random.choice(["A", "B"]))

    add_message(conn, conversation_id, "user", user_text)
    record_event(conn, f"conversation:{conversation_id}", "user_message", {"text": user_text})

    memory = Memory.load(conn, conversation_id)
    memory.notice(conn, conversation_id, user_text)

    # ---- real multi-round agent loop ----
    for _ in range(config.MAX_TOOL_ROUNDS):
        hist = history_for_llm(conn, conversation_id, system_prompt)
        resp = provider.respond(hist, system_prompt, SPECS)

        if not resp.tool_calls:
            final = resp.content or "I'm not sure how to respond to that."
            add_message(conn, conversation_id, "assistant", final)
            return final, conversation_id

        tool_calls_db = [
            {"id": c["id"], "type": "function",
             "function": {"name": c["name"], "arguments": json.dumps(c["args"])}}
            for c in resp.tool_calls
        ]
        add_message(conn, conversation_id, "assistant", resp.content or "",
                    tool_calls_json=json.dumps(tool_calls_db))

        for call in resp.tool_calls:
            output, status = _execute_tool_call(conn, customer, conversation_id, call)
            add_message(conn, conversation_id, "tool", json.dumps(output),
                        tool_call_id=call["id"], tool_calls_json=json.dumps([call]))

    final = "This needs a human agent — I'm escalating your conversation."
    add_message(conn, conversation_id, "assistant", final)
    conn.execute("UPDATE conversations SET status='escalated' WHERE id=?", (conversation_id,))
    conn.commit()
    return final, conversation_id