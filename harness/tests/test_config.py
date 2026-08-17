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