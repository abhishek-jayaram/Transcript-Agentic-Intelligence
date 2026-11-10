import logging, os
from functools import lru_cache
from dotenv import load_dotenv
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(ROOT, ".env"))

def env(k):
    v = os.environ.get(k)
    if not v: raise SystemExit(f"Missing {k} in .env")
    return v

EMBED_DIM = 1536  # text-embedding-3-small

def credential():
    """Which Azure identity the agents use. In Docker / Kubernetes set AZURE_TENANT_ID, AZURE_CLIENT_ID and
    AZURE_CLIENT_SECRET (a service principal). Otherwise it is your own `az login`, exactly as before."""
    from azure.identity import AzureCliCredential, ClientSecretCredential
    keys = ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET")
    if all(os.environ.get(k) for k in keys):
        return ClientSecretCredential(*(os.environ[k] for k in keys))
    return AzureCliCredential()

def openai_client():
    """OpenAI client authenticated against the Foundry project (uses `az login`)."""
    from azure.identity import DefaultAzureCredential
    from azure.ai.projects import AIProjectClient
    proj = AIProjectClient(endpoint=env("FOUNDRY_PROJECT_ENDPOINT"), credential=DefaultAzureCredential())
    return proj.get_openai_client()

def neo4j_driver():
    # Belt-and-braces: the driver logs server notifications via logging.getLogger("neo4j.notifications"),
    # so raise its level too. The actual fix is notifications_min_severity="OFF" on the *session* (not the
    # driver) - see neo4j_driver usage in tools.py.
    from neo4j import GraphDatabase
    logging.getLogger("neo4j.notifications").setLevel(logging.CRITICAL)
    auth = (env("NEO4J_USERNAME"), env("NEO4J_PASSWORD"))
    return GraphDatabase.driver(env("NEO4J_URI"), auth=auth)

@lru_cache(maxsize=1)
def _embed_client():
    """Azure OpenAI client on the deployment path. The project's /openai/v1/embeddings route returns 404
    for this deployment, while the direct deployment path works (verified)."""
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI
    base = env("FOUNDRY_PROJECT_ENDPOINT").split("/api/projects")[0]
    tok = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
    return AzureOpenAI(azure_endpoint=base, api_version="2024-10-21", azure_ad_token_provider=tok)

def embed(client, texts):
    """`client` is kept for call-site compatibility; embeddings go through _embed_client()."""
    r = _embed_client().embeddings.create(model=env("AZURE_AI_EMBEDDING_NAME"), input=texts)
    return [d.embedding for d in r.data]
