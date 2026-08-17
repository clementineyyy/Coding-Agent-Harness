import json
from pathlib import Path
from harness.hooks import HookBus
from harness import transcript

def test_order_and_observation():
    bus = HookBus(); seen = []
    bus.register("pre", lambda name, args: (seen.append(("pre", name)) or (args, True)))
    bus.register("post", lambda name, args, result: seen.append(("post", name)))
    args, ok = bus.pre_tool_use("bash", {"command": "ls"})
    bus.post_tool_use("bash", args, {"status": "ok"})
    assert seen == [("pre", "bash"), ("post", "bash")]

def test_hook_can_modify_args():
    bus = HookBus()
    bus.register("pre", lambda name, args: (dict(args, command="ls -la"), True))
    args, ok = bus.pre_tool_use("bash", {"command": "ls"})
    assert args["command"] == "ls -la"

def test_hook_exception_nonfatal():
    bus = HookBus()
    def bad(name, args): raise RuntimeError("boom")
    bus.register("pre", bad)
    args, ok = bus.pre_tool_use("bash", {})
    assert ok is True and len(bus.errors) == 1

def test_default_session_end_writes_transcript(tmp_path):
    bus = HookBus(transcript_dir=tmp_path)
    bus.session_end([{"role": "user", "content": "hi"}])
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["messages"][0]["content"] == "hi"
