"""
HTTP 工具测试
=============
覆盖 react/action/tools/impl/�?
  - WebFetchAction   (web_fetch)   �?mock httpx.get
  - HttpRequestAction (http_request) �?mock httpx.request

所有测试离线运行，不发出真实网络请求�?

运行方式�?
  cd E:/ReAct
  python -m pytest src/test/tools/test_http.py -v
"""
from __future__ import annotations

import importlib.machinery
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

SRC = Path(__file__).resolve().parent.parent.parent
REACT_DIR = SRC / "agent" / "react"


def _pkg_stub(dotted_name: str, path: Path | None = None) -> types.ModuleType:
    m = types.ModuleType(dotted_name)
    m.__package__ = dotted_name
    m.__spec__ = importlib.machinery.ModuleSpec(
        dotted_name, loader=None, is_package=True
    )
    if path is not None:
        m.__path__ = [str(path)]
        m.__spec__.submodule_search_locations = m.__path__
    sys.modules[dotted_name] = m
    return m


def _mod_stub(dotted_name: str) -> types.ModuleType:
    m = types.ModuleType(dotted_name)
    m.__spec__ = importlib.machinery.ModuleSpec(dotted_name, loader=None)
    sys.modules[dotted_name] = m
    return m


_pkg_stub("agent.react", REACT_DIR)
_lc = _pkg_stub("langchain_community")
_lce = _mod_stub("langchain_community.embeddings")
_lcv = _mod_stub("langchain_community.vectorstores")
_lcv.FAISS = MagicMock()
_lc.embeddings = _lce
_lc.vectorstores = _lcv
_lc_hf = _pkg_stub("langchain_huggingface")
_lc_hf.HuggingFaceEmbeddings = MagicMock(name="HuggingFaceEmbeddings")

# html2text �?测试环境未安装，提供最�?stub
_html2text = _mod_stub("html2text")
import re as _re

class _HTML2Text:
    ignore_links = False
    ignore_images = True
    body_width = 0

    def handle(self, html: str) -> str:
        return _re.sub(r"<[^>]+>", " ", html).strip()

_html2text.HTML2Text = _HTML2Text

sys.path.insert(0, str(SRC))

import pytest

from agent.react.action.tools.impl.web_fetch import WebFetchAction
from agent.react.action.tools.impl.http_request import HttpRequestAction

# 保留对两个模块的直接引用，供 monkeypatch 使用
import agent.react.action.tools.impl.web_fetch as _wf_mod
import agent.react.action.tools.impl.http_request as _hr_mod


# ── 辅助：构�?httpx Response mock ──────────────────────────────────────────

def _make_response(
    text: str = "",
    status_code: int = 200,
    content_type: str = "text/html; charset=utf-8",
) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.content = text.encode("utf-8")
    resp.apparent_encoding = "utf-8"
    resp.status_code = status_code
    resp.headers = {"content-type": content_type}
    resp.raise_for_status = MagicMock()
    return resp


def _make_httpx_mock(**kwargs) -> MagicMock:
    """返回一�?httpx 模块 mock�?get / .request �?kwargs 指定�?""
    m = MagicMock()
    for attr, fn in kwargs.items():
        setattr(m, attr, fn)
    return m


# ════════════════════════════════════════════════════════════════════════════�?
#  WebFetchAction
# ════════════════════════════════════════════════════════════════════════════�?

class TestWebFetch:
    def setup_method(self):
        self.action = WebFetchAction()
        self.url = "https://example.com"

    def test_html_converted_to_text(self, monkeypatch):
        html = "<html><body><h1>Title</h1><p>Paragraph text.</p></body></html>"
        monkeypatch.setattr(
            _wf_mod, "httpx",
            _make_httpx_mock(get=lambda *a, **kw: _make_response(text=html, content_type="text/html")),
        )
        result = self.action.execute(url=self.url)
        assert "Title" in result
        assert "Paragraph" in result
        assert "<h1>" not in result

    def test_plain_text_returned_as_is(self, monkeypatch):
        monkeypatch.setattr(
            _wf_mod, "httpx",
            _make_httpx_mock(get=lambda *a, **kw: _make_response(text="just plain text", content_type="text/plain")),
        )
        result = self.action.execute(url=self.url)
        assert "just plain text" in result

    def test_url_in_result(self, monkeypatch):
        monkeypatch.setattr(
            _wf_mod, "httpx",
            _make_httpx_mock(get=lambda *a, **kw: _make_response(text="content")),
        )
        result = self.action.execute(url=self.url)
        assert self.url in result

    def test_max_chars_truncates(self, monkeypatch):
        long_text = "A" * 10000
        monkeypatch.setattr(
            _wf_mod, "httpx",
            _make_httpx_mock(get=lambda *a, **kw: _make_response(text=long_text)),
        )
        result = self.action.execute(url=self.url, max_chars=100)
        assert "截断" in result
        assert "10000" in result

    def test_non_text_content_skipped(self, monkeypatch):
        resp = _make_response(text="binary", content_type="application/pdf")
        resp.content = b"%PDF-1.4 fake"
        monkeypatch.setattr(
            _wf_mod, "httpx",
            _make_httpx_mock(get=lambda *a, **kw: resp),
        )
        result = self.action.execute(url=self.url)
        assert "非文�? in result
        assert "PDF" in result or "pdf" in result.lower()

    def test_disallowed_scheme(self):
        with pytest.raises(ValueError, match="仅允�?):
            self.action.execute(url="file:///etc/passwd")

    def test_timeout_passed_to_httpx(self, monkeypatch):
        captured: dict = {}

        def fake_get(*a, **kw):
            captured["timeout"] = kw.get("timeout")
            return _make_response(text="x")

        monkeypatch.setattr(_wf_mod, "httpx", _make_httpx_mock(get=fake_get))
        self.action.execute(url=self.url, timeout=42)
        assert captured.get("timeout") == 42

    def test_response_too_large_aborts(self, monkeypatch):
        huge = b"x" * 5000
        resp = _make_response(text="")
        resp.content = huge
        resp.text = huge.decode("utf-8")
        monkeypatch.setattr(
            _wf_mod, "httpx",
            _make_httpx_mock(get=lambda *a, **kw: resp),
        )
        result = self.action.execute(url=self.url, max_response_bytes=3000)
        assert "过大" in result
        assert "5000" in result

    def test_sandbox_url_check_called(self, monkeypatch):
        class _SandboxStub:
            def __init__(self):
                self.checked_urls: list = []

            def assert_url_allowed(self, url: str) -> None:
                self.checked_urls.append(url)

        sb = _SandboxStub()
        action = WebFetchAction(sandbox=sb)
        monkeypatch.setattr(
            _wf_mod, "httpx",
            _make_httpx_mock(get=lambda *a, **kw: _make_response(text="ok")),
        )
        action.execute(url=self.url)
        assert self.url in sb.checked_urls

    def test_empty_page(self, monkeypatch):
        monkeypatch.setattr(
            _wf_mod, "httpx",
            _make_httpx_mock(get=lambda *a, **kw: _make_response(text="   ")),
        )
        result = self.action.execute(url=self.url)
        assert "�? in result or result.endswith(")")

    def test_http_error_propagates(self, monkeypatch):
        import httpx
        resp = _make_response(status_code=404)
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=resp
        )
        monkeypatch.setattr(
            _wf_mod, "httpx",
            _make_httpx_mock(get=lambda *a, **kw: resp),
        )
        with pytest.raises(httpx.HTTPStatusError):
            self.action.execute(url=self.url)

    def test_network_error_propagates(self, monkeypatch):
        import httpx

        def _raise(*a, **kw):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(
            _wf_mod, "httpx",
            _make_httpx_mock(get=_raise),
        )
        with pytest.raises(httpx.ConnectError):
            self.action.execute(url=self.url)


# ════════════════════════════════════════════════════════════════════════════�?
#  HttpRequestAction
# ════════════════════════════════════════════════════════════════════════════�?

class TestHttpRequest:
    def setup_method(self):
        self.action = HttpRequestAction()
        self.url = "https://httpbin.org/get"

    def _patch_request(self, monkeypatch, text: str = "OK", status: int = 200):
        resp = _make_response(text=text, status_code=status, content_type="application/json")
        monkeypatch.setattr(
            _hr_mod, "httpx",
            _make_httpx_mock(request=lambda *a, **kw: resp),
        )
        return resp

    def test_get_returns_status_and_body(self, monkeypatch):
        self._patch_request(monkeypatch, text='{"key": "value"}')
        result = self.action.execute(url=self.url, method="GET")
        assert "200" in result
        assert "key" in result

    def test_post_with_json_body(self, monkeypatch):
        captured = {}
        resp = _make_response(text="created")

        def fake_request(*a, **kw):
            captured.update(kw)
            return resp

        monkeypatch.setattr(_hr_mod, "httpx", _make_httpx_mock(request=fake_request))
        self.action.execute(url=self.url, method="POST", json_body={"name": "test"})
        assert captured.get("json") == {"name": "test"}

    def test_post_with_string_body(self, monkeypatch):
        captured = {}
        resp = _make_response(text="ok")

        def fake_request(*a, **kw):
            captured.update(kw)
            return resp

        monkeypatch.setattr(_hr_mod, "httpx", _make_httpx_mock(request=fake_request))
        self.action.execute(url=self.url, method="POST", body="raw body text")
        assert captured.get("content") == b"raw body text"

    def test_method_uppercased(self, monkeypatch):
        captured = {}
        resp = _make_response()

        def fake_request(*a, **kw):
            captured["method"] = a[0] if a else kw.get("method")
            return resp

        monkeypatch.setattr(_hr_mod, "httpx", _make_httpx_mock(request=fake_request))
        self.action.execute(url=self.url, method="put")
        assert captured["method"] == "PUT"

    def test_max_response_chars_truncates(self, monkeypatch):
        self._patch_request(monkeypatch, text="X" * 10000)
        result = self.action.execute(url=self.url, max_response_chars=100)
        assert "截断" in result

    def test_custom_headers_forwarded(self, monkeypatch):
        captured = {}
        resp = _make_response()

        def fake_request(*a, **kw):
            captured["headers"] = kw.get("headers", {})
            return resp

        monkeypatch.setattr(_hr_mod, "httpx", _make_httpx_mock(request=fake_request))
        self.action.execute(url=self.url, headers={"X-Token": "abc"})
        assert captured["headers"].get("X-Token") == "abc"

    def test_sandbox_url_check_called(self, monkeypatch):
        # Python 3.12+ MagicMock 禁止访问 assert_* 属性，改用自定�?stub
        class _SandboxStub:
            def __init__(self):
                self.checked_urls: list = []
            def assert_url_allowed(self, url: str) -> None:
                self.checked_urls.append(url)

        sb = _SandboxStub()
        action = HttpRequestAction(sandbox=sb)
        self._patch_request(monkeypatch)
        action.execute(url=self.url)
        assert self.url in sb.checked_urls

    def test_result_contains_url_and_method(self, monkeypatch):
        self._patch_request(monkeypatch)
        result = self.action.execute(url=self.url, method="GET")
        assert self.url in result
        assert "GET" in result


# ════════════════════════════════════════════════════════════════════════════�?
#  直接运行
# ════════════════════════════════════════════════════════════════════════════�?

if __name__ == "__main__":
    print("请使�?pytest 运行此文件（需�?monkeypatch fixture）：")
    print("  python -m pytest src/test/tools/test_http.py -v")
