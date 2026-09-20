import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("AGENT_DB", str(BASE_DIR / "agent.db"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

REFUND_WINDOW_DAYS = int(os.getenv("REFUND_WINDOW_DAYS", "30"))
AUTO_REFUND_MAX_CENTS = int(os.getenv("AUTO_REFUND_MAX_CENTS", "20000"))
ESCALATION_EMAIL = os.getenv("ESCALATION_EMAIL", "support-team@novabooks.example")
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "8"))