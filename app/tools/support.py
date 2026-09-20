"""Support-related tool entry points."""
from ..support_db import (
    create_refund, create_ticket, get_order_for_customer, kb_search, refund_eligibility,
)

def get_order(ctx, order_no):
    o = get_order_for_customer(ctx["conn"], order_no, ctx["customer"]["id"])
    if not o:
        return {"error": "Order not found on your account."}
    return {"order_no": o["order_no"], "model": o["model"], "status": o["status"],
            "price": o["price_cents"] / 100, "delivered_at": o["delivered_at"]}

def check_refund_eligibility(ctx, order_no):
    o = get_order_for_customer(ctx["conn"], order_no, ctx["customer"]["id"])
    if not o:
        return {"error": "Order not found on your account."}
    ok, reason = refund_eligibility(ctx["conn"], o)
    return {"order_no": o["order_no"], "eligible": ok, "reason": reason}

def request_refund(ctx, order_no, amount_cents=None, reason="customer request"):
    # Only reached when verdict.judge returned PERMIT (small refund, eligible).
    o = get_order_for_customer(ctx["conn"], order_no, ctx["customer"]["id"])
    amount = amount_cents or o["price_cents"]
    return create_refund(ctx["conn"], o["id"], amount, reason)

def raise_ticket(ctx, kind, subject, description="", severity="low"):
    return create_ticket(ctx["conn"], ctx["customer"]["id"], kind, subject, description, severity)

def troubleshoot(ctx, issue):
    hit = kb_search(ctx["conn"], issue)
    if not hit["issue"]:
        return {"matched": False, "message": "No KB match — raising a tech support ticket is best."}
    return {"matched": True, **hit}

def my_tickets(ctx):
    rows = ctx["conn"].execute(
        "SELECT ticket_no, kind, subject, severity, status, created_at FROM tickets WHERE customer_id=? ORDER BY id DESC",
        (ctx["customer"]["id"],),
    ).fetchall()
    return {"tickets": [dict(r) for r in rows]}

TOOLS = {
    "get_order": get_order,
    "check_refund_eligibility": check_refund_eligibility,
    "request_refund": request_refund,
    "raise_ticket": raise_ticket,
    "troubleshoot": troubleshoot,
    "my_tickets": my_tickets,
}

SPECS = [
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": (
                "Look up an order's status by order number. Use whenever the customer asks "
                "where their order is, whether it shipped, delivery status, or mentions an order "
                "number (format ORD-XXXX). The order must belong to the logged-in customer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_no": {"type": "string", "description": "Order number, e.g. ORD-1001"}
                },
                "required": ["order_no"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_refund_eligibility",
            "description": (
                "Check whether an order qualifies for a refund BEFORE offering or initiating one. "
                "Policy: order must be delivered and within the 30-day refund window. "
                "Use when the customer asks 'can I get a refund', 'am I eligible', or before request_refund."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_no": {"type": "string", "description": "Order number, e.g. ORD-1001"}
                },
                "required": ["order_no"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_refund",
            "description": (
                "Request a refund for a delivered order. Only call when the customer explicitly "
                "asks for a refund — never proactively. Amount is in cents; omit amount_cents for a "
                "full refund. Outcome depends on policy and may be: processed immediately (small "
                "amounts), routed for human approval (large amounts), or denied (outside window / "
                "not delivered). Always check the tool result and explain the outcome honestly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_no": {"type": "string"},
                    "amount_cents": {
                        "type": "integer",
                        "description": "Refund amount in cents. Omit for full order refund.",
                    },
                    "reason": {"type": "string", "description": "Short reason for the refund"},
                },
                "required": ["order_no"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "raise_ticket",
            "description": (
                "File a ticket when the problem isn't solved or the customer is unhappy. "
                "kind='complaint' for service/product dissatisfaction; kind='tech_support' when "
                "troubleshooting failed or needs a technician. severity: 'high' if the device is "
                "unusable or the customer is very upset; 'medium' for degraded use; 'low' otherwise."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["complaint", "tech_support"]},
                    "subject": {"type": "string", "description": "One-line summary"},
                    "description": {"type": "string", "description": "Details from the customer"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["kind", "subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "troubleshoot",
            "description": (
                "Search the technical knowledge base for common laptop issues (battery, wifi, "
                "slow performance, screen). Use FIRST for technical problems, before raising a "
                "ticket. Present the steps to the customer. If no article matches or the steps "
                "fail, raise a tech_support ticket."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "issue": {"type": "string", "description": "Customer's problem described in their words"}
                },
                "required": ["issue"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "my_tickets",
            "description": "List the customer's existing tickets with status. Use when they ask about their complaint/ticket status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]