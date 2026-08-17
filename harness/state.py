from datetime import datetime


class StateError(Exception):
    pass


TRANSITIONS = {
    ("idle", "task_submitted"): "running",
    ("running", "tool_requested"): "executing",
    ("running", "approval_needed"): "awaiting_user",
    ("running", "agent_question"): "awaiting_user",
    ("running", "interrupt"): "paused",
    ("running", "final_answer"): "completed",
    ("executing", "tool_finished"): "running",
    ("executing", "interrupt"): "paused",
    ("executing", "abort"): "terminated",
    ("awaiting_user", "user_answered"): "running",
    ("awaiting_user", "abort"): "terminated",
    ("paused", "resume"): "running",
    ("paused", "abort"): "terminated",
    ("completed", "task_submitted"): "running",
    ("idle", "error"): "running",
    ("running", "error"): "running",
    ("executing", "error"): "running",
    ("awaiting_user", "error"): "running",
    ("paused", "error"): "running",
    ("completed", "error"): "running",
    ("idle", "session_unavailable"): "terminated",
    ("running", "session_unavailable"): "terminated",
    ("executing", "session_unavailable"): "terminated",
    ("awaiting_user", "session_unavailable"): "terminated",
    ("paused", "session_unavailable"): "terminated",
    ("completed", "session_unavailable"): "terminated",
    ("terminated", "session_unavailable"): "terminated",
}


class StateMachine:
    def __init__(self):
        self.state = "idle"
        self.event_history = []

    def fire(self, event: str, source: str) -> None:
        key = (self.state, event)
        if key not in TRANSITIONS:
            raise StateError(f"illegal transition: {self.state} + {event}")
        nxt = TRANSITIONS[key]
        self.event_history.append({
            "event": event,
            "source": source,
            "from": self.state,
            "to": nxt,
            "at": datetime.now().isoformat(),
        })
        self.state = nxt
