"""
工具模块测试
============
覆盖 react/action/tools/impl/ 下全部工具，以及 web_search（SearXNG）。

运行方式：
  cd G:/ReAct
  python -m pytest src/test/test_tools.py -v
  # 或直接：
  python src/test/test_tools.py
"""

from __future__ import annotations

import importlib.machinery
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# ── 必须在任何项目模块导入之前执行 ──────────────────────────────────────────
#
# react/__init__.py 会 import TaoLoop → 触发 long_term/store.py
# → langchain_community（未安装）。
# 解决：把 react 替换为带真实 __path__ 的空壳包，让子模块仍可按路径加载，
# 同时桩住 langchain_community / langchain_core 的不可用符号。
# ─────────────────────────────────────────────────────────────────────────────

SRC = Path(__file__).resolve().parent.parent
REACT_DIR = SRC / "react"


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


# react 包：跳过 __init__.py，子模块仍可按路径寻址
_pkg_stub("react", REACT_DIR)

# langchain_community：桩住 store.py 依赖的子模块
_lc_comm = _pkg_stub("langchain_community")
_lc_emb  = _mod_stub("langchain_community.embeddings")
_lc_vs   = _mod_stub("langchain_community.vectorstores")
_lc_emb.HuggingFaceBgeEmbeddings = MagicMock(name="HuggingFaceBgeEmbeddings")
_lc_vs.FAISS                      = MagicMock(name="FAISS")
_lc_comm.embeddings               = _lc_emb
_lc_comm.vectorstores             = _lc_vs

sys.path.insert(0, str(SRC))

# ─────────────────────────────────────────────────────────────────────────────

import pytest

# ── 导入所有工具 ──────────────────────────────────────────────────────────────

from react.action.tools.impl.calculator import CalculatorAction
from react.action.tools.impl.datetime_tool import GetDatetimeAction, GetWeekdayAction
from react.action.tools.impl.random_tool import (
    GenerateUUIDAction,
    RandomChoiceAction,
    RandomNumberAction,
)
from react.action.tools.impl.string_tool import Base64Action, HashAction, StringTransformAction
from react.action.tools.impl.unit_converter import UnitConverterAction
from react.action.tools.impl.weather import WeatherAction
from react.action.tools.impl.web_search import WebSearchAction
from react.action.tools.impl.word_count import WordCountAction


# ═════════════════════════════════════════════════════════════════════════════
#  Calculator
# ═════════════════════════════════════════════════════════════════════════════

class TestCalculator:
    def setup_method(self):
        self.calc = CalculatorAction()

    def test_addition(self):
        assert self.calc.execute("1 + 2") == "1 + 2 = 3"

    def test_multiplication(self):
        assert self.calc.execute("3 * 4") == "3 * 4 = 12"

    def test_float_result(self):
        result = self.calc.execute("1 / 3")
        assert result.startswith("1 / 3 =")
        assert "0.333" in result

    def test_integer_result_no_decimal(self):
        assert self.calc.execute("9 / 3") == "9 / 3 = 3"

    def test_power(self):
        assert self.calc.execute("2 ** 10") == "2 ** 10 = 1024"

    def test_sqrt(self):
        assert self.calc.execute("sqrt(16)") == "sqrt(16) = 4"

    def test_complex_expression(self):
        result = self.calc.execute("2 + 3 * 4")
        assert result == "2 + 3 * 4 = 14"

    def test_modulo(self):
        assert self.calc.execute("10 % 3") == "10 % 3 = 1"

    def test_floor_div(self):
        assert self.calc.execute("10 // 3") == "10 // 3 = 3"

    def test_pi_constant(self):
        result = self.calc.execute("pi")
        assert "3.14159" in result

    def test_unsupported_function_raises(self):
        with pytest.raises(ValueError, match="unknown function"):
            self.calc.execute("exec('rm -rf')")


# ═════════════════════════════════════════════════════════════════════════════
#  Datetime
# ═════════════════════════════════════════════════════════════════════════════

class TestGetDatetime:
    def setup_method(self):
        self.action = GetDatetimeAction()

    def test_returns_string(self):
        result = self.action.execute()
        assert isinstance(result, str)

    def test_contains_date_pattern(self):
        result = self.action.execute()
        assert "年" in result and "月" in result and "日" in result

    def test_contains_time_pattern(self):
        result = self.action.execute()
        assert ":" in result

    def test_utc_timezone(self):
        result = self.action.execute(tz="utc")
        assert "UTC+0" in result

    def test_beijing_timezone(self):
        result = self.action.execute(tz="beijing")
        assert "UTC+8" in result

    def test_unknown_tz_defaults_to_beijing(self):
        result = self.action.execute(tz="nonexistent")
        assert "UTC+8" in result


class TestGetWeekday:
    def setup_method(self):
        self.action = GetWeekdayAction()

    def test_known_weekday(self):
        result = self.action.execute(date="2024-01-01")
        assert "星期一" in result

    def test_another_weekday(self):
        result = self.action.execute(date="2024-06-15")
        assert "星期六" in result

    def test_contains_week_number(self):
        result = self.action.execute(date="2024-01-01")
        assert "第" in result and "周" in result


# ═════════════════════════════════════════════════════════════════════════════
#  Random
# ═════════════════════════════════════════════════════════════════════════════

class TestRandomNumber:
    def setup_method(self):
        self.action = RandomNumberAction()

    def test_result_in_range(self):
        for _ in range(20):
            result = self.action.execute(min=1, max=10)
            n = int(result.split("：")[1])
            assert 1 <= n <= 10

    def test_decimal_mode(self):
        result = self.action.execute(min=0, max=1, decimal=True)
        assert "随机小数" in result

    def test_single_value_range(self):
        result = self.action.execute(min=42, max=42)
        assert "42" in result

    def test_invalid_range_raises(self):
        with pytest.raises(Exception):
            self.action.execute(min=10, max=1)


class TestRandomChoice:
    def setup_method(self):
        self.action = RandomChoiceAction()

    def test_chosen_from_options(self):
        for _ in range(20):
            result = self.action.execute(options="苹果,香蕉,橘子")
            assert any(item in result for item in ["苹果", "香蕉", "橘子"])

    def test_single_option(self):
        result = self.action.execute(options="唯一")
        assert "唯一" in result


class TestGenerateUUID:
    def setup_method(self):
        self.action = GenerateUUIDAction()

    def test_uuid_format(self):
        import re
        result = self.action.execute()
        uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        assert re.search(uuid_pattern, result)

    def test_unique_each_time(self):
        r1 = self.action.execute()
        r2 = self.action.execute()
        assert r1 != r2


# ═════════════════════════════════════════════════════════════════════════════
#  String
# ═════════════════════════════════════════════════════════════════════════════

class TestStringTransform:
    def setup_method(self):
        self.action = StringTransformAction()

    def test_upper(self):
        result = self.action.execute(text="hello", operation="upper")
        assert "HELLO" in result

    def test_lower(self):
        result = self.action.execute(text="WORLD", operation="lower")
        assert "world" in result

    def test_title(self):
        result = self.action.execute(text="hello world", operation="title")
        assert "Hello World" in result

    def test_reverse(self):
        result = self.action.execute(text="abc", operation="reverse")
        assert "cba" in result

    def test_strip(self):
        result = self.action.execute(text="  hi  ", operation="strip")
        assert "hi" in result

    def test_count_chars(self):
        result = self.action.execute(text="banana", operation="count_chars", char="a")
        assert "3" in result

    def test_count_chars_missing_char_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            StringTransformAction.args_model.model_validate(
                {"text": "test", "operation": "count_chars", "char": ""}
            )

    def test_unsupported_operation_raises(self):
        with pytest.raises(ValueError):
            self.action.execute(text="x", operation="explode")


class TestBase64:
    def setup_method(self):
        self.action = Base64Action()

    def test_encode(self):
        result = self.action.execute(text="hello", mode="encode")
        assert "aGVsbG8=" in result

    def test_decode(self):
        result = self.action.execute(text="aGVsbG8=", mode="decode")
        assert "hello" in result

    def test_encode_decode_roundtrip(self):
        original = "你好，世界！"
        encoded = self.action.execute(text=original, mode="encode")
        b64 = encoded.split("：")[1].strip()
        decoded = self.action.execute(text=b64, mode="decode")
        assert original in decoded


class TestHash:
    def setup_method(self):
        self.action = HashAction()

    def test_sha256_length(self):
        result = self.action.execute(text="hello", algorithm="sha256")
        hex_part = result.split("：")[1].strip()
        assert len(hex_part) == 64

    def test_md5_length(self):
        result = self.action.execute(text="hello", algorithm="md5")
        hex_part = result.split("：")[1].strip()
        assert len(hex_part) == 32

    def test_sha1_length(self):
        result = self.action.execute(text="hello", algorithm="sha1")
        hex_part = result.split("：")[1].strip()
        assert len(hex_part) == 40

    def test_deterministic(self):
        r1 = self.action.execute(text="test", algorithm="sha256")
        r2 = self.action.execute(text="test", algorithm="sha256")
        assert r1 == r2

    def test_different_inputs_differ(self):
        r1 = self.action.execute(text="aaa", algorithm="md5")
        r2 = self.action.execute(text="bbb", algorithm="md5")
        assert r1 != r2


# ═════════════════════════════════════════════════════════════════════════════
#  UnitConverter
# ═════════════════════════════════════════════════════════════════════════════

class TestUnitConverter:
    def setup_method(self):
        self.action = UnitConverterAction()

    def test_km_to_m(self):
        result = self.action.execute(value=1.0, from_unit="km", to_unit="m")
        assert "1000" in result

    def test_celsius_to_fahrenheit(self):
        result = self.action.execute(value=0.0, from_unit="c", to_unit="f")
        assert "32" in result

    def test_celsius_to_kelvin(self):
        result = self.action.execute(value=0.0, from_unit="c", to_unit="k")
        assert "273.15" in result

    def test_kg_to_lb(self):
        result = self.action.execute(value=1.0, from_unit="kg", to_unit="lb")
        assert "2.2" in result

    def test_unsupported_conversion_raises(self):
        with pytest.raises(ValueError):
            self.action.execute(value=1.0, from_unit="kg", to_unit="m")


# ═════════════════════════════════════════════════════════════════════════════
#  WordCount
# ═════════════════════════════════════════════════════════════════════════════

class TestWordCount:
    def setup_method(self):
        self.action = WordCountAction()

    def test_basic_count(self):
        result = self.action.execute(text="hello world")
        assert "11" in result  # 总字符数

    def test_chinese_chars(self):
        result = self.action.execute(text="你好世界")
        assert "4" in result

    def test_multiline(self):
        result = self.action.execute(text="line1\nline2\nline3")
        assert "行数：3" in result

    def test_empty_like_text(self):
        result = self.action.execute(text="x")
        assert isinstance(result, str)


# ═════════════════════════════════════════════════════════════════════════════
#  Weather (占位工具)
# ═════════════════════════════════════════════════════════════════════════════

class TestWeather:
    def setup_method(self):
        self.action = WeatherAction()

    def test_fixed_response(self):
        result = self.action.execute()
        assert result == "7月1日，晴天，温度为30~35°"

    def test_ignores_city_param(self):
        result = self.action.execute(city="北京")
        assert result == "7月1日，晴天，温度为30~35°"


# ═════════════════════════════════════════════════════════════════════════════
#  WebSearch — 调度层测试
#  Action 层仅做参数校验与格式化；网络逻辑全在 network.search。
#  离线测试在 SearchEngine 层 mock，不触碰 httpx。
# ═════════════════════════════════════════════════════════════════════════════

def _check_searxng() -> bool:
    """探测本地 SearXNG，只用 SEARXNG_URL 或 127.0.0.1:8888，不读 YAML。"""
    import httpx
    url = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8888").rstrip("/")
    resp = httpx.get(
        f"{url}/search",
        params={"q": "test", "format": "json"},
        timeout=httpx.Timeout(3.0),
    )
    return resp.status_code == 200


def _searxng_available() -> bool:
    try:
        return _check_searxng()
    except Exception:
        return False


_live_searxng = _searxng_available()


@pytest.mark.skipif(not _live_searxng, reason="SearXNG 实例不可达")
class TestWebSearch:
    """在线测试：需要真实 SearXNG 实例（设置 SEARXNG_URL 环境变量）。"""

    def setup_method(self):
        self.action = WebSearchAction()

    def test_returns_results(self):
        result = self.action.execute(query="Python programming", max_results=3)
        assert isinstance(result, str) and len(result) > 0
        assert "搜索" in result

    def test_result_count_respected(self):
        result = self.action.execute(query="Python", max_results=2)
        assert "共 2 条" in result or "共 1 条" in result

    def test_no_results_message(self):
        result = self.action.execute(
            query="xkcdqwertyuiopzxcvbnmasdfghjkl12345678900987654321",
            max_results=1,
        )
        assert isinstance(result, str)

    def test_language_param(self):
        result = self.action.execute(query="Python", language="zh-CN", max_results=3)
        assert isinstance(result, str)

    def test_news_category(self):
        result = self.action.execute(query="technology", categories="news", max_results=3)
        assert isinstance(result, str)


class TestWebSearchOffline:
    """
    离线测试：在 SearchEngine 层注入假结果，完全不触碰 httpx。

    验证点：
      · Action 正确把参数传给 SearchEngine.search()
      · Action 正确把 SearchResult 列表格式化成字符串
      · 空结果时返回"未找到"提示
      · 后端异常时异常向上透传
    """

    def setup_method(self):
        self.action = WebSearchAction()

    # ── 辅助 ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _patch_engine(monkeypatch, results=None, error=None):
        """把 SearchEngine.search() 替换为返回 results 或抛出 error 的假版本。"""
        from network.search.engine import SearchEngine

        if error is not None:
            def _fake_search(self, *a, **kw):
                raise error
        else:
            def _fake_search(self, *a, **kw):
                return results or []

        monkeypatch.setattr(SearchEngine, "search", _fake_search)

    # ── 测试项 ────────────────────────────────────────────────────────────────

    def test_empty_results_message(self, monkeypatch):
        self._patch_engine(monkeypatch, results=[])
        result = self.action.execute(query="无结果关键词")
        assert "未找到" in result

    def test_result_formatting(self, monkeypatch):
        from network.search.result import SearchResult

        fake = [SearchResult(
            title="Python 官网",
            snippet="Python 是一种高级编程语言",
            url="https://python.org",
            engine="google",
        )]
        self._patch_engine(monkeypatch, results=fake)
        result = self.action.execute(query="python", max_results=1)
        assert "Python 官网" in result
        assert "https://python.org" in result
        assert "google" in result
        assert "Python 是一种高级编程语言" in result

    def test_result_count_in_header(self, monkeypatch):
        from network.search.result import SearchResult

        fakes = [SearchResult(title=f"标题{i}", snippet="", url=f"http://ex.com/{i}", engine="x")
                 for i in range(3)]
        self._patch_engine(monkeypatch, results=fakes)
        result = self.action.execute(query="test", max_results=3)
        assert "共 3 条" in result

    def test_backend_error_propagates(self, monkeypatch):
        import httpx
        self._patch_engine(monkeypatch, error=httpx.ConnectError("connection refused"))
        with pytest.raises(httpx.ConnectError):
            self.action.execute(query="test")

    def test_no_backend_raises(self, monkeypatch):
        """当所有 backend 均不可用时 SearchEngine 应抛出 RuntimeError。"""
        from network.search.engine import SearchEngine
        from network.search.backend.base import BaseSearchBackend

        monkeypatch.setattr(BaseSearchBackend, "is_available", lambda self: False)
        with pytest.raises(RuntimeError, match="没有可用的搜索后端"):
            SearchEngine().search("test")

    def test_params_forwarded(self, monkeypatch):
        """Action 把 language / categories 正确转发给 SearchEngine.search()。"""
        from network.search.engine import SearchEngine

        captured: dict = {}

        def _fake_search(self, query, max_results, language, categories):
            captured.update(query=query, max_results=max_results,
                            language=language, categories=categories)
            return []

        monkeypatch.setattr(SearchEngine, "search", _fake_search)
        self.action.execute(query="test", max_results=5, language="zh-CN", categories="news")
        assert captured["language"] == "zh-CN"
        assert captured["categories"] == "news"
        assert captured["max_results"] == 5


# ═════════════════════════════════════════════════════════════════════════════
#  直接运行
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    suites = [
        ("Calculator",      TestCalculator),
        ("GetDatetime",     TestGetDatetime),
        ("GetWeekday",      TestGetWeekday),
        ("RandomNumber",    TestRandomNumber),
        ("RandomChoice",    TestRandomChoice),
        ("GenerateUUID",    TestGenerateUUID),
        ("StringTransform", TestStringTransform),
        ("Base64",          TestBase64),
        ("Hash",            TestHash),
        ("UnitConverter",   TestUnitConverter),
        ("WordCount",       TestWordCount),
        ("Weather",         TestWeather),
        ("WebSearch(mock)", TestWebSearchOffline),
    ]

    if _live_searxng:
        suites.append(("WebSearch(live)", TestWebSearch))
    else:
        print("\n[SKIP] SearXNG 不可达，跳过在线 WebSearch 测试。")
        print("       在 config/network/web_search.yaml 中配置可用实例地址后重试。\n")

    total = passed = failed = 0

    for suite_name, cls in suites:
        print(f"\n── {suite_name} ──")
        inst = cls()
        methods = [m for m in dir(cls) if m.startswith("test_")]
        for m in methods:
            total += 1
            inst.setup_method()
            fn = getattr(inst, m)
            sig = fn.__code__.co_varnames[:fn.__code__.co_argcount]
            if "monkeypatch" in sig:
                print(f"  SKIP  {m}  (需要 pytest monkeypatch，请用 pytest 运行)")
                total -= 1
                continue
            result_ok = True
            try:
                fn()
            except Exception as e:
                result_ok = False
                failed += 1
                print(f"  FAIL  {m}")
                traceback.print_exc()
            if result_ok:
                passed += 1
                print(f"  PASS  {m}")

    print(f"\n{'='*50}")
    print(f"结果：{passed} 通过 / {failed} 失败 / {total} 总计")
