"""假 MCP stdio 服务器：逐行读 JSON-RPC 2.0 请求，应答 initialize / tools/list / tools/call。

仅供测试（离线）；text == "die" 时应答后退出，模拟服务器中途死亡。
"""

import json
import sys


def _write(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        if not line:
            return
        try:
            req = json.loads(line)
        except ValueError:
            continue
        method = req.get("method")
        rpc_id = req.get("id")
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake_mcp", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "echo_tool",
                        "description": "回显文本",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    }
                ]
            }
        elif method == "tools/call":
            params = req.get("params") or {}
            args = params.get("arguments") or {}
            text = args.get("text", "")
            _write({"jsonrpc": "2.0", "id": rpc_id,
                    "result": {"content": [{"type": "text", "text": text}]}})
            if text == "die":
                return
            continue
        else:
            _write({"jsonrpc": "2.0", "id": rpc_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"}})
            continue
        _write({"jsonrpc": "2.0", "id": rpc_id, "result": result})


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    main()
