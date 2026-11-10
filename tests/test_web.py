"""Web UI API tests. No Foundry / Neo4j needed: ti.agent_base and ti.agent_tools are replaced by fakes, the persona
modules (and their DEMO lists) are the real ones.   Run:  pytest tests/test_web.py"""
import os, sys, types
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
pytest.importorskip("fastapi"); pytest.importorskip("httpx")
from fastapi.testclient import TestClient


@pytest.fixture()
def web(monkeypatch):
    before = set(sys.modules)
    state = {"fail": None}
    trace = []

    class FakeAgent:
        def __init__(self, name): self.name = name
        def create_session(self): return {"turns": []}

    async def fake_ask(agent, q, session=None, trace=False):
        if state["fail"]:
            raise state["fail"]
        session["turns"].append(q)
        trace_list.append(("graph_query", {"template": "competitor_mentions", "competitor": "SentinelShield"}))
        trace_list.append(("search_transcripts", {"query": "pricing offers", "account": "Cobalt", "call_type": None, "date_from": None, "date_to": None}))
        return f"[Lens: Sales Manager]\n\nAnswer from {agent.name} (turn {len(session['turns'])}): {q}"

    trace_list = trace
    ab = types.ModuleType("ti.agent_base")
    ab.make_agent = lambda name, instructions, tools=None, rules=None: FakeAgent(name)
    ab.cli = lambda *a, **k: None
    ab.ask = fake_ask
    at = types.ModuleType("ti.agent_tools")
    at.TRACE = trace
    monkeypatch.setitem(sys.modules, "ti.agent_base", ab)
    monkeypatch.setitem(sys.modules, "ti.agent_tools", at)
    for m in ("ti.web", "ti.orchestrator", "ti.sales_agent", "ti.support_agent", "ti.product_agent", "ti.eng_agent"):
        monkeypatch.delitem(sys.modules, m, raising=False)
    import ti.web as w
    w._state = state
    yield w
    for k in set(sys.modules) - before:
        if k.startswith("ti."):
            del sys.modules[k]


SID = "browser-session-1"

def test_personas_listed_with_demo_questions(web):
    r = TestClient(web.app).get("/api/personas")
    assert r.status_code == 200
    ps = r.json()
    assert [p["id"] for p in ps] == ["auto", "sales", "support", "product", "eng"]
    assert all(p["label"] and p["blurb"] and len(p["demos"]) >= 3 for p in ps)

def test_index_served(web):
    r = TestClient(web.app).get("/")
    assert r.status_code == 200 and "Transcript Intelligence" in r.text and "/api/chat" in r.text

def test_chat_returns_answer_and_tool_steps(web):
    r = TestClient(web.app).post("/api/chat", json={"persona": "sales", "session_id": SID, "message": "Who is at risk?"})
    assert r.status_code == 200
    j = r.json()
    assert "Answer from SalesManagerCopilot" in j["answer"] and "Who is at risk?" in j["answer"]
    assert [s["tool"] for s in j["steps"]] == ["graph_query", "search_transcripts"]
    assert j["steps"][0]["detail"] == "competitor_mentions competitor=SentinelShield"
    assert j["steps"][1]["detail"] == "pricing offers  [account=Cobalt]"
    assert isinstance(j["seconds"], (int, float))

def test_conversation_context_is_per_session_and_persona(web):
    c = TestClient(web.app)
    ask = lambda persona, sid, m: c.post("/api/chat", json={"persona": persona, "session_id": sid, "message": m}).json()["answer"]
    assert "turn 1" in ask("sales", SID, "a")
    assert "turn 2" in ask("sales", SID, "b")          # same session continues
    assert "turn 1" in ask("eng", SID, "c")            # other persona = fresh conversation
    assert "turn 1" in ask("sales", "other-browser-2", "d")
    c.post("/api/reset", json={"persona": "sales", "session_id": SID})
    assert "turn 1" in ask("sales", SID, "e")          # reset starts over

def test_trace_is_cleared_between_requests(web):
    c = TestClient(web.app)
    for _ in range(3):
        j = c.post("/api/chat", json={"persona": "auto", "session_id": SID, "message": "q"}).json()
        assert len(j["steps"]) == 2                    # not 2, 4, 6

@pytest.mark.parametrize("body,code", [
    ({"persona": "nope", "session_id": SID, "message": "hi"}, 404),
    ({"persona": "sales", "session_id": SID, "message": "   "}, 422),
    ({"persona": "sales", "session_id": SID, "message": ""}, 422),
    ({"persona": "sales", "session_id": SID, "message": "x" * 2001}, 422),
    ({"persona": "sales", "session_id": "short", "message": "hi"}, 422),
])
def test_bad_requests_rejected(web, body, code):
    assert TestClient(web.app).post("/api/chat", json=body).status_code == code

def test_agent_failure_becomes_readable_502(web):
    web._state["fail"] = RuntimeError("AzureCliCredential failed: please run 'az login'")
    r = TestClient(web.app).post("/api/chat", json={"persona": "sales", "session_id": SID, "message": "hi"})
    assert r.status_code == 502 and "az login" in r.json()["detail"]
    web._state["fail"] = None
    assert TestClient(web.app).post("/api/chat", json={"persona": "sales", "session_id": SID, "message": "hi"}).status_code == 200


def test_question_span_hides_question_text_unless_allowed(web, monkeypatch):
    sdk = pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    exp = InMemorySpanExporter(); prov = sdk.TracerProvider(); prov.add_span_processor(SimpleSpanProcessor(exp))
    monkeypatch.setattr(web.telemetry, "_tracer", prov.get_tracer("t"))
    c = TestClient(web.app)
    monkeypatch.delenv("ENABLE_SENSITIVE_DATA", raising=False)
    c.post("/api/chat", json={"persona": "sales", "session_id": SID, "message": "private question"})
    sp = exp.get_finished_spans()[-1]
    assert sp.name == "ti.question" and sp.attributes["ti.persona"] == "sales" and sp.attributes["ti.tool_calls"] == 2
    assert "ti.question" not in sp.attributes
    monkeypatch.setenv("ENABLE_SENSITIVE_DATA", "true")
    c.post("/api/chat", json={"persona": "sales", "session_id": SID, "message": "private question"})
    assert exp.get_finished_spans()[-1].attributes["ti.question"] == "private question"
    web._state["fail"] = RuntimeError("boom")
    assert c.post("/api/chat", json={"persona": "sales", "session_id": SID, "message": "x"}).status_code == 502
    assert exp.get_finished_spans()[-1].attributes["ti.failed"] is True


def test_healthz_needs_no_backend(web):
    r = TestClient(web.app).get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}

def test_service_principal_errors_get_a_helpful_message(web):
    web._state["fail"] = RuntimeError("ClientAuthenticationError: AADSTS7000215: Invalid client secret provided")
    r = TestClient(web.app).post("/api/chat", json={"persona": "sales", "session_id": SID, "message": "hi"})
    assert r.status_code == 502 and "AZURE_CLIENT_SECRET" in r.json()["detail"]
