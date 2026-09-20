# Laptop_Service_agenet — design

- Agent loop: plan -> verdict -> idempotency -> execute -> event log -> final
- verdict.py breaks:
    SAFE  : get_order, troubleshoot, my_tickets, check_refund_eligibility
    DENY  : refund outside 30d window / not delivered / wrong customer / >5 open tickets
    PERMIT: small refunds (<= AUTO_REFUND_MAX_CENTS), ticket creation
    APPROVAL: large refunds -> approvals table -> decide_aproval() executes refund
- worker.py: drains outbox + escalates open high-severity tickets (status -> escalated)
- append_only.sql: events + outbox are insert-only
- A/B lab: conversations.variant picks system prompt A or B