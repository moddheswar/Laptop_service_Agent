from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import run_turn
from .providers import get_provider
from .runner import setup
from .support_db import decide_approval, get_customer_by_email, history_for_llm

BASE_DIR = __file__.rsplit("/", 1)[0]
provider = get_provider()          # one Gemini client for the app lifetime

@asynccontextmanager
async def lifespan(app):
    setup()                        # create DB + seed on startup
    yield

app = FastAPI(title="NovaSupport Agent", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=f"{BASE_DIR}/static"), name="static")

# ---------- schemas ----------
class ChatIn(BaseModel):
    email: str
    message: str
    conversation_id: int | None = None

class ChatOut(BaseModel):
    reply: str
    conversation_id: int
    approval_id: int | None = None

class DecideIn(BaseModel):
    approved: bool
    decided_by: str = "manager@novabooks.example"
    reason: str = ""

# ---------- helpers ----------
def _conn():
    from .support_db import connect
    conn = connect()
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def _pending_approval(conn, conversation_id):
    row = conn.execute(
        """
        SELECT a.id FROM approvals a
        JOIN tool_runs t ON t.id = a.tool_run_id
        WHERE t.conversation_id = ? AND a.status = 'pending'
        ORDER BY a.id DESC LIMIT 1
        """,
        (conversation_id,),
    ).fetchone()
    return row["id"] if row else None

# ---------- routes ----------
@app.get("/")
def index():
    return FileResponse(f"{BASE_DIR}/static/index.html")

@app.post("/api/chat", response_model=ChatOut)
def chat(body: ChatIn):
    if get_customer_by_email(_conn(), body.email) is None:
        raise HTTPException(404, "Unknown customer email")
    conn = _conn()
    reply, conversation_id = run_turn(
        conn, body.email, body.message, provider,
        conversation_id=body.conversation_id, system_prompt=_system_prompt(conn, body.conversation_id),
    )
    approval_id = _pending_approval(conn, conversation_id)
    conn.close()
    return ChatOut(reply=reply, conversation_id=conversation_id, approval_id=approval_id)

@app.get("/api/conversations/{cid}/messages")
def messages(cid: int):
    conn = _conn()
    view = [
        {"role": m["role"], "content": m["content"]}
        for m in history_for_llm(conn, cid)
        if m["role"] in ("user", "assistant") and m.get("content")
    ]
    conn.close()
    return {"messages": view}

@app.get("/api/approvals/pending")
def pending_approvals():
    conn = _conn()
    rows = conn.execute(
        """
        SELECT a.id, a.kind, a.payload_json, a.created_at, t.conversation_id
        FROM approvals a JOIN tool_runs t ON t.id = a.tool_run_id
        WHERE a.status = 'pending'
        ORDER BY a.id DESC
        """
    ).fetchall()
    conn.close()
    return {"approvals": [dict(r) for r in rows]}

@app.post("/api/approvals/{aid}/decide")
def decide(aid: int, body: DecideIn):
    conn = _conn()
    try:
        result = decide_approval(conn, aid, body.decided_by, body.approved, body.reason)
    except ValueError as e:
        conn.close()
        raise HTTPException(400, str(e))
    conn.close()
    return result

def _system_prompt(conn, conversation_id):
    from scripts.ab_descriptions import system_prompt
    from .support_db import conversation_variant, get_facts
    if conversation_id is None:
        return system_prompt("A", {})
    return system_prompt(
        conversation_variant(conn, conversation_id),
        get_facts(conn, conversation_id),
    )