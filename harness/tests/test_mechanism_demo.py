import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).parent / "mechanism_demo"


def run_demo(name):
    return subprocess.run(
        [sys.executable, "-m", "harness.tests.mechanism_demo." + name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def test_demo_1_guardrail_deny():
    r = run_demo("demo_1_guardrail_deny")
    assert r.returncode == 0 and "denied" in r.stdout


def test_demo_2_feedback_change():
    r = run_demo("demo_2_feedback_change")
    assert r.returncode == 0 and "changed" in r.stdout


def test_demo_3_hitl_trace():
    r = run_demo("demo_3_hitl_trace")
    assert r.returncode == 0 and "TRACE OK" in r.stdout
