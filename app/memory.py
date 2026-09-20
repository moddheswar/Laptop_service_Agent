"""Conversation and agent memory interfaces."""
# memory.py
from .support_db import extract_order_no, set_fact, get_facts

class Memory:
    def __init__(self, facts):
        self.facts = facts

    @classmethod
    def load(cls, conn, conversation_id):
        return cls(get_facts(conn, conversation_id))

    def notice(self, conn, conversation_id, text):
        order_no = extract_order_no(text)
        if order_no:
            self.facts["order_no"] = order_no
            set_fact(conn, conversation_id, "order_no", order_no)