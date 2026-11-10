"""Step 7: observability with Azure Application Insights (OpenTelemetry).

Off by default. Set APPLICATIONINSIGHTS_CONNECTION_STRING in .env to turn it on:
  - Agent Framework already emits spans for every agent run, model call and tool call;
  - this module sends them to Azure Monitor and adds our own spans (graph_query, search_transcripts and its
    embed / vector / keyword steps) so you can see where the time goes;
  - prompts, answers and tool arguments are NOT recorded unless you set ENABLE_SENSITIVE_DATA=true
    (transcripts are customer calls - keep it false outside development).
Everything here is safe to call when telemetry is off or the packages are missing: it just does nothing."""
import atexit, os, sys
from contextlib import contextmanager

try:                                   # opentelemetry-api ships with agent-framework; without a provider it is a no-op
    from opentelemetry import trace as _trace
    _tracer = _trace.get_tracer("ti")
except Exception:                      # pragma: no cover
    _trace = _tracer = None

SERVICE = "transcript-intelligence"
_enabled = False

def _flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")

def content_enabled():
    """True only when the user explicitly allowed prompts / answers to be recorded."""
    return _flag("ENABLE_SENSITIVE_DATA")

def enabled():
    return _enabled

def setup(service_name=SERVICE):
    """Call once at start-up. Returns a short status string (also printed)."""
    global _enabled
    if _enabled:
        return "already on"
    cs = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not cs:
        return _say("off (set APPLICATIONINSIGHTS_CONNECTION_STRING in .env to send traces to Azure)")
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from agent_framework.observability import create_resource, enable_instrumentation
    except ImportError as e:
        return _say(f"off ({e.name or e} is not installed - run: pip install -r requirements.txt)")
    try:
        configure_azure_monitor(connection_string=cs, resource=create_resource(service_name=service_name),
                                enable_live_metrics=False)
        enable_instrumentation()       # prompts/answers stay out of the traces unless ENABLE_SENSITIVE_DATA=true
    except Exception as e:             # a bad connection string must not stop the app from working
        return _say(f"off (could not start: {type(e).__name__}: {str(e)[:150]})")
    atexit.register(flush)
    _enabled = True
    return _say("ON -> Azure Application Insights" + (" (prompt/answer text IS recorded)" if content_enabled() else " (no prompt/answer text)"))

def _say(msg):
    msg = "Telemetry: " + msg
    print(msg, file=sys.stderr)
    return msg

def flush():
    """Send anything still buffered (short-lived CLI runs would otherwise exit before the exporter fires)."""
    try:
        p = _trace.get_tracer_provider()
        if hasattr(p, "force_flush"):
            p.force_flush(5000)
    except Exception:
        pass

@contextmanager
def span(name, **attrs):
    """with span("ti.graph_query", template=t) as s: ...   - a no-op when telemetry is off. Errors are recorded and re-raised."""
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as s:
        for k, v in attrs.items():
            if v is not None:
                s.set_attribute(k if "." in k else f"ti.{k}", v)
        yield s

def set_attrs(s, **attrs):
    if s is not None:
        for k, v in attrs.items():
            if v is not None:
                s.set_attribute(k if "." in k else f"ti.{k}", v)
