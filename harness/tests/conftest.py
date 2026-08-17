import pytest
from harness.config import Config


@pytest.fixture
def tmp_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def session_config(tmp_workspace):
    return Config(workspace=tmp_workspace, tool_timeout=1)