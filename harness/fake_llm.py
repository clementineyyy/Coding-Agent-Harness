from __future__ import annotations

from dataclasses import dataclass

from harness.llm import LLM, LLMResult


@dataclass
class FakeTurn:
    text: str = ""
    tool_calls: list[dict] | None = None
    usage_approx: int = 10


class FakeLLM(LLM):
    """脚本化 LLM：按序重放 turns，耗尽后重放最后一个；绝无网络。"""

    def __init__(self, turns: list[FakeTurn]):
        self.turns = list(turns)
        self.calls = 0
        self.turn_index = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResult:
        self.calls += 1
        if not self.turns:
            return LLMResult(text="", tool_calls=[], usage={"approx_tokens": 0})
        index = min(self.turn_index, len(self.turns) - 1)
        self.turn_index += 1
        turn = self.turns[index]
        return LLMResult(
            text=turn.text,
            tool_calls=turn.tool_calls or [],
            usage={"approx_tokens": turn.usage_approx},
        )
