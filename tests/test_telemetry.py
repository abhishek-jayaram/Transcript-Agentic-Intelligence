"""Observability tests - no Azure, Neo4j or Foundry needed.  Run:  pytest tests/test_telemetry.py"""
import importlib, os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sdk = pytest.importorskip("opentelemetry.sdk.trace")
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture()
def tel(monkeypatch):
    telemetry = importlib.import_module("ti.telemetry")
    exp = InMemorySpanExporter()
    prov = sdk.TracerProvider()
    prov.add_span_processor(SimpleSpanProcessor(exp))
    monkeypatch.setattr(telemetry, "_tracer", prov.get_tracer("ti-test"))
    monkeypatch.delenv("ENABLE_SENSITIVE_DATA", raising=False)
    telemetry._exp = exp
    return telemetry


def test_span_adds_ti_prefix_and_skips_none(tel):
    with tel.span("ti.x", template="t", nothing=None, **{"db.system": "neo4j"}) as s:
        tel.set_attrs(s, rows=3)
    (sp,) = tel._exp.get_finished_spans()
    assert sp.attributes == {"ti.template": "t", "db.system": "neo4j", "ti.rows": 3}

def test_span_records_errors_and_reraises(tel):
    with pytest.raises(ValueError):
        with tel.span("ti.boom"):
            raise ValueError("bad")
    (sp,) = tel._exp.get_finished_spans()
    assert sp.status.status_code.name == "ERROR" and any(e.name == "exception" for e in sp.events)

def test_noop_when_no_tracer(monkeypatch):
    telemetry = importlib.import_module("ti.telemetry")
    monkeypatch.setattr(telemetry, "_tracer", None)
    with telemetry.span("ti.x", a=1) as s:
        telemetry.set_attrs(s, b=2)
    assert s is None

def test_setup_is_off_without_connection_string(monkeypatch, capsys):
    telemetry = importlib.import_module("ti.telemetry")
    monkeypatch.setattr(telemetry, "_enabled", False)
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    assert "off" in telemetry.setup() and telemetry.enabled() is False

def test_setup_survives_bad_connection_string(monkeypatch):
    telemetry = importlib.import_module("ti.telemetry")
    monkeypatch.setattr(telemetry, "_enabled", False)
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "not-a-real-string")
    msg = telemetry.setup()                      # must not raise
    assert msg.startswith("Telemetry: ") and telemetry.enabled() in (True, False)

def test_content_flag(monkeypatch):
    telemetry = importlib.import_module("ti.telemetry")
    monkeypatch.setenv("ENABLE_SENSITIVE_DATA", "false"); assert not telemetry.content_enabled()
    monkeypatch.setenv("ENABLE_SENSITIVE_DATA", "True");  assert telemetry.content_enabled()

def test_tool_spans_nest_and_do_not_leak_query_text(tel, monkeypatch):
    tools = importlib.import_module("ti.tools")
    monkeypatch.setattr(tools, "_oc", object())
    monkeypatch.setattr(tools, "embed", lambda c, t: [[0.0]])
    row = lambda i: dict(id=i, text="t", first_turn=1, last_turn=2, call_id="c", title="T", date="2026-03-10", call_type="support", account="A", score=1.0)
    monkeypatch.setattr(tools, "_run", lambda cy, **p: [row("a"), row("b")] if "queryNodes" in cy else [{"n": 1}])
    out = tools.search_transcripts("super secret customer question", k=2, account="Cobalt")
    tools.graph_query("top_topics")
    spans = {s.name: s for s in tel._exp.get_finished_spans()}
    assert set(spans) == {"ti.search_transcripts", "ti.search.embed", "ti.search.vector", "ti.search.keyword", "ti.graph_query"}
    top = spans["ti.search_transcripts"]
    assert all(spans[n].parent.span_id == top.context.span_id for n in ("ti.search.embed", "ti.search.vector", "ti.search.keyword"))
    assert top.attributes["ti.account"] == "Cobalt" and top.attributes["ti.hits"] == len(out) == 2
    assert spans["ti.graph_query"].attributes["ti.template"] == "top_topics"
    assert "secret" not in str([s.attributes for s in spans.values()])
