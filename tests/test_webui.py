import pytest
from fastapi.testclient import TestClient

from hipaa_bridge.config import BridgeConfig
from hipaa_bridge.proxy import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # config.save() writes to cwd
    config = BridgeConfig(vault_path=str(tmp_path / "vault.db"), use_ner=False)
    app = create_app(vault_path=tmp_path / "vault.db", use_ner=False, config=config)
    return TestClient(app)


def test_index_serves_ui(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "HIPAA-Bridge" in r.text


def test_config_roundtrip(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    assert r.json()["setup_complete"] is False

    r = client.post("/api/config", json={"mode": "ollama"})
    assert r.json()["ok"] is True
    assert client.get("/api/config").json()["setup_complete"] is True


def test_scrub_endpoint(client):
    r = client.post("/api/scrub", json={"text": "Patient John Doe, MRN: 1234567."})
    body = r.json()
    assert "John Doe" not in body["text"]
    assert body["count"] == 2
    # replacements expose category+token only — never the original value
    assert all(set(item) == {"category", "token"} for item in body["replacements"])


def test_restore_endpoint(client):
    scrubbed = client.post("/api/scrub", json={"text": "Patient John Doe admitted."}).json()
    restored = client.post("/api/restore", json={"text": scrubbed["text"]}).json()
    assert restored["text"] == "Patient John Doe admitted."


def test_ask_blocked_in_scrub_only_mode(client):
    r = client.post("/api/ask", json={"text": "anything"})
    assert r.status_code == 400


def test_audit(client):
    client.post("/api/scrub", json={"text": "Patient John Doe, MRN: 1234567."})
    body = client.get("/api/audit").json()
    assert body["total"] == 2
    assert body["categories"]["PATIENT"] == 1
