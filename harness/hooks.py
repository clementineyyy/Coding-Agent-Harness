from datetime import datetime
from typing import Callable

from harness.transcript import default_session_end_hook


class HookBus:
    def __init__(self, transcript_dir=None):
        self._hooks: dict[str, list[Callable]] = {}
        self._records: list[dict] = []
        self.errors: list[str] = []
        if transcript_dir is not None:
            self.register("session_end", default_session_end_hook(transcript_dir))

    def register(self, name: str, fn: Callable) -> None:
        self._hooks.setdefault(name, []).append(fn)

    def _record(self, hook_name: str, tool_name, args, result) -> None:
        self._records.append({
            "hook_name": hook_name,
            "tool_name": tool_name,
            "args": args,
            "result": result,
            "timestamp": datetime.now().isoformat(),
        })

    def pre_tool_use(self, tool_name: str, args: dict) -> tuple[dict, bool]:
        ok = True
        for hook in self._hooks.get("pre", []):
            try:
                args, flag = hook(tool_name, args)
                ok = ok and flag
                self._record("pre", tool_name, args, None)
            except Exception as exc:
                self.errors.append(f"pre_tool_use({tool_name}): {exc}")
        return args, ok

    def post_tool_use(self, tool_name: str, args: dict, result) -> None:
        for hook in self._hooks.get("post", []):
            try:
                hook(tool_name, args, result)
                self._record("post", tool_name, args, result)
            except Exception as exc:
                self.errors.append(f"post_tool_use({tool_name}): {exc}")

    def session_end(self, messages: list[dict]) -> None:
        for hook in self._hooks.get("session_end", []):
            try:
                hook(messages)
                self._record("session_end", None, None, None)
            except Exception as exc:
                self.errors.append(f"session_end: {exc}")

    def records(self) -> list[dict]:
        return self._records
