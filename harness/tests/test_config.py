from pathlib import Path
from harness.config import Config

def test_defaults(tmp_path):
    c = Config.load(None)
    assert c.model == "deepseek-chat"
    assert c.max_steps == 50 and c.failure_budget == 3 and c.tool_timeout == 30

def test_toml_override(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("model = \"deepseek-reasoner\"\nmax_steps = 12\n", encoding="utf-8")
    c = Config.load(p)
    assert c.model == "deepseek-reasoner" and c.max_steps == 12
    assert c.tool_timeout == 30  # 未覆盖的保持默认

def test_mcp_servers_parsed(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[[mcp_servers]]\nname = "demo"\ntype = "stdio"\ncommand = "python"\n', encoding="utf-8")
    c = Config.load(p)
    assert c.mcp_servers == [{"name": "demo", "type": "stdio", "command": "python"}]


def test_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-ai/DeepSeek-V3")
    c = Config.load(None)
    assert c.base_url == "https://api.siliconflow.cn/v1"
    assert c.model == "deepseek-ai/DeepSeek-V3"


def test_env_file_overrides_defaults(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEEPSEEK_BASE_URL=https://api.example.com/v1\nDEEPSEEK_MODEL=example-model\n",
        encoding="utf-8",
    )
    c = Config.load(None, env_file=str(env_file))
    assert c.base_url == "https://api.example.com/v1"
    assert c.model == "example-model"


def test_os_environ_wins_over_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_MODEL=from-file\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_MODEL", "from-env")
    c = Config.load(None, env_file=str(env_file))
    assert c.model == "from-env"


def test_toml_wins_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL", "from-env")
    p = tmp_path / "config.toml"
    p.write_text('model = "from-toml"\n', encoding="utf-8")
    c = Config.load(p)
    assert c.model == "from-toml"


def test_env_base_url_trailing_slash_stripped(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.example.com/v1/")
    c = Config.load(None)
    assert c.base_url == "https://api.example.com/v1"


def test_env_file_tolerates_bom(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("\ufeffDEEPSEEK_MODEL=model-from-bom\n", encoding="utf-8")
    c = Config.load(None, env_file=str(env_file))
    assert c.model == "model-from-bom"