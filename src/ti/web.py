"""Step 6b: local web UI - persona picker + chat.     python -m ti.web [port]     ->  http://127.0.0.1:8000
A thin layer over the SAME agents the CLI uses (no new agent logic): one HTML page + a tiny JSON API.
Bound to 127.0.0.1 on purpose - there is no login, and the server runs with YOUR `az login` identity and Neo4j password."""
import asyncio, os, sys, time, traceback
from collections import OrderedDict
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from .agent_base import ask
from .agent_tools import TRACE
from . import orchestrator, sales_agent, support_agent, product_agent, eng_agent
from . import telemetry

STATIC = Path(__file__).parent / "static"

PERSONAS = OrderedDict(
    auto=dict(label="Copilot (auto)", blurb="Ask anything. It picks the right lens and tells you which.", module=orchestrator),
    sales=dict(label="Sales Manager", blurb="Churn signals, renewal risk, competitor pressure, follow-up gaps.", module=sales_agent),
    support=dict(label="Support Lead", blurb="Repeat issues, commitments to customers, resolution patterns.", module=support_agent),
    product=dict(label="Product Manager", blurb="Feature gaps, Comply v2 reception, how we compare to competitors.", module=product_agent),
    eng=dict(label="Engineering Lead", blurb="Incidents, root causes, and whether fixes shipped when promised.", module=eng_agent),
)

_agents = {}                  # persona id -> Agent (built lazily, reused)
_sessions = OrderedDict()     # (browser session id, persona id) -> agent session (keeps conversation context)
MAX_SESSIONS = 100
_lock = asyncio.Lock()        # one question at a time: the tool TRACE is a process-wide list, so concurrent runs would mix up

def _agent(pid):
    if pid not in _agents:
        _agents[pid] = PERSONAS[pid]["module"].build()
    return _agents[pid]

def _session(pid, sid):
    key = (sid, pid)
    if key not in _sessions:
        _sessions[key] = _agent(pid).create_session()
        while len(_sessions) > MAX_SESSIONS:
            _sessions.popitem(last=False)
    _sessions.move_to_end(key)
    return _sessions[key]

def _describe(tool, args):
    """One line per tool call for the 'how I answered' panel."""
    error = tool.endswith(" ERROR")
    name = tool.removesuffix(" ERROR")
    if error:
        detail = str(args.get("error", ""))[:200]
    elif name == "graph_query":
        extra = {k: v for k, v in args.items() if k != "template" and v not in (None, "")}
        detail = args.get("template", "") + (" " + ", ".join(f"{k}={v}" for k, v in extra.items()) if extra else "")
    else:
        detail = args.get("query", "")
        filt = [f"{k}={args[k]}" for k in ("account", "call_type", "date_from", "date_to") if args.get(k)]
        if filt:
            detail += "  [" + ", ".join(filt) + "]"
    return dict(tool=name, detail=detail, error=error)

def _friendly(e):
    s = f"{type(e).__name__}: {e}"
    low = s.lower()
    if "az login" in low or "azureclicredential" in low or "credentialunavailable" in low or "aadsts" in low or "clientauthentication" in low:
        return ("Azure sign-in problem. Locally run `az login` and try again; in Docker/Kubernetes check AZURE_TENANT_ID, "
                "AZURE_CLIENT_ID, AZURE_CLIENT_SECRET and the service principal's role on the Foundry project. (" + s[:160] + ")")
    if "neo4j" in low or "serviceunavailable" in low or "authenticat" in low and "bolt" in low:
        return "Could not reach Neo4j. Check that the Aura instance is running and the .env credentials are right. (" + s[:160] + ")"
    if "429" in low or "rate" in low and "limit" in low:
        return "The model endpoint is rate limited. Wait a minute and try again."
    return s[:400]

app = FastAPI(title="Transcript Intelligence", docs_url=None, redoc_url=None)

class ChatIn(BaseModel):
    persona: str
    session_id: str = Field(min_length=8, max_length=64)
    message: str = Field(min_length=1, max_length=2000)

class ResetIn(BaseModel):
    persona: str
    session_id: str = Field(min_length=8, max_length=64)

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

@app.get("/healthz")
def healthz():
    """Liveness / readiness probe for Docker and Kubernetes. Deliberately touches neither Neo4j nor Azure."""
    return dict(status="ok")

@app.get("/api/personas")
def personas():
    return [dict(id=pid, label=p["label"], blurb=p["blurb"], demos=list(p["module"].DEMO)) for pid, p in PERSONAS.items()]

@app.post("/api/chat")
async def chat(body: ChatIn):
    if body.persona not in PERSONAS:
        raise HTTPException(404, f"Unknown persona '{body.persona}'")
    msg = body.message.strip()
    if not msg:
        raise HTTPException(422, "Empty question")
    async with _lock:
        del TRACE[:]                      # keep the process-wide trace small; safe because we hold the lock
        t0 = time.time()
        with telemetry.span("ti.question", persona=body.persona, session=body.session_id,
                            question=msg if telemetry.content_enabled() else None) as sp:   # question text only if explicitly allowed
            try:
                answer = await ask(_agent(body.persona), msg, session=_session(body.persona, body.session_id))
            except Exception as e:
                traceback.print_exc()
                telemetry.set_attrs(sp, failed=True)
                raise HTTPException(502, _friendly(e))
            steps = [_describe(t, a) for t, a in TRACE]
            telemetry.set_attrs(sp, tool_calls=len(steps), tool_errors=sum(1 for x in steps if x["error"]),
                                answer_chars=len(answer or ""))
    return dict(answer=answer, steps=steps, seconds=round(time.time() - t0, 1))

@app.post("/api/reset")
def reset(body: ResetIn):
    _sessions.pop((body.session_id, body.persona), None)
    return dict(ok=True)

def main():
    import uvicorn
    telemetry.setup()
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else int(os.environ.get("PORT", 8000))
    host = os.environ.get("TI_HOST", "127.0.0.1")  # only the Docker image sets TI_HOST=0.0.0.0 (publish the port on 127.0.0.1 only!)
    print(f"Transcript Intelligence UI -> http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}   (Ctrl+C to stop)")
    uvicorn.run(app, host=host, port=port, log_level="warning")

if __name__ == "__main__":
    main()
