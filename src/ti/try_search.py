"""Quick look at retrieval: python -m ti.try_search "which customers mentioned SentinelShield?" """
import sys
from .config import openai_client, neo4j_driver, embed
q = " ".join(sys.argv[1:]) or "customer threatening to leave after the outage"
v = embed(openai_client(), [q])[0]
with neo4j_driver().session() as s:
    rows = s.run("""CALL db.index.vector.queryNodes('chunk_embedding', 5, $v) YIELD node, score
        MATCH (node)-[:PART_OF]->(call:Call)
        RETURN round(score,3) AS score, call.title AS call, call.date AS date, node.first_turn AS turn, substring(node.text,0,220) AS text""", v=v).data()
for r in rows: print(f"\n[{r['score']}] {r['date']} {r['call']} (turn {r['turn']})\n  {r['text']}")
