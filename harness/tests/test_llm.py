import json

import pytest

from harness.fake_llm import FakeLLM, FakeTurn
from harness.llm import LLMAuthError, LLMRateLimitError, OpenAILLM


def sse_handler(payload):
    def handler(request):
        import httpx
        lines = (
            "\n\n".join(f"data: {json.dumps(c)}" for c in payload)
            + "\n\ndata: [DONE]\n\n"
        )
        return httpx.Response(
            200, text=lines, headers={"Content-Type": "text/event-stream"}
        )

    return handler


def test_fake_llm_scripted():
    llm = FakeLLM(
        [
            FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "ls"}}]),
            FakeTurn(text="final"),
        ]
    )
    r1 = llm.complete([], [])
    r2 = llm.complete([], [])
    assert r1.tool_calls[0]["name"] == "bash"
    assert r2.text == "final" and r2.tool_calls == []


def test_openai_streaming_and_tool_calls():
    import httpx

    payload = [
        {"choices": [{"delta": {"content": "思考中"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "c1", "function": {"name": "bash", "arguments": ""}}
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"comm'}}]}}
            ]
        },
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'and": "ls"}'}}]}}
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]
    client = httpx.Client(transport=httpx.MockTransport(sse_handler(payload)))
    llm = OpenAILLM("test-key", http_client=client)
    r = llm.complete([{"role": "user", "content": "x"}], [])
    assert "思考中" in r.text
    assert r.tool_calls == [{"name": "bash", "arguments": {"command": "ls"}}]
    assert r.usage["approx_tokens"] >= 1


def test_auth_error_mapping():
    import httpx

    def handler(request):
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    llm = OpenAILLM(
        "bad", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(LLMAuthError):
        llm.complete([], [])


def test_rate_limit_retries_once_then_raises(monkeypatch):
    import httpx

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429, json={"error": {"message": "slow"}})

    monkeypatch.setattr("harness.llm.RETRY_BACKOFF", 0.0)
    llm = OpenAILLM("k", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LLMRateLimitError):
        llm.complete([], [])
    assert calls["n"] == 2
