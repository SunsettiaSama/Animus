"""
Sub-Agent Event Forwarding Tests
=================================
Validates the event callback pipeline:
  SubAgentRunner.run_sync(event_callback) → DelegateTaskSkill._forward()
  → SubAgentXxxEvent → TaoLoop.sub_event_sink

All heavy dependencies are stubbed before importing from agent.react.tao.

Run:
  cd F:/ReAct
  python -m pytest src/test/delegate/test_sub_agent_events.py -v
"""
from __future__ import annotations

import importlib.machinery
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pkg_stub(dotted_name: str, path=None):
    m = types.ModuleType(dotted_name)
    m.__package__ = dotted_name
    m.__spec__ = importlib.machinery.ModuleSpec(dotted_name, loader=None, is_package=True)
    if path is not None:
        m.__path__ = [str(path)]
        m.__spec__.submodule_search_locations = m.__path__
    sys.modules[dotted_name] = m
    return m


def _mod_stub(dotted_name: str):
    m = types.ModuleType(dotted_name)
    m.__spec__ = importlib.machinery.ModuleSpec(dotted_name, loader=None)
    sys.modules[dotted_name] = m
    return m


def _mm_stub(dotted_name: str, **attrs):
    """MagicMock-backed module stub with given attributes."""
    m = _mod_stub(dotted_name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# ─────────────────────────────────────────────────────────────────────────────
#  Step 1 — pydantic stub (must come BEFORE any agent.react.* import)
# ─────────────────────────────────────────────────────────────────────────────

class _BaseModel:
    """Minimal pydantic.BaseModel replacement."""
    model_config = {}

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)

    def __init__(self, **kwargs):
        # Copy class-level annotation-backed defaults onto the instance.
        for base in reversed(type(self).__mro__):
            for attr_name in getattr(base, "__annotations__", {}):
                if attr_name.startswith("_"):
                    continue
                if attr_name in base.__dict__:
                    val = base.__dict__[attr_name]
                    if callable(val) or isinstance(val, (classmethod, staticmethod, property)):
                        continue
                    try:
                        object.__setattr__(self, attr_name, val)
                    except Exception:
                        pass
        for k, v in kwargs.items():
            object.__setattr__(self, k, v)


class _ValidationError(Exception):
    pass


_pydantic_mod = _pkg_stub("pydantic")
_pydantic_mod.BaseModel       = _BaseModel
_pydantic_mod.Field           = lambda *a, **kw: kw.get("default", None)
_pydantic_mod.ConfigDict      = dict
_pydantic_mod.ValidationError = _ValidationError
_pydantic_mod.field_validator = lambda *a, **kw: (lambda f: f)
_pydantic_mod.model_validator = lambda *a, **kw: (lambda f: f)
_mod_stub("pydantic.fields").FieldInfo = object

# ─────────────────────────────────────────────────────────────────────────────
#  Step 2 — langchain_core stub
# ─────────────────────────────────────────────────────────────────────────────

class _BaseTool(_BaseModel):
    name: str = ""
    description: str = ""

    def _run(self, *a, **kw): return ""
    async def _arun(self, *a, **kw): return ""


_lc_core      = _pkg_stub("langchain_core")
_lc_tools_mod = _mod_stub("langchain_core.tools")
_lc_msgs_mod  = _mod_stub("langchain_core.messages")
_lc_tools_mod.BaseTool = _BaseTool
for _cn in ("BaseMessage", "SystemMessage", "HumanMessage", "AIMessage"):
    setattr(_lc_msgs_mod, _cn,
            type(_cn, (), {"__init__": lambda self, content="", **kw: setattr(self, "content", content)}))
_lc_core.tools    = _lc_tools_mod
_lc_core.messages = _lc_msgs_mod

# langchain_community stubs (used by agent.react action manager)
_lc_comm = _pkg_stub("langchain_community")
_lce = _mod_stub("langchain_community.embeddings")
_lcv = _mod_stub("langchain_community.vectorstores")
_lcv.FAISS = MagicMock()
_lc_comm.embeddings   = _lce
_lc_comm.vectorstores = _lcv
_lc_hf = _pkg_stub("langchain_huggingface")
_lc_hf.HuggingFaceEmbeddings = MagicMock(name="HuggingFaceEmbeddings")

# ─────────────────────────────────────────────────────────────────────────────
#  Step 3 — Stub ALL module-level imports in agent/react/tao.py
#            so tao.py can load and its @dataclass definitions be exposed.
# ─────────────────────────────────────────────────────────────────────────────

_simple_stubs = {
    "infra.sandbox":                  dict(SandboxManager=MagicMock()),
    "llm_core.handle":                dict(LLMHandle=MagicMock()),
    "llm_core.llm":                   dict(LLM=MagicMock()),
    "config.agent.tao_config":        dict(TaoConfig=MagicMock()),
    "config.agent.prompt_config":     dict(PromptConfig=MagicMock()),
    "config.agent.memory.memory_config": dict(
        MemoryConfig=MagicMock(), LongTermMemoryConfig=MagicMock(),
    ),
    "config.agent.memory.medium_term_config": dict(MediumTermMemoryConfig=MagicMock()),
    "config.agent.risk_config":       dict(RiskConfig=MagicMock()),
    "runtime.scheduler.timeline":       dict(TimelineStore=MagicMock()),
    # agent.react.* that tao.py imports at module level
    "agent.react.action.executor":    dict(ActionExecutor=MagicMock()),
    "agent.react.action.risk.gate":   dict(RiskGate=MagicMock()),
    "agent.react.action.risk.level":  dict(RiskLevel=MagicMock(), OperationRisk=MagicMock()),
    "agent.react.action.tools.impl.memory_recall": dict(MemoryRecallAction=MagicMock()),
    "agent.react.action.tools.impl.knowledge_hybrid_search": dict(KnowledgeHybridSearchAction=MagicMock()),
    "agent.react.action.tools.impl.knowledge_save": dict(KnowledgeSaveAction=MagicMock()),
    "agent.react.action.tools.impl.knowledge_list": dict(KnowledgeListAction=MagicMock()),
    "agent.react.action.tools.impl.scratchpad": dict(
        NoteDeleteAction=MagicMock(), NoteReadAction=MagicMock(),
        NoteWriteAction=MagicMock(), ScratchpadStore=MagicMock(),
    ),
    "agent.react.action.skill.domain_learning": dict(DomainLearningSkill=MagicMock()),
    "agent.react.action.tools.impl.web_fetch":  dict(WebFetchAction=MagicMock()),
    "agent.react.action.tools.impl.web_search": dict(WebSearchAction=MagicMock()),
    "agent.soul.memory.long_term.init":         dict(make_memory=MagicMock()),
    "agent.soul.memory.long_term.memory":       dict(LongTermMemory=MagicMock()),
    "agent.react.context.medium_term.memory":    dict(RecentHistoryMemory=MagicMock()),
    "agent.react.context.memory":                dict(Step=MagicMock()),
    "agent.soul.memory.milestone.init":         dict(make_milestone=MagicMock()),
    "agent.soul.memory.milestone.memory":       dict(MilestoneMemory=MagicMock()),
    "agent.react.context.processor":             dict(MemoryProcessor=MagicMock(), MemoryResult=MagicMock()),
    "agent.react.prompt.block":                 dict(MemoryBlock=MagicMock(), PromptBlock=MagicMock()),
    "agent.react.prompt.parser":                dict(
        ParseQuality=MagicMock(), diagnose=MagicMock(), parse_llm_output=MagicMock(),
    ),
    "agent.react.prompt.repair":   dict(repair=MagicMock()),
    "agent.soul.persona":          dict(PersonaManager=MagicMock()),
    "agent.react.prompt.manager":  dict(PromptManager=MagicMock(), StaticPromptParts=MagicMock()),
    "agent.react.trace":           dict(TraceStore=MagicMock()),
}

for _mod_name, _attrs in _simple_stubs.items():
    _mm_stub(_mod_name, **_attrs)

# ─────────────────────────────────────────────────────────────────────────────
#  Step 4 — Now import event classes from the REAL tao.py
# ─────────────────────────────────────────────────────────────────────────────

import pytest
from agent.profile import SubAgentConfig, SubAgentProfile
from agent.result import SubAgentResult
from agent.react.tao import (
    ChunkEvent,
    StepEvent,
    FinishEvent,
    SubAgentStartEvent,
    SubAgentChunkEvent,
    SubAgentStepEvent,
    SubAgentFinishEvent,
    SubAgentErrorEvent,
)


# ═════════════════════════════════════════════════════════════════════════════
#  Class 1: TestSubAgentEventDataclasses — pure data structure validation
# ═════════════════════════════════════════════════════════════════════════════

class TestSubAgentEventDataclasses:
    def test_start_event(self):
        e = SubAgentStartEvent(action="delegate_task", instruction="do X")
        assert e.action == "delegate_task"
        assert e.instruction == "do X"

    def test_chunk_event(self):
        e = SubAgentChunkEvent(index=0, chunk="hello")
        assert e.index == 0
        assert e.chunk == "hello"

    def test_step_event_ok(self):
        e = SubAgentStepEvent(
            index=1, thought="think", action="web_search",
            action_input={"q": "test"}, observation="result",
        )
        assert not e.is_error
        assert e.action == "web_search"

    def test_step_event_error_flag(self):
        e = SubAgentStepEvent(
            index=2, thought="t", action="tool",
            action_input={}, observation="[工具执行错误] 404", is_error=True,
        )
        assert e.is_error

    def test_finish_event(self):
        assert SubAgentFinishEvent(answer="done").answer == "done"

    def test_error_event(self):
        assert SubAgentErrorEvent(error="boom").error == "boom"


# ═════════════════════════════════════════════════════════════════════════════
#  Class 2: TestRunnerEventCallback — run_sync(event_callback=...) transparency
# ═════════════════════════════════════════════════════════════════════════════

def _runner_fake_modules(mock_tao_mod):
    return {
        "config.llm_core.config":     MagicMock(),
        "config.agent.tao_config":    MagicMock(),
        "config.agent.prompt_config": MagicMock(),
        "llm_core.llm":               MagicMock(),
        "agent.react.action.manager": MagicMock(),
        "agent.react.tao":            mock_tao_mod,
    }


class TestRunnerEventCallback:
    def test_callback_receives_all_events(self):
        _StepEvent   = type("StepEvent",   (), {"index": 0, "thought": "t",
                                                "action": "a", "action_input": {},
                                                "observation": "ok"})
        _FinishEvent = type("FinishEvent", (), {"answer": "done"})
        step_ev   = _StepEvent()
        finish_ev = _FinishEvent()

        mock_tao = MagicMock()
        mock_tao.stream.return_value = [step_ev, finish_ev]
        mock_mod = MagicMock()
        mock_mod.TaoLoop.return_value = mock_tao
        mock_mod.FinishEvent = _FinishEvent
        mock_mod.StepEvent   = _StepEvent

        received = []
        with patch.dict(sys.modules, _runner_fake_modules(mock_mod)):
            sys.modules.pop("agent.runner", None)
            from agent.runner import SubAgentRunner
            runner = SubAgentRunner()
            runner.run_sync("task", SubAgentProfile(), "fake.yaml",
                            event_callback=received.append)

        assert len(received) == 2
        assert received[0] is step_ev
        assert received[1] is finish_ev

    def test_no_callback_does_not_raise(self):
        _FinishEvent = type("FinishEvent", (), {"answer": ""})
        _StepEvent   = type("StepEvent",   (), {})
        mock_tao = MagicMock()
        mock_tao.stream.return_value = [_FinishEvent()]
        mock_mod = MagicMock()
        mock_mod.TaoLoop.return_value = mock_tao
        mock_mod.FinishEvent = _FinishEvent
        mock_mod.StepEvent   = _StepEvent

        with patch.dict(sys.modules, _runner_fake_modules(mock_mod)):
            sys.modules.pop("agent.runner", None)
            from agent.runner import SubAgentRunner
            result = SubAgentRunner().run_sync("task", SubAgentProfile(), "fake.yaml")

        assert "answer" in result

    def test_callback_called_zero_times_when_stream_empty(self):
        _FinishEvent = type("FinishEvent", (), {"answer": ""})
        _StepEvent   = type("StepEvent",   (), {})
        mock_tao = MagicMock()
        mock_tao.stream.return_value = []
        mock_mod = MagicMock()
        mock_mod.TaoLoop.return_value = mock_tao
        mock_mod.FinishEvent = _FinishEvent
        mock_mod.StepEvent   = _StepEvent

        received = []
        with patch.dict(sys.modules, _runner_fake_modules(mock_mod)):
            sys.modules.pop("agent.runner", None)
            from agent.runner import SubAgentRunner
            SubAgentRunner().run_sync("task", SubAgentProfile(), "fake.yaml",
                                     event_callback=received.append)

        assert received == []


# ═════════════════════════════════════════════════════════════════════════════
#  Class 3: TestDelegateTaskSkillForwarding — _forward() mapping
# ═════════════════════════════════════════════════════════════════════════════

def _build_real_tao_mod():
    """Return a fake tao module exposing the REAL event classes (already imported)."""
    mod = types.ModuleType("agent.react.tao")
    mod.ChunkEvent          = ChunkEvent
    mod.StepEvent           = StepEvent
    mod.FinishEvent         = FinishEvent
    mod.SubAgentChunkEvent  = SubAgentChunkEvent
    mod.SubAgentStepEvent   = SubAgentStepEvent
    mod.SubAgentFinishEvent = SubAgentFinishEvent
    mod.SubAgentStartEvent  = SubAgentStartEvent
    mod.SubAgentErrorEvent  = SubAgentErrorEvent
    return mod


class TestDelegateTaskSkillForwarding:
    def _make_skill(self, sink):
        from agent.react.action.skill.delegate_task import DelegateTaskSkill
        skill = DelegateTaskSkill()
        skill.sub_event_sink = sink
        return skill

    def test_forward_chunk_maps_to_sub_chunk_event(self):
        tao_mod = _build_real_tao_mod()
        chunk_ev = ChunkEvent(index=3, chunk="abc")

        received = []
        with patch.dict(sys.modules, {"agent.react.tao": tao_mod}):
            skill = self._make_skill(received.append)
            skill._forward(chunk_ev)

        assert len(received) == 1
        assert isinstance(received[0], SubAgentChunkEvent)
        assert received[0].index == 3
        assert received[0].chunk == "abc"

    def test_forward_step_normal_is_error_false(self):
        tao_mod = _build_real_tao_mod()
        step_ev = StepEvent(
            index=0, thought="thinking", action="web_search",
            action_input={"query": "test"}, observation="some result",
        )

        received = []
        with patch.dict(sys.modules, {"agent.react.tao": tao_mod}):
            skill = self._make_skill(received.append)
            skill._forward(step_ev)

        assert len(received) == 1
        assert isinstance(received[0], SubAgentStepEvent)
        assert not received[0].is_error
        assert received[0].action == "web_search"

    def test_forward_step_error_prefix_sets_is_error_true(self):
        tao_mod = _build_real_tao_mod()
        step_ev = StepEvent(
            index=1, thought="t", action="tool",
            action_input={}, observation="[工具执行错误] connection refused",
        )

        received = []
        with patch.dict(sys.modules, {"agent.react.tao": tao_mod}):
            skill = self._make_skill(received.append)
            skill._forward(step_ev)

        assert received[0].is_error

    def test_forward_finish_maps_to_sub_finish_event(self):
        tao_mod = _build_real_tao_mod()
        fin_ev = FinishEvent(answer="final answer")

        received = []
        with patch.dict(sys.modules, {"agent.react.tao": tao_mod}):
            skill = self._make_skill(received.append)
            skill._forward(fin_ev)

        assert len(received) == 1
        assert isinstance(received[0], SubAgentFinishEvent)
        assert received[0].answer == "final answer"

    def test_forward_noop_when_sink_is_none(self):
        tao_mod = _build_real_tao_mod()
        chunk_ev = ChunkEvent(index=0, chunk="x")

        with patch.dict(sys.modules, {"agent.react.tao": tao_mod}):
            from agent.react.action.skill.delegate_task import DelegateTaskSkill
            skill = DelegateTaskSkill()
            skill.sub_event_sink = None
            skill._forward(chunk_ev)  # must not raise

    def test_execute_emits_error_event_on_exception(self):
        tao_mod = _build_real_tao_mod()

        mock_runner = MagicMock()
        mock_runner.run_sync.side_effect = RuntimeError("kaboom")
        mock_cfg = MagicMock()
        mock_cfg.profiles.get.return_value = SubAgentProfile()
        mock_cfg.llm_cfg_path = "fake.yaml"

        received = []
        with patch.dict(sys.modules, {"agent.react.tao": tao_mod}):
            from agent.react.action.skill.delegate_task import DelegateTaskSkill
            skill = DelegateTaskSkill(runner=mock_runner, cfg=mock_cfg)
            skill.sub_event_sink = received.append

            with pytest.raises(RuntimeError, match="kaboom"):
                skill.execute("do it", profile="minimal")

        error_events = [e for e in received if isinstance(e, SubAgentErrorEvent)]
        assert len(error_events) == 1
        assert "kaboom" in error_events[0].error

    def test_execute_emits_start_event_before_run(self):
        tao_mod = _build_real_tao_mod()

        mock_runner = MagicMock()
        mock_runner.run_sync.return_value = {"answer": "ok", "step_count": 0, "steps_log": []}
        mock_cfg = MagicMock()
        mock_cfg.profiles.get.return_value = SubAgentProfile()
        mock_cfg.llm_cfg_path = "fake.yaml"

        received = []
        with patch.dict(sys.modules, {"agent.react.tao": tao_mod}):
            from agent.react.action.skill.delegate_task import DelegateTaskSkill
            skill = DelegateTaskSkill(runner=mock_runner, cfg=mock_cfg)
            skill.sub_event_sink = received.append
            skill.execute("do it", profile="minimal")

        assert isinstance(received[0], SubAgentStartEvent)
        assert received[0].instruction == "do it"


# ═════════════════════════════════════════════════════════════════════════════
#  Class 4: TestTaoLoopSinkInjection — sub_event_sink property propagation
# ═════════════════════════════════════════════════════════════════════════════

class TestTaoLoopSinkInjection:
    """Uses stub loop + stub delegate to verify sink propagation logic
    (mirrors the real TaoLoop.sub_event_sink property exactly)."""

    class _StubDelegate:
        def __init__(self):
            self.sub_event_sink = None

    def _stub_loop(self):
        delegate = self._StubDelegate()

        class _StubLoop:
            def __init__(self, d):
                self._delegate_skill = d
                self._sub_event_sink = None

            @property
            def sub_event_sink(self):
                return self._sub_event_sink

            @sub_event_sink.setter
            def sub_event_sink(self, sink):
                self._sub_event_sink = sink
                if self._delegate_skill is not None:
                    self._delegate_skill.sub_event_sink = sink

        return _StubLoop(delegate), delegate

    def test_sink_propagates_to_delegate_skill(self):
        loop, delegate = self._stub_loop()
        sink = MagicMock()
        loop.sub_event_sink = sink
        assert delegate.sub_event_sink is sink

    def test_sink_clear_sets_none_on_skill(self):
        loop, delegate = self._stub_loop()
        loop.sub_event_sink = MagicMock()
        loop.sub_event_sink = None
        assert delegate.sub_event_sink is None

    def test_sink_getter_returns_current_value(self):
        loop, _ = self._stub_loop()
        assert loop.sub_event_sink is None
        sentinel = object()
        loop.sub_event_sink = sentinel
        assert loop.sub_event_sink is sentinel

    def test_no_delegate_skill_does_not_raise(self):
        """When _delegate_skill is None, setting sink must not raise."""
        class _NullLoop:
            def __init__(self):
                self._delegate_skill = None
                self._sub_event_sink = None

            @property
            def sub_event_sink(self):
                return self._sub_event_sink

            @sub_event_sink.setter
            def sub_event_sink(self, sink):
                self._sub_event_sink = sink
                if self._delegate_skill is not None:
                    self._delegate_skill.sub_event_sink = sink

        loop = _NullLoop()
        loop.sub_event_sink = MagicMock()  # must not raise


# ═════════════════════════════════════════════════════════════════════════════
#  Direct runner
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    suites = [
        TestSubAgentEventDataclasses,
        TestRunnerEventCallback,
        TestDelegateTaskSkillForwarding,
        TestTaoLoopSinkInjection,
    ]
    passed = failed = 0
    for suite_cls in suites:
        suite = suite_cls()
        methods = [m for m in dir(suite) if m.startswith("test_")]
        for name in methods:
            try:
                getattr(suite, name)()
                print(f"  PASS  {suite_cls.__name__}.{name}")
                passed += 1
            except Exception:
                print(f"  FAIL  {suite_cls.__name__}.{name}")
                traceback.print_exc()
                failed += 1
    print(f"\nResult: {passed} passed, {failed} failed")
