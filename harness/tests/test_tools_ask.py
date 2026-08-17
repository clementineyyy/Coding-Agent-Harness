from harness.config import Config
from harness.registry import Context, make_registry
from harness.sandbox import LocalSandbox
from harness.state import StateMachine
from harness.tools.ask import spec as ask_spec


def ctx(ws, state, cb):
    return Context(workspace=ws, sandbox=LocalSandbox(), hooks=None, policy=None,
                   state=state, memory=None, config=Config(workspace=ws), ask_callback=cb)


def running_state():
    m = StateMachine()
    m.fire("task_submitted", "user")
    return m


def test_ask_menu_cycle(tmp_path):
    m = running_state()
    answers = []

    def cb(question, options):
        answers.append((question, options))
        return options[1]

    reg = make_registry([ask_spec()])
    r = reg["ask_user"].handler({"question": "选哪个?", "options": ["A", "B"]}, ctx(tmp_path, m, cb))
    assert r.status == "success" and "B" in r.output
    assert answers[0][0] == "选哪个?"
    assert [h["event"] for h in m.event_history[-2:]] == ["agent_question", "user_answered"]
    assert m.state == "running"


def test_ask_no_callback_returns_error(tmp_path):
    m = running_state()
    reg = make_registry([ask_spec()])
    r = reg["ask_user"].handler({"question": "选哪个?", "options": ["A", "B"]}, ctx(tmp_path, m, None))
    assert r.status == "error"
    assert m.state == "running"


def test_ask_callback_raises_cancels_and_releases(tmp_path):
    m = running_state()

    def cb(question, options):
        raise RuntimeError("user pressed ctrl-c")

    reg = make_registry([ask_spec()])
    r = reg["ask_user"].handler({"question": "选哪个?", "options": ["A", "B"]}, ctx(tmp_path, m, cb))
    assert r.status == "error" and r.error == "ask cancelled"
    assert m.state == "running"
    assert [h["event"] for h in m.event_history[-2:]] == ["agent_question", "user_answered"]
