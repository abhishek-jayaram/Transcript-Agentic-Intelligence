"""Which Azure identity is chosen. No Azure access needed.  Run:  pytest tests/test_credential.py"""
import importlib, os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
pytest.importorskip("azure.identity")
KEYS = ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET")

def cred():
    return importlib.import_module("ti.config").credential()

def test_uses_az_login_by_default(monkeypatch):
    for k in KEYS: monkeypatch.delenv(k, raising=False)
    assert type(cred()).__name__ == "AzureCliCredential"

def test_uses_service_principal_when_all_three_set(monkeypatch):
    for k in KEYS: monkeypatch.setenv(k, "x" * 8)
    assert type(cred()).__name__ == "ClientSecretCredential"

def test_partial_settings_fall_back_to_az_login(monkeypatch):
    for k in KEYS: monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AZURE_CLIENT_ID", "only-one")
    assert type(cred()).__name__ == "AzureCliCredential"
