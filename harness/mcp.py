"""MCP 客户端（手写 JSON-RPC 2.0，非 SDK）。

- stdio 服务器：subprocess.Popen + 逐行 JSON-RPC（initialize → tools/list → tools/call）
- url 服务器：requests.post 同样 JSON-RPC
- 连接失败 / 超时 → 该服务器优雅停用，不阻塞其余服务器（spec §4.3 / §11.2）

实现偏差：spec §4.3 原计划用官方 Python SDK，v1 改为手写轻量协议（更可测试、零网络依赖）。
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import warnings

import requests

from harness.registry import Tool, ToolResult

PROTOCOL_VERSION = "2024-11-05"
INIT_TIMEOUT = 3.0
RPC_TIMEOUT = 30.0


class MCPServer:
    def __init__(
        self,
        name: str,
        cfg: dict,
        init_timeout: float = INIT_TIMEOUT,
        rpc_timeout: float = RPC_TIMEOUT,
    ):
        self.name = name
        self.cfg = cfg
        self.tools: list[dict] = []
        self._proc: subprocess.Popen | None = None
        self._connected = False
        self._seq = 0
        self._init_timeout = init_timeout
        self._rpc_timeout = rpc_timeout

    def connect(self) -> bool:
        try:
            if self.cfg.get("type") == "url":
                self._rpc("initialize", _client_info(), self._init_timeout)
            else:
                self._spawn_stdio()
                self._rpc("initialize", _client_info(), self._init_timeout)
            self._connected = True
            return True
        except Exception as exc:
            warnings.warn(f"MCP 服务器 {self.name} 连接失败: {exc}")
            self.close()
            return False

    def list_tools(self) -> list[dict]:
        result = self._rpc("tools/list", {}, self._rpc_timeout)
        tools = result.get("tools", [])
        self.tools = tools
        return tools

    def call(self, name: str, args: dict) -> dict:
        return self._rpc("tools/call", {"name": name, "arguments": args}, self._rpc_timeout)

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=1)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._connected = False

    def _spawn_stdio(self) -> None:
        command = self.cfg.get("command")
        if not command:
            raise RuntimeError(f"MCP {self.name}: stdio 配置缺少 command")
        args = list(self.cfg.get("args") or [])
        self._proc = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def _rpc(self, method: str, params: dict, timeout: float) -> dict:
        if not self._connected and method != "initialize":
            raise RuntimeError(f"MCP {self.name} 未连接")
        if self.cfg.get("type") == "url":
            return self._rpc_url(method, params, timeout)
        return self._rpc_stdio(method, params, timeout)

    def _rpc_url(self, method: str, params: dict, timeout: float) -> dict:
        self._seq += 1
        resp = requests.post(self.cfg["url"], json=_request(self._seq, method, params), timeout=timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"MCP {self.name}: HTTP {resp.status_code}")
        return _unwrap(resp.json())

    def _rpc_stdio(self, method: str, params: dict, timeout: float) -> dict:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            raise RuntimeError(f"MCP {self.name}: stdio 进程已退出")
        self._seq += 1
        proc.stdin.write(json.dumps(_request(self._seq, method, params), ensure_ascii=False) + "\n")
        proc.stdin.flush()
        try:
            line = _read_line(proc, self.name, timeout)
        except TimeoutError:
            self._teardown(proc)
            raise
        return _unwrap(json.loads(line))

    def _teardown(self, proc: subprocess.Popen) -> None:
        """读超时后终止子进程并标记未连接。

        不这样做时，被阻塞在 readline 的 reader 线程会一直持有管道读锁，
        使该服务器后续所有调用都永久卡死并泄漏线程。
        """
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=1)
        except Exception:
            pass
        self._connected = False


def load_mcp_servers(server_cfgs: list[dict], registry: dict, sandbox, config) -> list[str]:
    """连接并注册各 MCP 服务器工具；失败的服务器警告并跳过，返回激活的服务器名列表。"""
    active: list[str] = []
    for cfg in server_cfgs:
        name = cfg.get("name", "mcp")
        server = MCPServer(name, cfg)
        if not server.connect():
            warnings.warn(f"MCP 服务器 {name} 连接失败，已停用")
            continue
        try:
            tools = server.list_tools()
        except Exception as exc:
            warnings.warn(f"MCP 服务器 {name} 工具列表失败，已停用: {exc}")
            server.close()
            continue
        for decl in tools:
            tool_name = decl.get("name") if isinstance(decl, dict) else None
            if not tool_name or tool_name in registry:
                continue
            registry[tool_name] = Tool(
                name=tool_name,
                description=decl.get("description", ""),
                parameters=_input_schema(decl),
                requires_approval=True,
                needs_sandbox=False,
                uses_workspace=False,
                handler=_forward_handler(server, tool_name),
            )
        active.append(name)
    return active


def _forward_handler(server: MCPServer, tool_name: str):
    def handler(args: dict, ctx) -> ToolResult:
        try:
            result = server.call(tool_name, args)
        except Exception as exc:
            return ToolResult(status="error", error=f"MCP {server.name} {tool_name} 调用失败: {exc}")
        return ToolResult(status="success", output=_content_text(result))
    return handler


def _content_text(result: dict) -> str:
    content = result.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
        if parts:
            return "\n".join(parts)
    return json.dumps(result, ensure_ascii=False)


def _input_schema(decl: dict) -> dict:
    schema = decl.get("inputSchema")
    if isinstance(schema, dict) and schema.get("type") == "object":
        return schema
    return {"type": "object", "properties": {}, "required": []}


def _request(rpc_id: int, method: str, params: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}


def _client_info() -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "harness", "version": "0.1.0"},
    }


def _unwrap(body: dict) -> dict:
    if not isinstance(body, dict):
        raise RuntimeError(f"非 JSON-RPC 响应: {body!r}")
    if "error" in body:
        err = body["error"]
        message = err.get("message") if isinstance(err, dict) else str(err)
        raise RuntimeError(f"JSON-RPC 错误: {message}")
    if "result" not in body:
        raise RuntimeError(f"JSON-RPC 响应缺少 result: {body!r}")
    return body["result"]


def _read_line(proc: subprocess.Popen, name: str, timeout: float) -> str:
    q: queue.Queue = queue.Queue()

    def _reader():
        try:
            q.put(proc.stdout.readline())
        except Exception as exc:
            q.put(exc)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    try:
        item = q.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError(f"MCP {name}: 等待响应超时 ({timeout}s)")
    if isinstance(item, Exception):
        raise item
    return item
