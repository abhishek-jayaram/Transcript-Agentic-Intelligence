"""python -m ti.diagnose   - finds exactly which stage of search breaks (embedding / vector index / full-text / full tool)."""
import sys, traceback
from .config import openai_client, neo4j_driver, embed, env, EMBED_DIM

def stage(name, fn):
    try:
        out = fn(); print(f"PASS  {name}  {out or ''}"); return True
    except Exception as e:
        print(f"FAIL  {name}: {type(e).__name__}: {e}")
        for a in ("status_code", "body", "request_id"):
            if getattr(e, a, None) is not None: print(f"        {a} = {getattr(e, a)}")
        resp = getattr(e, "response", None)
        if resp is not None:
            try: print("        response =", resp.text[:600])
            except Exception: pass
            try: print("        url      =", resp.request.url)
            except Exception: pass
        return False

print("endpoint :", env("FOUNDRY_PROJECT_ENDPOINT"))
print("chat     :", env("FOUNDRY_MODEL"))
print("embedding:", env("AZURE_AI_EMBEDDING_NAME"), "\n")
oc = openai_client()
stage("1 chat model reachable", lambda: oc.responses.create(model=env("FOUNDRY_MODEL"), input="say ok").output_text.strip())
ok = stage("2 embedding model reachable", lambda: f"{len(embed(oc, ['test'])[0])} dims (expected {EMBED_DIM})")
drv = neo4j_driver()
def q(cypher, **p):
    with drv.session(notifications_min_severity="OFF") as s: return s.run(cypher, **p).data()
stage("3 chunks have embeddings", lambda: q("MATCH (c:Chunk) RETURN count(c) AS total, count(c.embedding) AS embedded")[0])
# Queries live outside the f-strings: Python < 3.12 forbids backslashes inside f-string expressions.
VEC_Q = ('MATCH (c:Chunk) WHERE c.embedding IS NOT NULL WITH c LIMIT 1 '
         'CALL db.index.vector.queryNodes("chunk_embedding", 3, c.embedding) '
         'YIELD node RETURN node.id AS id')
FT_Q = 'CALL db.index.fulltext.queryNodes("chunk_text", "outage", {limit: 3}) YIELD node RETURN node.id AS id'
stage("4 vector index query (uses a stored vector, no API call)", lambda: f"{len(q(VEC_Q))} hits")
stage("5 full-text index query", lambda: f"{len(q(FT_Q))} hits")
from . import tools
stage("6 full search_transcripts()", lambda: f"{len(tools.search_transcripts('outage impact', k=3, account='Northstar'))} hits")