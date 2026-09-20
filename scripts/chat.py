from app.agent import run_turn
from app.providers import get_provider
from app.runner import setup
from app.support_db import conversation_variant, decide_approval, get_facts
from app.worker import process_once
from scripts.ab_descriptions import system_prompt

def main():
    conn = setup()
    provider = get_provider()
    email = input("Customer email: ").strip() or "ana@example.com"
    conversation_id = None
    print("Commands: '/approve <id> yes|no' (manager), '/worker' (notifications), 'exit'")
    while True:
        text = input("> ").strip()
        if text == "exit":
            break
        if text == "/worker":
            print(f"processed: {process_once(conn)}")
            continue
        if text.startswith("/approve"):
            _, aid, decision, *reason = text.split(maxsplit=3)
            result = decide_approval(conn, int(aid), "manager@novabooks.example",
                                     decision.lower() == "yes", reason[0] if reason else "")
            print(result)
            continue
        variant = conversation_variant(conn, conversation_id) if conversation_id else "A"
        facts = get_facts(conn, conversation_id) if conversation_id else {}
        reply, conversation_id = run_turn(
            conn, email, text, provider, conversation_id=conversation_id,
            system_prompt=system_prompt(variant, facts))
        print(reply)

if __name__ == "__main__":
    main()