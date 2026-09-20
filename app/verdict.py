"""Service decision and verdict handling."""
from . import config
from .domain import Decision, Verdict
from .support_db import (
    get_order_for_customer, refund_eligibility, open_ticket_count,
)

SAFE_TOOLS = {"get_order", "troubleshoot", "my_tickets", "check_refund_eligibility"}
MAX_OPEN_TICKETS = 5

def judge(conn, customer, tool_name, args):
    if tool_name in SAFE_TOOLS:
        return Verdict(Decision.PERMIT)

    if tool_name == "raise_ticket":
        if open_ticket_count(conn, customer["id"]) >= MAX_OPEN_TICKETS:
            return Verdict(Decision.DENY, f"You have {MAX_OPEN_TICKETS} open tickets — let's resolve those first.")
        return Verdict(Decision.PERMIT)

    if tool_name == "request_refund":
        order = get_order_for_customer(conn, args.get("order_no", ""), customer["id"])
        if not order:
            return Verdict(Decision.DENY, "I couldn't find that order on your account.")
        ok, reason = refund_eligibility(conn, order)
        if not ok:
            return Verdict(Decision.DENY, reason)
        amount = args.get("amount_cents") or order["price_cents"]   # None = full refund
        if amount > order["price_cents"]:
            return Verdict(Decision.DENY, "Refund exceeds the order total.")
        if amount > config.AUTO_REFUND_MAX_CENTS:
            return Verdict(Decision.APPROVAL,
                           f"Refunds over ${config.AUTO_REFUND_MAX_CENTS/100:.0f} need manager approval.")
        return Verdict(Decision.PERMIT)

    return Verdict(Decision.DENY, f"Unknown tool: {tool_name}")