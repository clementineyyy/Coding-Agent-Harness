import pytest
from harness.state import StateMachine, StateError, TRANSITIONS

def test_full_transition_table_coverage():
    spec_rows = [
        ("idle", "task_submitted", "running"),
        ("running", "tool_requested", "executing"),
        ("running", "approval_needed", "awaiting_user"),
        ("running", "agent_question", "awaiting_user"),
        ("running", "interrupt", "paused"),
        ("running", "final_answer", "completed"),
        ("executing", "tool_finished", "running"),
        ("executing", "interrupt", "paused"),
        ("executing", "abort", "terminated"),
        ("awaiting_user", "user_answered", "running"),
        ("awaiting_user", "abort", "terminated"),
        ("paused", "resume", "running"),
        ("paused", "abort", "terminated"),
        ("completed", "task_submitted", "running"),
        ("idle", "error", "running"),
        ("running", "error", "running"),
        ("executing", "error", "running"),
        ("awaiting_user", "error", "running"),
        ("paused", "error", "running"),
        ("completed", "error", "running"),
        ("terminated", "session_unavailable", "terminated"),
    ]
    for s, e, nxt in spec_rows:
        assert TRANSITIONS[(s, e)] == nxt, f"{s}+{e}"

def test_ask_cycle_with_history():
    m = StateMachine()
    m.fire("task_submitted", "user"); m.fire("approval_needed", "guardrail")
    assert m.state == "awaiting_user"
    m.fire("user_answered", "user"); assert m.state == "running"
    assert [h["event"] for h in m.event_history] == ["task_submitted", "approval_needed", "user_answered"]
    assert m.event_history[1]["source"] == "guardrail"

def test_illegal_transition_raises():
    m = StateMachine()
    with pytest.raises(StateError): m.fire("abort", "user")  # idle+abort 非法
    with pytest.raises(StateError): m.fire("tool_requested", "loop")  # idle+tool_requested 非法
