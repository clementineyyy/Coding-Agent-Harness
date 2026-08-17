from pathlib import Path
from harness.credentials import CredentialStore

class FakeKeyring:
    def __init__(self): self.data = {}
    def get_password(self, service, user): return self.data.get((service, user))
    def set_password(self, service, user, pw): self.data[(service, user)] = pw
    def delete_password(self, service, user): self.data.pop((service, user), None)

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
