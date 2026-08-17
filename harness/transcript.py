import json
from datetime import datetime
from pathlib import Path


def write_transcript(
    path: Path,
    messages: list[dict],
    tool_calls: list[dict],
    policy_changes: list[dict],
) -> None:
    data = {
        "messages": messages,
        "tool_calls": tool_calls,
        "policy_changes": policy_changes,
        "written_at": datetime.now().isoformat(),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def default_session_end_hook(transcript_dir: Path):
    def hook(messages: list[dict]) -> None:
        path = transcript_dir / f"{datetime.now().strftime('%Y-%m-%dT%H-%M-%S-%f')}.json"
        write_transcript(path, messages, [], [])

    return hook
