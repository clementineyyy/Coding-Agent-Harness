from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_commands_match_implementation():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    main = (ROOT / "harness" / "main.py").read_text(encoding="utf-8")
    for cmd in ["/exit", "/reset", "/skills", "/rules", "/key", "/memory"]:
        assert cmd in readme, f"README 缺少 {cmd}"
        assert cmd in main, f"main.py 缺少 {cmd}"


def test_component_docs_exist():
    assert (ROOT / "docs" / "COMPONENTS.md").exists()


def test_readme_command_table_matches_help_text():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    main = (ROOT / "harness" / "main.py").read_text(encoding="utf-8")
    for fragment in ["/exit", "/reset", "/skills", "/rules", "/rules drop skill:",
                     "/key set", "/key status", "/key clear", "/memory", "/help"]:
        assert fragment in readme, f"README 命令表缺少 {fragment}"
    assert '"/exit /reset /skills /rules [/rules drop skill:<name>] "' in main
    assert '"/key set|status|clear /memory"' in main


def test_readme_security_and_sandbox_notes():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for fragment in ["keyring", ".env", "非隔离", "Docker"]:
        assert fragment in readme, f"README 缺少安全/沙箱说明: {fragment}"


def test_makefile_has_test_target():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "test:" in makefile and "pytest" in makefile


def test_ci_workflow_exists_and_runs_tests():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pytest" in ci and "actions/checkout" in ci and "upload-artifact" in ci
