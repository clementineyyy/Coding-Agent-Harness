from harness.registry import Context, make_registry
from harness.tools.web import spec as web_spec
from harness.config import Config
from harness.sandbox import LocalSandbox


class FakeResponse:
    def __init__(self, status_code=200, text="hello web", content=b"hello web"):
        self.status_code = status_code
        self.text = text
        self.content = content


def ctx(ws, network):
    sb = LocalSandbox(network_enabled=network)
    return Context(
        workspace=ws,
        sandbox=sb,
        hooks=None,
        policy=None,
        state=None,
        memory=None,
        config=Config(workspace=ws),
    )


def test_fetch_disabled_by_default(tmp_path):
    reg = make_registry([web_spec()])
    r = reg["fetch_url"].handler({"url": "https://example.com"}, ctx(tmp_path, False))
    assert r.status == "error" and "network disabled" in r.error


def test_fetch_ok_when_enabled(tmp_path):
    seen = {}

    def fake_get(url, timeout):
        seen["url"] = url
        return FakeResponse()

    reg = make_registry([web_spec(fake_get)])
    r = reg["fetch_url"].handler({"url": "https://example.com"}, ctx(tmp_path, True))
    assert r.status == "success" and "hello web" in r.output and seen["url"].startswith("https://")


def test_fetch_http_error(tmp_path):
    reg = make_registry([web_spec(lambda url, timeout: FakeResponse(404, "not found"))])
    r = reg["fetch_url"].handler({"url": "https://example.com/nope"}, ctx(tmp_path, True))
    assert r.status == "error" and "404" in r.error
