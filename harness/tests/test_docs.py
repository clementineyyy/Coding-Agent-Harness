from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_commands_match_implementation():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    main = (ROOT / "harness" / "main.py").read_text(encoding="utf-8")
    for cmd in ["/exit", "/reset", "/skills", "/rules", "/key", "/memory"]:
        assert cmd in readme, f"README 缺少 {cmd}"
        assert cmd in main, f"main.py 缺少 {cmd}"


def test_component_docs_exist():
    assert (ROOT / "docs" / "superpowers" / "specs" / "SPEC.md").exists()


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


def test_gitlab_ci_has_unit_test_job():
    gitlab = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    assert "unit-test:" in gitlab, ".gitlab-ci.yml 缺少 unit-test job"
    assert "pytest harness/tests" in gitlab


def test_readme_documents_env_config_override():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "DEEPSEEK_BASE_URL" in readme, "README 未文档化 DEEPSEEK_BASE_URL"
    assert "DEEPSEEK_MODEL" in readme, "README 未文档化 DEEPSEEK_MODEL"


def test_console_script_cah_declared():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert 'cah = "harness.main:main"' in pyproject, "pyproject 缺少 [project.scripts] cah"
    assert "cah" in readme, "README 未提 cah 入口命令"
