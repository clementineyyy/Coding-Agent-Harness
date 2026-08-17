from __future__ import annotations

import getpass
from pathlib import Path

_ENV_KEY = "DEEPSEEK_API_KEY"


class CredentialStore:
    def __init__(self, service: str = "coding-agent-harness", env_file: str = ".env", keyring_backend=None):
        self.service = service
        self.env_file = Path(env_file)
        self._keyring = keyring_backend
        if self._keyring is None:
            try:
                import keyring
                self._keyring = keyring.get_keyring()
            except Exception:
                self._keyring = None

    def _keyring_get(self, user: str) -> str | None:
        if self._keyring is None:
            return None
        try:
            return self._keyring.get_password(self.service, user)
        except Exception:
            return None

    def _env_value(self) -> str | None:
        try:
            if not self.env_file.exists():
                return None
            for line in self.env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(_ENV_KEY + "="):
                    value = line[len(_ENV_KEY) + 1:].strip()
                    if value:
                        return value
        except Exception:
            return None
        return None

    def get(self) -> str | None:
        key = self._keyring_get("api_key")
        if key:
            return key
        return self._env_value()

    def set(self, key: str) -> None:
        if self._keyring is None:
            return
        try:
            self._keyring.set_password(self.service, "api_key", key)
        except Exception:
            pass

    def clear(self) -> None:
        if self._keyring is None:
            return
        try:
            self._keyring.delete_password(self.service, "api_key")
        except Exception:
            pass

    def verified_at(self) -> str | None:
        return self._keyring_get("verified_at")

    def status(self) -> dict:
        if self._keyring_get("api_key"):
            source = "keyring"
        elif self._env_value():
            source = "env"
        else:
            source = None
        return {
            "configured": source is not None,
            "source": source,
            "verified_at": self.verified_at(),
        }


def wizard_enter_key() -> str:
    key = getpass.getpass("请粘贴 API Key（输入不可见）: ")
    if not key:
        raise ValueError("API Key 不能为空")
    return key
