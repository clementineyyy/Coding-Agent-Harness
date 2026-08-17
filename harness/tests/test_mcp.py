import sys
import time
from pathlib import Path

import pytest

from harness.config import Config
from harness.mcp import MCPServer, load_mcp_servers
from harness.registry import make_registry
from harness.sandbox import LocalSandbox

FAKE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"

SILENT_CALL_SCRIPT = (
    "import json, sys\n"
    "for line in sys.stdin:\n"
    "    req = json.loads(line)\n"
    "    m = req.get('method')\n"
    "    if m == 'initialize':\n"
    "        print(json.dumps({'jsonrpc': '2.0', 'id': req.get('id'), 'result': "
    "{'protocolVersion': '2024-11-05', 'capabilities': {}, 'serverInfo': "
    "{'name': 'silent', 'version': '1'}}}), flush=True)\n"
    "    elif m == 'tools/list':\n"
    "        print(json.dumps({'jsonrpc': '2.0', 'id': req.get('id'), 'result': "
    "{'tools': [{'name': 'echo_tool', 'description': 'd', 'inputSchema': "
    "{'type': 'object', 'properties': {'text': {'type': 'string'}}}}]}}), flush=True)\n"
)


def stdio_cfg(name="demo"):
    return {"name": name, "type": "stdio", "command": sys.executable, "args": [str(FAKE)]}


def test_stdio_list_and_call(tmp_path):
    srv = MCPServer("demo", {"type": "stdio", "command": sys.executable, "args": [str(FAKE)]})
    assert srv.connect()
    tools = srv.list_tools()
    assert any(t["name"] == "echo_tool" for t in tools)
    res = srv.call("echo_tool", {"text": "mcp-ok"})
    assert "mcp-ok" in str(res)
    srv.close()


def test_connection_failure_disables_only_that_server(tmp_path):
    reg = make_registry([])
    cfg = Config(workspace=tmp_path,
                 mcp_servers=[{"name": "dead", "type": "stdio", "command": "does-not-exist-xyz"}])
    active = load_mcp_servers(cfg.mcp_servers, reg, LocalSandbox(), cfg)
    assert active == []


def test_load_registers_tools_and_forwards(tmp_path):
    reg = make_registry([])
    cfg = Config(workspace=tmp_path, mcp_servers=[stdio_cfg()])
    active = load_mcp_servers(cfg.mcp_servers, reg, LocalSandbox(), cfg)
    assert active == ["demo"]
    tool = reg["echo_tool"]
    assert tool.parameters["properties"]["text"]["type"] == "string"
    r = tool.handler({"text": "mcp-ok"}, None)
    assert r.status == "success" and "mcp-ok" in r.output


def test_handler_returns_error_when_server_dies(tmp_path):
    reg = make_registry([])
    cfg = Config(workspace=tmp_path, mcp_servers=[stdio_cfg()])
    load_mcp_servers(cfg.mcp_servers, reg, LocalSandbox(), cfg)
    first = reg["echo_tool"].handler({"text": "die"}, None)
    assert first.status == "success"
    r = reg["echo_tool"].handler({"text": "x"}, None)
    assert r.status == "error"


def test_url_transport_posts_jsonrpc(monkeypatch):
    sent = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"jsonrpc": "2.0", "id": sent["id"], "result": {"tools": [{"name": "url_tool"}]}}

    def fake_post(url, json=None, timeout=None):
        sent.update(json)
        return FakeResp()

    monkeypatch.setattr("harness.mcp.requests.post", fake_post)
    srv = MCPServer("urlsrv", {"type": "url", "url": "http://127.0.0.1:1/mcp"})
    assert srv.connect()
    assert sent["method"] == "initialize"
    tools = srv.list_tools()
    assert tools[0]["name"] == "url_tool"
    assert sent["method"] == "tools/list"
    res = srv.call("url_tool", {"text": "x"})
    assert sent["method"] == "tools/call"
    assert sent["params"]["name"] == "url_tool"
    assert sent["params"]["arguments"] == {"text": "x"}
    assert res["tools"][0]["name"] == "url_tool"
    srv.close()


def test_url_transport_http_error_connect_fails(monkeypatch):
    class FakeResp:
        status_code = 500

        def json(self):
            return {}

    monkeypatch.setattr("harness.mcp.requests.post",
                        lambda url, json=None, timeout=None: FakeResp())
    srv = MCPServer("badsrv", {"type": "url", "url": "http://127.0.0.1:1/mcp"})
    assert not srv.connect()


def test_init_timeout_disables_server(tmp_path):
    srv = MCPServer("silent-init", {"type": "stdio", "command": sys.executable,
                                    "args": ["-c", "import time; time.sleep(3600)"]},
                    init_timeout=0.3)
    start = time.monotonic()
    assert not srv.connect()
    assert time.monotonic() - start < 3.0
    srv.close()


def test_call_timeout_kills_proc_and_does_not_wedge(tmp_path):
    srv = MCPServer("silent-call", {"type": "stdio", "command": sys.executable,
                                    "args": ["-c", SILENT_CALL_SCRIPT]},
                    init_timeout=2.0, rpc_timeout=0.5)
    assert srv.connect()
    assert any(t["name"] == "echo_tool" for t in srv.list_tools())
    with pytest.raises(TimeoutError):
        srv.call("echo_tool", {"text": "x"})
    start = time.monotonic()
    with pytest.raises(RuntimeError):
        srv.call("echo_tool", {"text": "y"})
    assert time.monotonic() - start < 5.0
    srv.close()
