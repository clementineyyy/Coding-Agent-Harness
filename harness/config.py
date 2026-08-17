from __future__ import annotations

import tomllib
import warnings
from dataclasses import dataclass, field, fields
from pathlib import Path


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
    def load(cls, path: Path | None = None) -> Config:
        cfg = cls()
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