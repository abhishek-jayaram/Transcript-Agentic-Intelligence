"""Usage: python -m ti.build_graph [--dry-run]   (run from ./src)"""
import argparse, collections, json, os, sys
from .parse import build_graph

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="write out/graph.json instead of loading Neo4j")
    a = ap.parse_args()
    nodes, rels = build_graph(f"{ROOT}/data/calls", f"{ROOT}/data/people.csv", f"{ROOT}/data/accounts.csv")
    print("nodes:", dict(collections.Counter(n["label"] for n in nodes)))
    print("rels :", dict(collections.Counter(r["type"] for r in rels)))
    if a.dry_run:
        os.makedirs(f"{ROOT}/out", exist_ok=True)
        json.dump({"nodes": nodes, "rels": [{**r, "from": list(r["from"]), "to": list(r["to"])} for r in rels]},
                  open(f"{ROOT}/out/graph.json", "w"))
        print("wrote out/graph.json"); return
    from dotenv import load_dotenv; from neo4j import GraphDatabase
    load_dotenv(f"{ROOT}/.env")
    drv = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]))
    with drv.session() as s:
        for lab in {n["label"] for n in nodes}:
            s.run(f"CREATE CONSTRAINT {lab.lower()}_id IF NOT EXISTS FOR (n:{lab}) REQUIRE n.id IS UNIQUE")
        for lab in {n["label"] for n in nodes}:
            rows = [{k: v for k, v in n.items() if k != "label" and v is not None} for n in nodes if n["label"] == lab]
            for i in range(0, len(rows), 500):
                s.run(f"UNWIND $rows AS r MERGE (n:{lab} {{id: r.id}}) SET n += r", rows=rows[i:i + 500])
        groups = collections.defaultdict(list)
        for r in rels: groups[(r["from"][0], r["type"], r["to"][0])].append({"a": r["from"][1], "b": r["to"][1]})
        for (fl, t, tl), rows in groups.items():
            for i in range(0, len(rows), 1000):
                s.run(f"UNWIND $rows AS r MATCH (a:{fl} {{id:r.a}}),(b:{tl} {{id:r.b}}) MERGE (a)-[:{t}]->(b)", rows=rows[i:i + 1000])
    print("loaded into Neo4j")

if __name__ == "__main__":
    main()
