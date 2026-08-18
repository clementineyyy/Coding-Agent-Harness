import httpx
import pytest
from pathlib import Path
from harness.credentials import CredentialStore, verify_api_key

class FakeKeyring:
    def __init__(self): self.data = {}
    def get_password(self, service, user): return self.data.get((service, user))
    def set_password(self, service, user, pw): self.data[(service, user)] = pw
    def delete_password(self, service, user): self.data.pop((service, user), None)

class FailingKeyring(FakeKeyring):
    def set_password(self, service, user, pw): raise RuntimeError("no credential service")
    def delete_password(self, service, user): raise RuntimeError("no credential service")

def test_priority_keyring_over_env(tmp_path):
    kr = FakeKeyring(); kr.set_password("coding-agent-harness", "api_key", "sk-keyring")
    env = tmp_path / ".env"; env.write_text("DEEPSEEK_API_KEY=sk-env\n", encoding="utf-8")
    cs = CredentialStore(env_file=str(env), keyring_backend=kr)
    assert cs.get() == "sk-keyring"
    assert cs.status()["source"] == "keyring"

def test_fallback_env(tmp_path):
    env = tmp_path / ".env"; env.write_text("DEEPSEEK_API_KEY=sk-env\n", encoding="utf-8")
    cs = CredentialStore(env_file=str(env), keyring_backend=FakeKeyring())
    assert cs.get() == "sk-env"
    assert cs.status()["source"] == "env"

def test_status_never_echoes_plaintext(tmp_path):
    env = tmp_path / ".env"; env.write_text("DEEPSEEK_API_KEY=sk-secret\n", encoding="utf-8")
    cs = CredentialStore(env_file=str(env), keyring_backend=FakeKeyring())
    status_str = str(cs.status())
    assert "sk-secret" not in status_str
    assert cs.status()["configured"] is True

def test_set_clear_roundtrip(tmp_path):
    kr = FakeKeyring()
    env = tmp_path / ".env"; env.write_text("DEEPSEEK_API_KEY=sk-env\n", encoding="utf-8")
    cs = CredentialStore(env_file=str(env), keyring_backend=kr)
    cs.set("sk-new")
    assert kr.data[("coding-agent-harness", "api_key")] == "sk-new"
    assert cs.get() == "sk-new"
    assert cs.status()["source"] == "keyring"
    cs.clear()
    assert ("coding-agent-harness", "api_key") not in kr.data
    assert cs.get() == "sk-env"

def test_verified_at(tmp_path):
    kr = FakeKeyring()
    cs = CredentialStore(env_file=str(tmp_path / ".env"), keyring_backend=kr)
    assert cs.verified_at() is None
    assert cs.status()["verified_at"] is None
    kr.set_password("coding-agent-harness", "verified_at", "2026-08-15T12:00:00")
    assert cs.verified_at() == "2026-08-15T12:00:00"
    assert cs.status()["verified_at"] == "2026-08-15T12:00:00"

def test_set_clear_raise_when_keyring_call_fails():
    kr = FailingKeyring()
    cs = CredentialStore(env_file=".env", keyring_backend=kr)
    with pytest.raises(RuntimeError):
        cs.set("sk-x")
    with pytest.raises(RuntimeError):
        cs.clear()

def test_set_raises_when_keyring_unavailable(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "keyring", None)
    cs = CredentialStore(env_file=".env")
    with pytest.raises(RuntimeError):
        cs.set("sk-x")

def test_wizard_rejects_whitespace(monkeypatch):
    import harness.credentials as creds
    monkeypatch.setattr(creds.getpass, "getpass", lambda prompt: "   ")
    with pytest.raises(ValueError):
        creds.wizard_enter_key()


def test_verify_api_key_success():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": [{"id": "deepseek-chat"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert verify_api_key("https://api.example.com", "sk-live", http_client=client) is True
    assert seen["path"] == "/models"
    assert seen["auth"] == "Bearer sk-live"


def test_verify_api_key_rejects_401():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "bad key"})))
    assert verify_api_key("https://api.example.com", "sk-bad", http_client=client) is False


def test_verify_api_key_network_error_false():
    def boom(request):
        raise httpx.ConnectError("connection refused")

    client = httpx.Client(transport=httpx.MockTransport(boom))
    assert verify_api_key("https://api.example.com", "sk-x", http_client=client) is False


def test_mark_verified_records_timestamp(tmp_path):
    kr = FakeKeyring()
    cs = CredentialStore(env_file=str(tmp_path / ".env"), keyring_backend=kr)
    cs.set("sk-x")
    cs.mark_verified()
    assert cs.status()["verified_at"] is not None
    assert cs.status()["source"] == "keyring"
