"""Step 3: the two tools the agents will call.
  graph_query(template, params)  - safe, parameterised Cypher templates (no free-form Cypher from the LLM)
  search_transcripts(query, ...) - hybrid (vector + keyword) search, merged with RRF, with citations
Every row carries call ids so answers can cite evidence."""
import logging, re, warnings
logging.getLogger("neo4j.notifications").setLevel(logging.CRITICAL)
logging.getLogger("neo4j").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", module="neo4j")
from .config import neo4j_driver, openai_client, embed
from .telemetry import span, set_attrs   # no-ops unless Application Insights is switched on (Step 7)

_drv = _oc = None
def _run(cypher, **p):
    global _drv
    _drv = _drv or neo4j_driver()
    with _drv.session(notifications_min_severity="OFF") as s:  # ask the server to send no notifications at all
        return s.run(cypher, **p).data()

DEFAULT_INCIDENT = "detect-outage-2026-03"
MAX_ROWS = 500  # safety cap; large templates also take their own LIMIT

# name -> (description, {param: default}, cypher)
TEMPLATES = {
 "churn_no_followup": ("Accounts with a churn_signal call in a date window and NO later call afterwards.",
  {"since": "2026-03-10", "until": "2026-03-18"},
  """MATCH (a:Account)<-[:ABOUT]-(c:Call)-[:HAS_MOMENT]->(:Moment {type:'churn_signal'})
     WHERE c.date >= $since AND c.date <= $until
     WITH a, max(c.date) AS last_signal, collect(DISTINCT c.id) AS call_ids
     OPTIONAL MATCH (a)<-[:ABOUT]-(later:Call) WHERE later.date > last_signal
     WITH a, last_signal, call_ids, count(later) AS later_calls WHERE later_calls = 0
     RETURN a.name AS account, properties(a).renewal_date AS renewal_date, last_signal, call_ids ORDER BY last_signal"""),
 "competitor_mentions": ("Which accounts mention which competitor (calls, last mention). competitor=null for all.",
  {"competitor": None},
  """MATCH (k:Competitor)<-[:MENTIONS]-(c:Call)-[:ABOUT]->(a:Account)
     WHERE $competitor IS NULL OR toLower(k.name) = toLower($competitor)
     RETURN k.name AS competitor, a.name AS account, count(c) AS calls, max(c.date) AS last_mention,
            collect(c.id)[..5] AS call_ids ORDER BY competitor, calls DESC"""),
 "moments_by_type": ("Tagged moments (churn_signal, feature_gap, technical_issue, concern, praise, pricing_offer, positive_pivot, action_item), optionally filtered by product and by date window (since/until, YYYY-MM-DD; use since for 'after launch' questions) (Detect, Comply, Protect, Identity, Backup, LogVault, CloudPrime; 'Comply v2' matches Comply).",
  {"type": "feature_gap", "product": None, "since": None, "until": None, "limit": 25},
  """MATCH (m:Moment {type:$type})<-[:HAS_MOMENT]-(c:Call)
     WHERE ($since IS NULL OR c.date >= $since) AND ($until IS NULL OR c.date <= $until)
     OPTIONAL MATCH (c)-[:ABOUT]->(a:Account)
     OPTIONAL MATCH (c)-[:MENTIONS]->(p:Product)
     WITH m, c, a, collect(DISTINCT p.name) AS products
     WHERE $product IS NULL OR any(n IN products WHERE toLower($product) CONTAINS toLower(n))
     RETURN coalesce(a.name, '(internal call)') AS account, c.type AS call_type, c.date AS date,
            m.text AS moment, products, c.id AS call_id
     ORDER BY date LIMIT $limit"""),
 "account_timeline": ("All calls for an account (name substring) in date order, with sentiment score.",
  {"account": "Trailhead"},
  """MATCH (a:Account)<-[:ABOUT]-(c:Call) WHERE toLower(a.name) CONTAINS toLower($account)
     RETURN a.name AS account, c.date AS date, c.title AS title, c.type AS type,
            c.sentiment AS sentiment, c.sentiment_score AS score, c.id AS call_id ORDER BY date"""),
 "repeat_support_accounts": ("Accounts with at least N support calls (repeat contacts).",
  {"min_cases": 2},
  """MATCH (a:Account)<-[:ABOUT]-(c:Call {type:'support'})
     WITH a, collect(c) AS cs WHERE size(cs) >= $min_cases
     RETURN a.name AS account, size(cs) AS cases, [x IN cs | x.title] AS titles, [x IN cs | x.id] AS call_ids
     ORDER BY cases DESC, account"""),
 "incident_impact": ("Accounts touched by an incident: call count, date span, average sentiment (lowest first).",
  {"incident_id": DEFAULT_INCIDENT},
  """MATCH (:Incident {id:$incident_id})<-[:RELATES_TO]-(c:Call)-[:ABOUT]->(a:Account)
     RETURN a.name AS account, count(c) AS calls, min(c.date) AS first_call, max(c.date) AS last_call,
            round(avg(c.sentiment_score), 1) AS avg_sentiment, collect(c.id)[..5] AS call_ids
     ORDER BY avg_sentiment, account"""),
 "commitments_after_incident": ("Action items from incident-related calls since a date, with owner when internal.",
  {"incident_id": DEFAULT_INCIDENT, "since": "2026-03-10", "limit": 40},
  """MATCH (:Incident {id:$incident_id})<-[:RELATES_TO]-(c:Call)-[:HAS_ACTION]->(x:ActionItem)
     WHERE c.date >= $since
     OPTIONAL MATCH (p:Person)-[:OWNS]->(x)
     RETURN c.date AS date, c.title AS call, coalesce(p.name, x.owner_name) AS owner, p.team AS team,
            x.text AS action, c.id AS call_id ORDER BY date LIMIT $limit"""),
 "incident_timeline": ("Earliest-first list of every call that references an incident (all call types, internal too). Use to find when an incident began.",
  {"incident_id": DEFAULT_INCIDENT, "limit": 15},
  """MATCH (:Incident {id:$incident_id})<-[:RELATES_TO]-(c:Call)
     OPTIONAL MATCH (c)-[:ABOUT]->(a:Account)
     RETURN c.date AS date, c.type AS call_type, coalesce(a.name, '(internal)') AS account, c.title AS title, c.id AS call_id
     ORDER BY c.start LIMIT $limit"""),
 "incident_calls_by_type": ("How many calls reference an incident, split by call type (support / external / internal). Counts are lower bounds: transcripts are excerpts.",
  {"incident_id": DEFAULT_INCIDENT},
  """MATCH (:Incident {id:$incident_id})<-[:RELATES_TO]-(c:Call)
     RETURN c.type AS call_type, count(c) AS calls, min(c.date) AS first_date, max(c.date) AS last_date, collect(c.id)[..5] AS call_ids
     ORDER BY calls DESC"""),
 "customer_outage_durations": ("Customer-facing (external/support) transcript excerpts about the outage that state a duration in hours or days, with account, date and the excerpt. Use for ANY 'how long' question: compare these customer-reported figures with the official figure.",
  {"incident_id": DEFAULT_INCIDENT},
  """MATCH (c:Call)-[:RELATES_TO]->(:Incident {id:$incident_id})
     WHERE c.type IN ['external', 'support']
     MATCH (ch:Chunk)-[:PART_OF]->(c)
     OPTIONAL MATCH (c)-[:ABOUT]->(a:Account)
     WITH c, a, ch WHERE ch.text =~ '(?si).*([0-9]+[+]? ?(hours?|hrs?|days?)|nine hours|twenty[- ]four hours|thirty[- ]six hours|fifteen hours|a full day|a day).*'
     RETURN coalesce(a.name, '(unknown account)') AS account, c.date AS date, c.title AS title, c.type AS call_type,
            substring(ch.text, 0, 700) AS excerpt
     ORDER BY date LIMIT 40"""),
 "account_brief": ("Account health brief for one account (name substring): number of calls, first/last call date and sentiment score, competitors mentioned, and excerpts about renewal, executives (CISO/CTO/VP), board or evaluation. Use for ANY 'brief' / 'account health' question.",
  {"account": "Northstar"},
  """MATCH (a:Account) WHERE toLower(a.name) CONTAINS toLower($account)
     MATCH (a)<-[:ABOUT]-(c:Call)
     WITH a, c ORDER BY c.date
     WITH a, collect(c) AS calls
     OPTIONAL MATCH (a)<-[:ABOUT]-(:Call)-[:MENTIONS]->(k:Competitor)
     WITH a, calls, collect(DISTINCT k.name) AS competitors
     OPTIONAL MATCH (a)<-[:ABOUT]-(:Call)<-[:PART_OF]-(ch:Chunk)
       WHERE ch.text =~ '(?si).*(renew|CISO|CIO|CTO|VP of|board|competitive evaluation|churn|cancel).*'
     WITH a, calls, competitors, collect(substring(ch.text, 0, 350))[..6] AS signal_excerpts
     RETURN a.name AS account, size(calls) AS calls, calls[0].date AS first_call, calls[size(calls)-1].date AS last_call,
            calls[0].sentiment_score AS first_score, calls[size(calls)-1].sentiment_score AS last_score,
            [x IN calls | x.date + ' ' + x.title][..10] AS call_list, competitors, signal_excerpts"""),
 "sentiment_change": ("Per account (2+ calls): first vs last call sentiment score and the change, biggest improvement first. Use for recovery/decline questions.",
  {"limit": 10},
  """MATCH (a:Account)<-[:ABOUT]-(c:Call) WITH a, c ORDER BY c.date
     WITH a, collect(c) AS cs WHERE size(cs) >= 2
     RETURN a.name AS account, cs[0].date AS first_date, cs[0].sentiment_score AS first_score,
            cs[-1].date AS last_date, cs[-1].sentiment_score AS last_score,
            round(cs[-1].sentiment_score - cs[0].sentiment_score, 1) AS change,
            [x IN cs | x.id] AS call_ids
     ORDER BY change DESC LIMIT $limit"""),
 "top_topics": ("Most common call topics, optionally for one call type (support/external/internal).",
  {"call_type": None},
  """MATCH (c:Call)-[:HAS_TOPIC]->(t:Topic) WHERE $call_type IS NULL OR c.type = $call_type
     RETURN t.name AS topic, count(c) AS calls ORDER BY calls DESC, topic LIMIT 15"""),
}

def graph_query(template, params=None):
    if template not in TEMPLATES:
        return {"error": f"unknown template '{template}'", "available": list(TEMPLATES)}
    _, defaults, cypher = TEMPLATES[template]
    p = {**defaults, **{k: v for k, v in (params or {}).items() if k in defaults}}
    with span("ti.graph_query", template=template) as s:
        rows = _run(cypher, **p)[:MAX_ROWS]
        set_attrs(s, rows=len(rows))
    return rows

# ---------- hybrid search ----------
_LUCENE = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')
def _lucene(q): return " ".join(_LUCENE.sub(r"\\\1", w) for w in q.split())

_FILTER = """MATCH (node)-[:PART_OF]->(call:Call)
  OPTIONAL MATCH (call)-[:ABOUT]->(a:Account)
  WITH node, call, a, score
  WHERE ($call_type IS NULL OR call.type = $call_type)
    AND ($account IS NULL OR toLower(a.name) CONTAINS toLower($account))
    AND ($date_from IS NULL OR call.date >= $date_from) AND ($date_to IS NULL OR call.date <= $date_to)
  RETURN node.id AS id, node.text AS text, node.first_turn AS first_turn, node.last_turn AS last_turn,
         call.id AS call_id, call.title AS title, call.date AS date, call.type AS call_type, a.name AS account, score
  ORDER BY score DESC LIMIT $n"""

def search_transcripts(query, k=6, account=None, call_type=None, date_from=None, date_to=None):
    global _oc
    _oc = _oc or openai_client()
    f = dict(call_type=call_type, account=account, date_from=date_from, date_to=date_to, n=30)
    with span("ti.search_transcripts", k=k, account=account, call_type=call_type, date_from=date_from, date_to=date_to) as top_span:
        with span("ti.search.embed"):
            qvec = embed(_oc, [query])[0]
        with span("ti.search.vector") as s:
            vec = _run("CALL db.index.vector.queryNodes('chunk_embedding', 100, $v) YIELD node, score\n" + _FILTER, v=qvec, **f)
            set_attrs(s, rows=len(vec))
        with span("ti.search.keyword") as s:
            kw = _run("CALL db.index.fulltext.queryNodes('chunk_text', $q, {limit: 100}) YIELD node, score\n" + _FILTER,
                      q=_lucene(query), **f)
            set_attrs(s, rows=len(kw))
        out = _fuse(vec, kw, k)
        set_attrs(top_span, hits=len(out))
    return out

def _fuse(vec, kw, k):
    scores, by_id = {}, {}
    for lst in (vec, kw):                      # reciprocal rank fusion
        for rank, r in enumerate(lst):
            by_id[r["id"]] = r
            scores[r["id"]] = scores.get(r["id"], 0) + 1 / (60 + rank)
    top = sorted(scores, key=lambda k: scores[k], reverse=True)[:k]
    out = []
    for cid in top:
        r = by_id[cid]; r.pop("score", None)
        r["rrf"] = round(scores[cid], 4)
        r["in_vector"] = any(x["id"] == cid for x in vec); r["in_keyword"] = any(x["id"] == cid for x in kw)
        r["citation"] = f'{r["title"]} ({r["date"]}), turns {r["first_turn"]}-{r["last_turn"]}'
        out.append(r)
    return out

def vector_search(query, k=6):
    """Baseline for evals: plain vector similarity only (no keyword, no filters, no graph)."""
    global _oc
    _oc = _oc or openai_client()
    rows = _run("CALL db.index.vector.queryNodes('chunk_embedding', $k, $v) YIELD node, score\n"
                "MATCH (node)-[:PART_OF]->(call:Call) OPTIONAL MATCH (call)-[:ABOUT]->(a:Account)\n"
                "RETURN node.text AS text, node.first_turn AS first_turn, node.last_turn AS last_turn, call.id AS call_id, "
                "call.title AS title, call.date AS date, call.type AS call_type, a.name AS account ORDER BY score DESC",
                v=embed(_oc, [query])[0], k=k)
    for r in rows: r["citation"] = f'{r["title"]} ({r["date"]}), turns {r["first_turn"]}-{r["last_turn"]}'
    return rows

# ---------- schemas for the agent (Step 4) ----------
def tool_specs():
    return [
     {"type": "function", "name": "graph_query",
      "description": "Run a vetted graph query for counts/relationships/time questions. Templates: " +
                     "; ".join(f"{n}: {d[0]}" for n, d in TEMPLATES.items()),
      "parameters": {"type": "object", "properties": {
          "template": {"type": "string", "enum": list(TEMPLATES)},
          "params": {"type": "object", "description": "Optional template parameters (see template defaults)"}},
          "required": ["template"]}},
     {"type": "function", "name": "search_transcripts",
      "description": "Hybrid semantic+keyword search over call transcript passages. Use for 'what did X say', evidence and quotes. Returns passages with citations.",
      "parameters": {"type": "object", "properties": {
          "query": {"type": "string"}, "k": {"type": "integer"},
          "account": {"type": "string", "description": "Account name substring filter"},
          "call_type": {"type": "string", "enum": ["support", "external", "internal"]},
          "date_from": {"type": "string"}, "date_to": {"type": "string"}}, "required": ["query"]}},
    ]
