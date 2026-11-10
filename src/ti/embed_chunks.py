"""Step 2: embed Chunk nodes and create vector + full-text indexes.  python -m ti.embed_chunks
Idempotent: only embeds chunks that have no embedding yet."""
from .config import openai_client, neo4j_driver, embed, EMBED_DIM

BATCH = 64

def main():
    oc, drv = openai_client(), neo4j_driver()
    with drv.session() as s:
        assert EMBED_DIM == 1536, "update the dimension in the index query below"
        s.run("CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS FOR (c:Chunk) ON (c.embedding) "
              "OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}")
        s.run("CREATE FULLTEXT INDEX chunk_text IF NOT EXISTS FOR (c:Chunk) ON EACH [c.text]")
        todo = s.run("MATCH (c:Chunk) WHERE c.embedding IS NULL RETURN c.id AS id, c.text AS text").data()
        print(f"{len(todo)} chunks to embed")
        for i in range(0, len(todo), BATCH):
            b = todo[i:i + BATCH]
            vecs = embed(oc, [x["text"] for x in b])
            s.run("UNWIND $rows AS r MATCH (c:Chunk {id:r.id}) CALL db.create.setNodeVectorProperty(c,'embedding',r.v)",
                  rows=[{"id": x["id"], "v": v} for x, v in zip(b, vecs)])
            print(f"  embedded {min(i + BATCH, len(todo))}/{len(todo)}")
        s.run("CALL db.awaitIndexes(300)")
    print("done")

if __name__ == "__main__":
    main()
