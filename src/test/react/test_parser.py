"""
ReAct Parser Robustness 测试
============================
覆盖三层兜底机制的各个组件：
  - parser.py: ParseQuality, diagnose(), 宽松推断
  - repair.py: build_repair_prompt(), repair()
  - executor.py: difflib 工具名模糊匹配
  - tao.py stream(): 三层保护链行为（模拟集成）

运行方式：
  cd E:/ReAct
  python -m pytest src/test/test_parser_robustness.py -v
  # 或直接：
  python src/test/test_parser_robustness.py
"""

from __future__ import annotations

import importlib.machinery
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# ── sys.path + react package stub ─────────────────────────────────────────────
#
# Stub `react` as an empty package with the real __path__ so that submodules
# can be loaded individually without executing react/__init__.py (which would
# trigger the full TaoLoop → LangChain import chain).

SRC = Path(__file__).resolve().parent.parent.parent
REACT_DIR = SRC / "react"
sys.path.insert(0, str(SRC))


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


# Stub `react` package so __init__.py is skipped
_pkg_stub("react", REACT_DIR)
# Stub `react.prompt` package so its __init__.py is skipped (it imports
# block / builder / manager which pull in langchain_core.prompts etc.)
_pkg_stub("react.prompt", REACT_DIR / "prompt")
# Stub `react.action` package similarly
_pkg_stub("react.action", REACT_DIR / "action")

# ── langchain_core stubs ──────────────────────────────────────────────────────

_lc_core      = _pkg_stub("langchain_core")
_lc_tools_mod = _mod_stub("langchain_core.tools")
_lc_msgs_mod  = _mod_stub("langchain_core.messages")
_lc_parse_mod = _mod_stub("langchain_core.output_parsers")

# BaseTool must be a real class so BaseAction can inherit from it
class _BaseTool:
    name: str = ""
    description: str = ""
    model_fields: dict = {}

_lc_tools_mod.BaseTool = _BaseTool

# Message classes
for _cls_name in ("BaseMessage", "SystemMessage", "HumanMessage", "AIMessage"):
    setattr(_lc_msgs_mod, _cls_name, type(_cls_name, (), {"__init__": lambda self, content="", **kw: setattr(self, "content", content)}))

# BaseOutputParser — real base class for ReActOutputParser
class _BaseOutputParser:
    def __class_getitem__(cls, item):  # make it subscriptable: BaseOutputParser[ParseResult]
        return cls
    def parse(self, text: str):  # noqa: D102
        ...
    @property
    def _type(self) -> str:
        return "base"

_lc_parse_mod.BaseOutputParser = _BaseOutputParser
_lc_core.output_parsers = _lc_parse_mod
_lc_core.tools = _lc_tools_mod
_lc_core.messages = _lc_msgs_mod

# ── pydantic stub ─────────────────────────────────────────────────────────────

_pydantic = _pkg_stub("pydantic")
_pydantic.BaseModel  = type("BaseModel", (), {
    "model_validate": classmethod(lambda cls, d: cls()),
    "model_dump": lambda self: {},
})
_pydantic.ValidationError = Exception
_pydantic.Field = lambda *a, **kw: None
_pydantic.ConfigDict = lambda **kw: dict(kw)

# ── Other optional stubs ──────────────────────────────────────────────────────

for _name in [
    "langchain_community", "langchain_community.embeddings",
    "langchain_community.vectorstores", "faiss", "sentence_transformers",
    "qdrant_client", "pymysql", "redis",
]:
    sys.modules.setdefault(_name, _mod_stub(_name))

# ── Now import the modules under test ─────────────────────────────────────────

from react.prompt.parser import (   # noqa: E402
    ParseQuality,
    ParseResult,
    diagnose,
    parse_llm_output,
    _infer_action,
)
from react.prompt.repair import build_repair_prompt, repair  # noqa: E402
from react.action.executor import ActionExecutor              # noqa: E402


# ═════════════════════════════════════════════════════════════════════════════
# 1. ParseQuality enum
# ═════════════════════════════════════════════════════════════════════════════

class TestParseQualityEnum:
    def test_values(self):
        assert ParseQuality.CLEAN.value   == "clean"
        assert ParseQuality.LENIENT.value == "lenient"
        assert ParseQuality.FAILED.value  == "failed"


# ═════════════════════════════════════════════════════════════════════════════
# 2. CLEAN quality — standard labels
# ═════════════════════════════════════════════════════════════════════════════

class TestParserClean:
    def test_standard_tool_call(self):
        raw = (
            "Thought: I need to search.\n"
            "Action: web_search\n"
            'Action Input: {"query": "python asyncio"}'
        )
        r = parse_llm_output(raw)
        assert r.quality == ParseQuality.CLEAN
        assert r.action == "web_search"
        assert r.action_input == {"query": "python asyncio"}
        assert not r.is_finish

    def test_finish_with_answer(self):
        raw = (
            "Thought: I know the answer.\n"
            "Action: finish\n"
            'Action Input: {"answer": "42"}'
        )
        r = parse_llm_output(raw)
        assert r.quality == ParseQuality.CLEAN
        assert r.is_finish
        assert r.action_input["answer"] == "42"

    def test_markdown_bold_labels(self):
        raw = (
            "**Thought**: thinking...\n"
            "**Action**: tool_search\n"
            '**Action Input**: {"query": "hello"}'
        )
        r = parse_llm_output(raw)
        assert r.quality == ParseQuality.CLEAN
        assert r.action == "tool_search"

    def test_cjk_separator(self):
        raw = (
            "Thought：看看天气\n"
            "Action：web_search\n"
            'Action Input：{"query": "今日天气"}'
        )
        r = parse_llm_output(raw)
        assert r.quality == ParseQuality.CLEAN
        assert r.action == "web_search"

    def test_final_answer_keyword(self):
        raw = (
            "Thought: done\n"
            "Action: final_answer\n"
            'Action Input: {"answer": "hello"}'
        )
        r = parse_llm_output(raw)
        assert r.is_finish
        assert r.action_input["answer"] == "hello"


# ═════════════════════════════════════════════════════════════════════════════
# 3. LENIENT quality — Layer 1b heuristic inference
# ═════════════════════════════════════════════════════════════════════════════

class TestParserLenient:
    TOOLS = frozenset({"web_search", "knowledge_save", "tool_search"})

    def test_verb_use(self):
        raw = "Thought: I'll use web_search to look this up.\n"
        r = parse_llm_output(raw, tool_names=self.TOOLS)
        assert r.quality == ParseQuality.LENIENT
        assert r.action == "web_search"
        assert not r.is_finish

    def test_verb_using(self):
        raw = "Using knowledge_save to persist my findings."
        r = parse_llm_output(raw, tool_names=self.TOOLS)
        assert r.quality == ParseQuality.LENIENT
        assert r.action == "knowledge_save"

    def test_verb_calling(self):
        raw = "Calling tool_search now."
        r = parse_llm_output(raw, tool_names=self.TOOLS)
        assert r.quality == ParseQuality.LENIENT
        assert r.action == "tool_search"

    def test_cjk_verb(self):
        raw = "调用 web_search 来查询相关信息。"
        r = parse_llm_output(raw, tool_names=self.TOOLS)
        assert r.quality == ParseQuality.LENIENT
        assert r.action == "web_search"

    def test_first_line_bare_tool_name(self):
        raw = 'tool_search\n{"query": "something"}'
        r = parse_llm_output(raw, tool_names=self.TOOLS)
        assert r.quality == ParseQuality.LENIENT
        assert r.action == "tool_search"

    def test_unknown_verb_target_falls_to_finish(self):
        raw = "I'll use nonexistent_tool to do something."
        r = parse_llm_output(raw, tool_names=self.TOOLS)
        assert r.is_finish  # degrades to implicit finish

    def test_no_tool_names_disables_lenient(self):
        raw = "I'll use web_search to search."
        r = parse_llm_output(raw, tool_names=None)
        assert r.is_finish   # no tool_names → lenient disabled → implicit finish


# ═════════════════════════════════════════════════════════════════════════════
# 4. FAILED / implicit-finish degradation
# ═════════════════════════════════════════════════════════════════════════════

class TestParserFailed:
    def test_plain_prose_is_implicit_finish(self):
        raw = "This is a final answer with no format whatsoever."
        r = parse_llm_output(raw)
        assert r.is_finish
        assert r.quality == ParseQuality.FAILED
        assert raw in r.action_input.get("answer", "")

    def test_quality_failed_on_implicit_finish(self):
        raw = "I have no idea what to do here."
        r = parse_llm_output(raw, tool_names=frozenset({"web_search"}))
        assert r.quality == ParseQuality.FAILED
        assert r.is_finish


# ═════════════════════════════════════════════════════════════════════════════
# 5. diagnose()
# ═════════════════════════════════════════════════════════════════════════════

class TestDiagnose:
    def test_returns_string(self):
        r = parse_llm_output("Just some text.")
        assert isinstance(diagnose(r), str)

    def test_lenient_action_described(self):
        tools = frozenset({"web_search"})
        r = parse_llm_output("Using web_search for this.", tool_names=tools)
        msg = diagnose(r)
        assert "heuristic" in msg or "inferred" in msg

    def test_clean_output_says_correct(self):
        raw = (
            "Thought: ok\n"
            "Action: web_search\n"
            'Action Input: {"query": "x"}'
        )
        r = parse_llm_output(raw)
        msg = diagnose(r)
        assert "correct" in msg

    def test_missing_action_input_described(self):
        # Valid action but no Action Input → empty dict
        raw = "Thought: hmm\nAction: web_search"
        r = parse_llm_output(raw)
        msg = diagnose(r)
        # action_input is {} and not a finish
        assert "Action Input" in msg or "correct" in msg


# ═════════════════════════════════════════════════════════════════════════════
# 6. build_repair_prompt()
# ═════════════════════════════════════════════════════════════════════════════

class TestBuildRepairPrompt:
    def test_contains_raw_text(self):
        p = build_repair_prompt("bad output here", "missing Action", ["web_search"])
        assert "bad output here" in p

    def test_contains_diagnosis(self):
        p = build_repair_prompt("x", "missing Action field", ["web_search"])
        assert "missing Action field" in p

    def test_contains_tool_names(self):
        p = build_repair_prompt("x", "diag", ["web_search", "knowledge_save"])
        assert "web_search" in p
        assert "knowledge_save" in p

    def test_empty_tool_names_fallback(self):
        p = build_repair_prompt("x", "diag", [])
        assert "none registered" in p

    def test_bilingual(self):
        p = build_repair_prompt("x", "diag", ["tool_a"])
        assert "Rewrite" in p       # English
        assert "重写" in p           # Chinese


# ═════════════════════════════════════════════════════════════════════════════
# 7. repair()
# ═════════════════════════════════════════════════════════════════════════════

class TestRepairFunction:
    TOOLS = ["web_search", "knowledge_save"]

    def _llm(self, response: str) -> MagicMock:
        m = MagicMock()
        m.generate.return_value = response
        return m

    def test_returns_repaired_text_on_valid_output(self):
        fixed = (
            "Thought: I need to search.\n"
            "Action: web_search\n"
            'Action Input: {"query": "test"}'
        )
        result = repair(self._llm(fixed), "bad raw", "missing action", self.TOOLS)
        assert result == fixed

    def test_returns_none_on_empty_response(self):
        assert repair(self._llm(""), "bad raw", "diag", self.TOOLS) is None

    def test_returns_none_on_whitespace_response(self):
        assert repair(self._llm("   \n  "), "bad", "diag", self.TOOLS) is None

    def test_generate_called_exactly_once(self):
        fixed = (
            "Thought: ok\nAction: web_search\n"
            'Action Input: {"query": "test"}'
        )
        llm = self._llm(fixed)
        repair(llm, "bad raw", "diag", self.TOOLS)
        assert llm.generate.call_count == 1

    def test_propagates_llm_exception(self):
        llm = MagicMock()
        llm.generate.side_effect = RuntimeError("network error")
        raised = False
        try:
            repair(llm, "bad raw", "diag", self.TOOLS)
        except RuntimeError:
            raised = True
        assert raised, "repair() should propagate LLM exceptions"

    def test_repair_output_that_becomes_finish_is_accepted(self):
        # repair LLM returns a finish-style output — still useful
        fixed = (
            "Thought: I know.\n"
            "Action: finish\n"
            'Action Input: {"answer": "done"}'
        )
        result = repair(self._llm(fixed), "bad raw", "diag", self.TOOLS)
        assert result == fixed


# ═════════════════════════════════════════════════════════════════════════════
# 8. _infer_action() helper
# ═════════════════════════════════════════════════════════════════════════════

class TestInferAction:
    TOOLS = frozenset({"web_search", "knowledge_save", "tool_search"})

    def test_use_verb(self):
        assert _infer_action("I'll use web_search here", self.TOOLS) == "web_search"

    def test_using_verb(self):
        assert _infer_action("Using knowledge_save to save.", self.TOOLS) == "knowledge_save"

    def test_calling_verb(self):
        assert _infer_action("Calling tool_search now.", self.TOOLS) == "tool_search"

    def test_cjk_verb(self):
        assert _infer_action("调用 web_search 来查询", self.TOOLS) == "web_search"

    def test_first_line_bare_name(self):
        assert _infer_action("web_search\n{}", self.TOOLS) == "web_search"

    def test_unknown_tool_returns_empty(self):
        assert _infer_action("I'll use ghost_tool here", self.TOOLS) == ""

    def test_empty_text_returns_empty(self):
        assert _infer_action("", self.TOOLS) == ""

    def test_case_insensitive_verb(self):
        assert _infer_action("USING web_search for this", self.TOOLS) == "web_search"


# ═════════════════════════════════════════════════════════════════════════════
# 9. ActionExecutor — fuzzy tool name matching
# ═════════════════════════════════════════════════════════════════════════════

# Minimal BaseAction stand-in (no pydantic, no langchain needed for executor)
class _FakeAction:
    args_model = None
    model_fields = {"name": MagicMock(default="fake_tool")}

    def execute(self, **kwargs) -> str:
        return "fake result"


class TestExecutorFuzzyMatch:
    def _make_executor_with_instance(self, tool_name: str = "web_search") -> tuple[ActionExecutor, _FakeAction]:
        ex = ActionExecutor()
        action = _FakeAction()
        action.name = tool_name
        ex._instances[tool_name] = action
        return ex, action

    def test_exact_name_still_works(self):
        ex, _ = self._make_executor_with_instance("web_search")
        result = ex.run(json.dumps({"action": "web_search", "args": {}}))
        assert result == "fake result"

    def test_close_typo_corrected(self):
        ex, _ = self._make_executor_with_instance("web_search")
        # "web_serach" should fuzzy-match to "web_search" at cutoff 0.75
        result = ex.run(json.dumps({"action": "web_serach", "args": {}}))
        assert result == "fake result"

    def test_completely_unknown_name_returns_error(self):
        ex, _ = self._make_executor_with_instance("web_search")
        result = ex.run(json.dumps({"action": "fly_to_moon", "args": {}}))
        assert "未知工具" in result

    def test_short_name_below_cutoff_returns_error(self):
        ex, _ = self._make_executor_with_instance("web_search")
        result = ex.run(json.dumps({"action": "xyz", "args": {}}))
        assert "未知工具" in result

    def test_fuzzy_works_for_registry_class(self):
        ex = ActionExecutor()

        # Register a fake class in the registry dict directly
        class FakeToolClass(_FakeAction):
            model_fields = {"name": MagicMock(default="knowledge_save")}
            name = "knowledge_save"

            def execute(self, **kwargs):
                return "saved"

        ex._registry["knowledge_save"] = FakeToolClass
        # Typo: "knowlege_save" (missing 'd')
        result = ex.run(json.dumps({"action": "knowlege_save", "args": {}}))
        assert result == "saved"

    def test_available_actions_lists_all_registries(self):
        ex = ActionExecutor()
        act1 = _FakeAction(); act1.name = "tool_a"
        act2 = _FakeAction(); act2.name = "tool_b"
        ex._instances["tool_a"] = act1
        ex._instances["tool_b"] = act2
        available = ex.available_actions
        assert "tool_a" in available
        assert "tool_b" in available


# ═════════════════════════════════════════════════════════════════════════════
# 10. Three-layer chain: direct simulation
# ═════════════════════════════════════════════════════════════════════════════

class TestThreeLayerChain:
    """
    Simulates the exact branching logic from tao.py stream() to verify the
    three-layer chain behaves as expected, without instantiating TaoLoop.
    """

    TOOLS = frozenset({"web_search", "knowledge_save"})

    def _run_chain(
        self,
        raw: str,
        repair_response: str | None = "__skip__",
        retry_response: str | None = None,
        repair_enabled: bool = True,
        retry_budget: int = 1,
    ) -> dict:
        """
        Execute the three-layer chain and return a status dict.
        repair_response=None → repair LLM raises RuntimeError (simulate failure)
        repair_response="__skip__" → repair not set up (used when layer2 won't trigger)
        retry_response → text that would come from the retry LLM call
        """
        tool_names = self.TOOLS
        result = parse_llm_output(raw, tool_names=tool_names)

        triggered_l2 = False
        triggered_l0 = False

        # Layer 2
        if (
            result.quality == ParseQuality.FAILED
            and not result.is_finish
            and repair_enabled
        ):
            triggered_l2 = True
            if repair_response is None:
                pass  # simulate LLM failure → no repair
            elif repair_response != "__skip__":
                if repair_response.strip():
                    reparse = parse_llm_output(repair_response.strip(), tool_names=tool_names)
                    if reparse.quality != ParseQuality.FAILED or reparse.is_finish:
                        result = reparse

        # Layer 0
        if result.quality == ParseQuality.FAILED and not result.is_finish:
            for _ in range(retry_budget):
                triggered_l0 = True
                if retry_response:
                    result = parse_llm_output(retry_response, tool_names=tool_names)
                if result.quality != ParseQuality.FAILED or result.is_finish:
                    break

        return {
            "result": result,
            "l2": triggered_l2,
            "l0": triggered_l0,
        }

    def test_clean_parse_no_layers_triggered(self):
        raw = (
            "Thought: ok\nAction: web_search\n"
            'Action Input: {"query": "hello"}'
        )
        out = self._run_chain(raw)
        assert out["result"].quality == ParseQuality.CLEAN
        assert not out["l2"]
        assert not out["l0"]

    def test_lenient_parse_no_layers_triggered(self):
        raw = "Using web_search to find it."
        out = self._run_chain(raw)
        assert out["result"].quality == ParseQuality.LENIENT
        assert not out["l2"]
        assert not out["l0"]

    def test_implicit_finish_no_l2_triggered(self):
        # action="" → implicit finish (FAILED+is_finish=True) → Layer 2 guard
        # requires `not result.is_finish`, so L2 should NOT fire.
        raw = "I have no idea what to do."
        out = self._run_chain(raw)
        assert out["result"].is_finish
        assert not out["l2"]

    def test_l2_repair_succeeds_l0_not_triggered(self):
        # Simulate a scenario where parse returns FAILED+not_is_finish.
        # Directly build such a result to force L2 without relying on parser.
        fake_result = ParseResult(
            thought="", action="", action_input={},
            raw="bad", is_finish=False,
            quality=ParseQuality.FAILED,
        )
        repaired_raw = (
            "Thought: I'll search.\nAction: web_search\n"
            'Action Input: {"query": "test"}'
        )
        # Manually run the layer logic on a pre-built failed result
        tool_names = self.TOOLS
        triggered_l2 = False
        triggered_l0 = False

        if (
            fake_result.quality == ParseQuality.FAILED
            and not fake_result.is_finish
        ):
            triggered_l2 = True
            reparse = parse_llm_output(repaired_raw, tool_names=tool_names)
            if reparse.quality != ParseQuality.FAILED or reparse.is_finish:
                fake_result = reparse

        assert triggered_l2
        assert fake_result.quality == ParseQuality.CLEAN
        assert not triggered_l0

    def test_l2_fails_l0_fires_and_succeeds(self):
        retry_raw = (
            "Thought: retrying.\nAction: web_search\n"
            'Action Input: {"query": "retry"}'
        )
        fake_result = ParseResult(
            thought="", action="", action_input={},
            raw="bad", is_finish=False,
            quality=ParseQuality.FAILED,
        )
        tool_names = self.TOOLS
        triggered_l0 = False

        # L2 "fails" → no improvement
        # L0
        if fake_result.quality == ParseQuality.FAILED and not fake_result.is_finish:
            for _ in range(1):
                triggered_l0 = True
                fake_result = parse_llm_output(retry_raw, tool_names=tool_names)
                if fake_result.quality != ParseQuality.FAILED or fake_result.is_finish:
                    break

        assert triggered_l0
        assert fake_result.quality == ParseQuality.CLEAN

    def test_all_layers_fail_degrades_to_finish(self):
        # When all retries produce FAILED+is_finish, the loop exits and the
        # final result is the implicit finish (safe degradation).
        raw = "Complete gibberish with no format."
        out = self._run_chain(raw, repair_response=None, retry_response=None)
        assert out["result"].is_finish  # implicit finish = safe degradation

    def test_retry_budget_respected(self):
        # With budget=2 and both retries returning clean output, L0 fires once
        retry_raw = (
            "Thought: retrying.\nAction: web_search\n"
            'Action Input: {"query": "retry"}'
        )
        fake_result = ParseResult(
            thought="", action="", action_input={},
            raw="bad", is_finish=False,
            quality=ParseQuality.FAILED,
        )
        tool_names = self.TOOLS
        l0_count = 0

        if fake_result.quality == ParseQuality.FAILED and not fake_result.is_finish:
            for _ in range(2):
                l0_count += 1
                fake_result = parse_llm_output(retry_raw, tool_names=tool_names)
                if fake_result.quality != ParseQuality.FAILED or fake_result.is_finish:
                    break

        assert l0_count == 1      # breaks after first success
        assert fake_result.quality == ParseQuality.CLEAN


# ═════════════════════════════════════════════════════════════════════════════
# Entry point for direct execution
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    suites = [
        TestParseQualityEnum,
        TestParserClean,
        TestParserLenient,
        TestParserFailed,
        TestDiagnose,
        TestBuildRepairPrompt,
        TestRepairFunction,
        TestInferAction,
        TestExecutorFuzzyMatch,
        TestThreeLayerChain,
    ]

    passed = failed = 0
    for suite_cls in suites:
        suite = suite_cls()
        methods = sorted(m for m in dir(suite_cls) if m.startswith("test_"))
        for method in methods:
            label = f"{suite_cls.__name__}.{method}"
            try:
                getattr(suite, method)()
                print(f"  PASS  {label}")
                passed += 1
            except Exception:
                print(f"  FAIL  {label}")
                traceback.print_exc()
                failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
