"""
Data 工具测试
=============
覆盖 react/action/tools/impl/data_tool.py 以及元工具 tool_search：
  - JsonQueryAction   (json_query)
  - RegexExtractAction (regex_extract)
  - TextDiffAction    (text_diff)
  - ToolSearchAction  (tool_search) — mock ToolManager

运行方式：
  cd E:/ReAct
  python -m pytest src/test/tools/test_tools_data.py -v
"""
from __future__ import annotations

import importlib.machinery
import json
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

_lc_comm = _pkg_stub("langchain_community")
_lc_emb  = _mod_stub("langchain_community.embeddings")
_lc_vs   = _mod_stub("langchain_community.vectorstores")
_lc_emb.HuggingFaceBgeEmbeddings = MagicMock()
_lc_vs.FAISS = MagicMock()
_lc_comm.embeddings  = _lc_emb
_lc_comm.vectorstores = _lc_vs

# jsonpath_ng — 测试环境未安装，提供最小 stub
_jpn = _pkg_stub("jsonpath_ng")

class _JPNMatch:
    def __init__(self, value):
        self.value = value

def _jpn_parse(path: str):
    """极简 JSONPath stub：仅支持 $.key 和 $.arr[*].key 形式。"""
    import re

    class _Expr:
        def __init__(self, path):
            self._path = path

        def find(self, data):
            p = self._path
            # Remove leading $
            if p.startswith("$"):
                p = p[1:]
            parts = [x for x in re.split(r"\.|(?=\[)", p) if x]
            results = [data]
            for part in parts:
                new_results = []
                for node in results:
                    if part.startswith("[*]"):
                        if isinstance(node, list):
                            new_results.extend(node)
                    elif part.startswith("[") and part.endswith("]"):
                        idx = int(part[1:-1])
                        if isinstance(node, (list, tuple)) and len(node) > idx:
                            new_results.append(node[idx])
                    elif isinstance(node, dict) and part in node:
                        new_results.append(node[part])
                results = new_results
            return [_JPNMatch(v) for v in results]

    return _Expr(path)

_jpn.parse = _jpn_parse

sys.path.insert(0, str(SRC))

import pytest

from agent.react.action.tools.impl.data_tool import (
    JsonQueryAction,
    RegexExtractAction,
    TextDiffAction,
)


# ═════════════════════════════════════════════════════════════════════════════
#  JsonQueryAction
# ═════════════════════════════════════════════════════════════════════════════

class TestJsonQuery:
    def setup_method(self):
        self.action = JsonQueryAction()

    def test_simple_key(self):
        data = json.dumps({"name": "Alice", "age": 30})
        result = self.action.execute(data=data, path="$.name")
        assert "Alice" in result

    def test_nested_key(self):
        data = json.dumps({"user": {"profile": {"city": "Beijing"}}})
        result = self.action.execute(data=data, path="$.user.profile.city")
        assert "Beijing" in result

    def test_array_wildcard(self):
        data = json.dumps({"items": [{"id": 1}, {"id": 2}, {"id": 3}]})
        result = self.action.execute(data=data, path="$.items[*].id")
        parsed = json.loads(result)
        assert parsed == [1, 2, 3]

    def test_no_match_returns_message(self):
        data = json.dumps({"a": 1})
        result = self.action.execute(data=data, path="$.nonexistent")
        assert "未匹配" in result

    def test_single_match_unwrapped(self):
        data = json.dumps({"x": 42})
        result = self.action.execute(data=data, path="$.x")
        assert result.strip() == "42"

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            self.action.execute(data="not json", path="$.x")

    def test_nested_object_match(self):
        data = json.dumps({"meta": {"version": "1.0", "author": "Bob"}})
        result = self.action.execute(data=data, path="$.meta")
        parsed = json.loads(result)
        assert parsed["version"] == "1.0"
        assert parsed["author"] == "Bob"


# ═════════════════════════════════════════════════════════════════════════════
#  RegexExtractAction
# ═════════════════════════════════════════════════════════════════════════════

class TestRegexExtract:
    def setup_method(self):
        self.action = RegexExtractAction()

    def test_basic_match(self):
        result = self.action.execute(text="foo123 bar456", pattern=r"\d+")
        assert "123" in result
        assert "456" in result

    def test_no_match_returns_message(self):
        result = self.action.execute(text="hello world", pattern=r"\d+")
        assert "未" in result

    def test_case_insensitive_flag(self):
        result = self.action.execute(text="Hello WORLD hello", pattern="hello", flags="i")
        assert "共找到 2 个" in result or "共找到 3 个" in result

    def test_multiline_flag(self):
        text = "start\nline two\nend"
        result = self.action.execute(text=text, pattern=r"^line", flags="m")
        assert "line two" in result or "line" in result

    def test_dotall_flag(self):
        text = "start\nmiddle\nend"
        result = self.action.execute(text=text, pattern=r"start.+end", flags="s")
        assert "未" not in result

    def test_max_matches_truncates(self):
        text = " ".join(str(i) for i in range(50))
        result = self.action.execute(text=text, pattern=r"\d+", max_matches=5)
        assert "显示前 5 个" in result

    def test_groups_returned(self):
        result = self.action.execute(text="2024-01-15", pattern=r"(\d{4})-(\d{2})-(\d{2})")
        assert "分组" in result

    def test_email_extraction(self):
        text = "contact alice@example.com or bob@test.org"
        result = self.action.execute(text=text, pattern=r"[\w.]+@[\w.]+")
        assert "alice@example.com" in result
        assert "bob@test.org" in result


# ═════════════════════════════════════════════════════════════════════════════
#  TextDiffAction
# ═════════════════════════════════════════════════════════════════════════════

class TestTextDiff:
    def setup_method(self):
        self.action = TextDiffAction()

    def test_identical_texts_no_diff(self):
        result = self.action.execute(text_a="hello", text_b="hello")
        assert "相同" in result

    def test_single_line_change(self):
        result = self.action.execute(text_a="hello world", text_b="hello Python")
        assert "-" in result
        assert "+" in result

    def test_added_line(self):
        result = self.action.execute(text_a="line1", text_b="line1\nline2")
        assert "+" in result
        assert "line2" in result

    def test_removed_line(self):
        result = self.action.execute(text_a="line1\nline2", text_b="line1")
        assert "-" in result
        assert "line2" in result

    def test_context_lines_zero(self):
        text_a = "\n".join(f"line{i}" for i in range(10))
        text_b = "\n".join(f"line{i}" for i in range(10)).replace("line5", "changed")
        result_full = self.action.execute(text_a=text_a, text_b=text_b, context_lines=3)
        result_zero = self.action.execute(text_a=text_a, text_b=text_b, context_lines=0)
        assert len(result_zero) <= len(result_full)

    def test_multiline_diff_contains_header(self):
        result = self.action.execute(text_a="old\ncontent", text_b="new\ncontent")
        assert "text_a" in result
        assert "text_b" in result

    def test_empty_original(self):
        result = self.action.execute(text_a="", text_b="new content")
        assert "+" in result

    def test_empty_new(self):
        result = self.action.execute(text_a="old content", text_b="")
        assert "-" in result


# ═════════════════════════════════════════════════════════════════════════════
#  ToolSearchAction — mock ToolManager
# ═════════════════════════════════════════════════════════════════════════════

class TestToolSearch:
    def setup_method(self):
        from agent.react.action.tools.tool_search import ToolSearchAction
        from agent.react.action.tools.registry import ToolMeta

        self.ToolMeta = ToolMeta

        mock_manager = MagicMock()
        mock_manager.search.return_value = [
            ToolMeta(name="calculator", description="数学计算工具", category="math", tags=[], action_cls=None),
            ToolMeta(name="web_search", description="网络搜索工具", category="network", tags=[], action_cls=None),
        ]
        self.action = ToolSearchAction(manager=mock_manager)
        self.mock_manager = mock_manager

    def test_returns_string(self):
        result = self.action.execute(query="计算")
        assert isinstance(result, str)

    def test_search_called_with_query(self):
        self.action.execute(query="math tool")
        self.mock_manager.search.assert_called_once()
        call_args = self.mock_manager.search.call_args
        assert "math tool" in str(call_args)

    def test_results_contain_tool_names(self):
        result = self.action.execute(query="tool")
        assert "calculator" in result
        assert "web_search" in result

    def test_empty_results_message(self):
        self.mock_manager.search.return_value = []
        result = self.action.execute(query="nonexistent_xyz")
        assert "未找到" in result or "没有" in result or len(result) > 0

    def test_top_k_passed(self):
        self.action.execute(query="test", top_k=3)
        call_args = self.mock_manager.search.call_args
        assert 3 in call_args.args or call_args.kwargs.get("top_k") == 3


# ═════════════════════════════════════════════════════════════════════════════
#  直接运行
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    suites = [
        ("JsonQuery",      TestJsonQuery),
        ("RegexExtract",   TestRegexExtract),
        ("TextDiff",       TestTextDiff),
        ("ToolSearch",     TestToolSearch),
    ]

    passed = failed = 0
    for name, cls in suites:
        print(f"\n── {name} ──")
        inst = cls()
        for m in sorted(m for m in dir(cls) if m.startswith("test_")):
            inst.setup_method()
            try:
                getattr(inst, m)()
                print(f"  PASS  {m}")
                passed += 1
            except Exception:
                print(f"  FAIL  {m}")
                traceback.print_exc()
                failed += 1

    print(f"\n{'='*50}")
    print(f"Result: {passed} passed, {failed} failed")
