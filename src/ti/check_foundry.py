"""Smoke test: python -m ti.check_foundry   (run `az login` first)"""
from .config import openai_client, embed, env, EMBED_DIM
c = openai_client()
r = c.responses.create(model=env("FOUNDRY_MODEL"), input="Reply with the single word: ready")
print("chat     :", r.output_text.strip())
v = embed(c, ["churn signal after outage"])[0]
print("embedding:", len(v), "dims", "OK" if len(v) == EMBED_DIM else f"MISMATCH (expected {EMBED_DIM})")
