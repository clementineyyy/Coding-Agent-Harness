from __future__ import annotations

import os
import tomllib
import warnings
from dataclasses import dataclass, field, fields
from pathlib import Path

_ENV_BASE_URL = "DEEPSEEK_BASE_URL"
_ENV_MODEL = "DEEPSEEK_MODEL"


def _read_env_file(path: str) -> dict[str, str]:
    values = {}
    p = Path(path)
    if not p.exists():
        return values
    try:
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                if key.strip():
                    values[key.strip()] = value.strip()
    except Exception:
        return values
    return values


@dataclass
class Config:
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    max_steps: int = 50
    failure_budget: int = 3
    tool_timeout: int = 30
    memory_top_k: int = 2
    max_budget_tokens: int = 6000
    compression_keep_turns: int = 10
    compression_max_rounds: int = 3
    workspace: Path = field(default_factory=Path.cwd)
    max_output_bytes: int = 51200
    mcp_servers: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None, env_file: str = ".env") -> Config:
        cfg = cls()
        env = _read_env_file(env_file)
        env.update({k: v for k, v in os.environ.items() if k in (_ENV_BASE_URL, _ENV_MODEL) and v})
        if env.get(_ENV_BASE_URL):
            cfg.base_url = env[_ENV_BASE_URL].rstrip("/")
        if env.get(_ENV_MODEL):
            cfg.model = env[_ENV_MODEL]
        if path is None:
            return cfg
        path = Path(path)
        if not path.exists():
            return cfg
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except Exception as exc:
            warnings.warn(f"config 解析失败，使用默认值: {exc}")
            return cfg
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key not in known:
                continue
            if key == "workspace":
                value = Path(value)
            setattr(cfg, key, value)
        return cfg