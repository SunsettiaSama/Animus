"""
记忆模块集成测试
================
覆盖三层记忆的核心交互流程：

  短期记忆 (ShortTermMemory)
  ├── 容量满时驱逐最旧步骤
  ├── token 上限驱逐
  └── clear 后归零

  处理器 (MemoryProcessor) — 仅短期
  ├── recall 返回当前步骤
  └── commit / clear 不崩溃

  处理器 — 短期 + 中期 (mock LLM)
  ├── 驱逐步进入中期
  ├── 达到 distill_trigger_steps 时蒸馏被调用
  └── commit 触发 flush

  处理器 — 短期 + 中期 + 长期 (mock)
  ├── recall 返回三层聚合结果
  └── commit 写入长期并 save

不依赖任何外部服务（无 LLM API、无 FAISS/BGE、无磁盘写入）。
运行方式：
  cd G:/ReAct
  python -m pytest src/test/test_memory.py -v
  # 或直接：
  python src/test/test_memory.py
"""

from __future__ import annotations

import importlib.machinery
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# ── 必须在任何项目模块导入之前执行 ──────────────────────────────────────────────
#
# 问题：react/__init__.py 会 import TaoLoop，这触发了
#   tao.py → react.parser → langchain_core → transformers → (torch check)
# 以及
#   long_term/store.py → langchain_community（未安装）
#
# 解决：
#   1. 把 react 本身替换为一个"有路径的空壳包"，让 Python 跳过 __init__.py，
#      但仍能通过 __path__ 找到真正的子模块。
#   2. 对 langchain_community 打最小化的桩，让 store.py 顶层导入不崩溃。
# ────────────────────────────────────────────────────────────────────────────────

SRC = Path(__file__).resolve().parent.parent
REACT_DIR = SRC / "react"


def _pkg_stub(dotted_name: str, path: Path | None = None) -> types.ModuleType:
    """注册一个带 __path__ 的空壳包（让 Python 能继续加载其子模块）。"""
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
    """注册一个普通空壳模块（无子包）。"""
    m = types.ModuleType(dotted_name)
    m.__spec__ = importlib.machinery.ModuleSpec(dotted_name, loader=None)
    sys.modules[dotted_name] = m
    return m


# 1. react 包：跳过 __init__.py，但保留真实 __path__ 让子模块可寻
_pkg_stub("react", REACT_DIR)

# 2. langchain_community：未安装，桩住 store.py 依赖的两个子模块
_lc_comm = _pkg_stub("langchain_community")
_lc_emb  = _mod_stub("langchain_community.embeddings")
_lc_vs   = _mod_stub("langchain_community.vectorstores")
_lc_emb.HuggingFaceBgeEmbeddings = MagicMock(name="HuggingFaceBgeEmbeddings")
_lc_vs.FAISS                      = MagicMock(name="FAISS")
_lc_comm.embeddings               = _lc_emb
_lc_comm.vectorstores             = _lc_vs

# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, str(SRC))

from config.react.memory.short_term_config import ShortTermMemoryConfig
from config.react.memory.medium_term_config import MediumTermMemoryConfig
from config.react.memory.memory_config import MemoryConfig, LongTermMemoryConfig
from react.memory.memory import Step
from react.memory.short_term.memory import ShortTermMemory
from react.memory.processor import MemoryProcessor


# ─────────────────────────────────────────────
# 辅助工厂
# ─────────────────────────────────────────────

def make_step(n: int) -> Step:
    """生成编号为 n 的虚拟步骤。"""
    return Step(
        thought=f"thought_{n}",
        action=f"action_{n}",
        action_input={"k": n},
        observation=f"observation_{n}",
    )


def make_short_only_cfg(max_turns: int = 5, max_tokens: int = 4096) -> MemoryConfig:
    """只启用短期记忆的配置。"""
    return MemoryConfig(
        short_term=ShortTermMemoryConfig(enabled=True, max_turns=max_turns, max_tokens=max_tokens),
        medium_term=MediumTermMemoryConfig(enabled=False),
        long_term=LongTermMemoryConfig(enabled=False),
    )


def make_short_medium_cfg(
    max_turns: int = 3,
    max_tokens: int = 4096,
    distill_trigger: int = 2,
) -> MemoryConfig:
    """启用短期 + 中期记忆的配置（中期蒸馏触发步数较小，便于测试）。"""
    return MemoryConfig(
        short_term=ShortTermMemoryConfig(enabled=True, max_turns=max_turns, max_tokens=max_tokens),
        medium_term=MediumTermMemoryConfig(enabled=True, distill_trigger_steps=distill_trigger),
        long_term=LongTermMemoryConfig(enabled=False),
    )


def make_mock_llm(distillate: str = "[distilled content]") -> MagicMock:
    """返回带 generate() 的 mock LLM。"""
    llm = MagicMock()
    llm.generate.return_value = distillate
    return llm


def make_mock_long_term(recall_text: str = "[long-term recall]") -> MagicMock:
    """返回带 smart_recall / add / save 的 mock LongTermMemory。"""
    lt = MagicMock()
    lt.smart_recall.return_value = recall_text
    return lt


# ─────────────────────────────────────────────
# ShortTermMemory 单元测试
# ─────────────────────────────────────────────

def test_short_term_basic_add():
    """正常添加步骤，不触发驱逐。"""
    mem = ShortTermMemory(ShortTermMemoryConfig(enabled=True, max_turns=5, max_tokens=4096))
    for i in range(3):
        evicted = mem.add(make_step(i))
        assert evicted == [], f"step {i} should not be evicted"
    assert len(mem) == 3
    steps = mem.steps()
    assert steps[0].thought == "thought_0"
    assert steps[2].thought == "thought_2"
    print("[OK] test_short_term_basic_add")


def test_short_term_turn_eviction():
    """超过 max_turns 后最旧步骤被驱逐。"""
    mem = ShortTermMemory(ShortTermMemoryConfig(enabled=True, max_turns=3, max_tokens=4096))
    for i in range(3):
        mem.add(make_step(i))

    # 添加第 4 步 → 驱逐第 0 步
    evicted = mem.add(make_step(3))
    assert len(evicted) == 1
    assert evicted[0].thought == "thought_0", "oldest step should be evicted"
    assert len(mem) == 3
    remaining = [s.thought for s in mem.steps()]
    assert remaining == ["thought_1", "thought_2", "thought_3"]
    print("[OK] test_short_term_turn_eviction")


def test_short_term_token_eviction():
    """超过 max_tokens 时触发基于 token 的驱逐。"""
    # 默认 tokenizer 按空格分词；每个步骤约 ~8 tokens
    # 设定极小的 max_tokens 强制在第三步触发驱逐
    mem = ShortTermMemory(ShortTermMemoryConfig(enabled=True, max_turns=100, max_tokens=20))
    evicted_total = []
    for i in range(5):
        evicted = mem.add(make_step(i))
        evicted_total.extend(evicted)

    # token 上限被遵守
    assert mem.token_count <= 20, (
        f"token_count={mem.token_count} exceeds max_tokens=20"
    )
    # 有步骤被驱逐
    assert len(evicted_total) > 0, "some steps should have been evicted"
    print(f"  token_count={mem.token_count}, evicted={len(evicted_total)}")
    print("[OK] test_short_term_token_eviction")


def test_short_term_clear():
    """clear() 后状态归零。"""
    mem = ShortTermMemory(ShortTermMemoryConfig(enabled=True, max_turns=5, max_tokens=4096))
    for i in range(3):
        mem.add(make_step(i))
    mem.clear()
    assert len(mem) == 0
    assert mem.token_count == 0
    assert mem.steps() == []
    print("[OK] test_short_term_clear")


# ─────────────────────────────────────────────
# MemoryProcessor — 仅短期
# ─────────────────────────────────────────────

def test_processor_short_only_recall_empty():
    """未添加任何步骤时 recall 应返回空结果。"""
    proc = MemoryProcessor(make_short_only_cfg())
    result = proc.recall("anything")
    assert result.short_term == []
    assert result.medium_term == ""
    assert result.long_term == ""
    print("[OK] test_processor_short_only_recall_empty")


def test_processor_short_only_add_and_recall():
    """添加步骤后 recall 应反映当前短期窗口。"""
    proc = MemoryProcessor(make_short_only_cfg(max_turns=5))
    for i in range(3):
        proc.add(make_step(i))

    result = proc.recall("query")
    assert len(result.short_term) == 3
    assert result.short_term[0].thought == "thought_0"
    assert result.short_term[2].action == "action_2"
    assert result.medium_term == ""
    assert result.long_term == ""
    print("[OK] test_processor_short_only_add_and_recall")


def test_processor_short_only_window_slides():
    """短期窗口满后最旧步骤滑出，recall 只返回最新 max_turns 步。"""
    proc = MemoryProcessor(make_short_only_cfg(max_turns=3))
    for i in range(5):
        proc.add(make_step(i))

    result = proc.recall("q")
    thoughts = [s.thought for s in result.short_term]
    assert thoughts == ["thought_2", "thought_3", "thought_4"], (
        f"Expected last 3 steps, got: {thoughts}"
    )
    print("[OK] test_processor_short_only_window_slides")


def test_processor_commit_and_clear_no_crash():
    """commit / clear 在无中/长期记忆时不应崩溃。"""
    proc = MemoryProcessor(make_short_only_cfg())
    proc.add(make_step(0))
    proc.commit("question", "answer")  # 无 long_term，应安静退出
    proc.clear()
    assert proc.recall("q").short_term == []
    print("[OK] test_processor_commit_and_clear_no_crash")


def test_processor_trace_accumulates():
    """trace 属性应包含所有已添加步骤（不受短期窗口影响）。"""
    proc = MemoryProcessor(make_short_only_cfg(max_turns=2))
    for i in range(4):
        proc.add(make_step(i))

    # 短期窗口只保留最后 2 步
    assert len(proc.recall("q").short_term) == 2
    # trace 保留全部 4 步
    assert len(proc.trace) == 4
    assert proc.trace[0].thought == "thought_0"
    print("[OK] test_processor_trace_accumulates")


# ─────────────────────────────────────────────
# MemoryProcessor — 短期 + 中期 (mock LLM)
# ─────────────────────────────────────────────

def test_processor_medium_absorbs_evicted():
    """短期驱逐的步骤应进入中期记忆的 pending 队列。"""
    mock_llm = make_mock_llm()
    cfg = make_short_medium_cfg(max_turns=2, distill_trigger=100)  # trigger 高→不蒸馏
    proc = MemoryProcessor(cfg, llm=mock_llm)

    for i in range(4):
        proc.add(make_step(i))

    # 短期保留最后 2 步
    result = proc.recall("q")
    assert len(result.short_term) == 2
    assert result.short_term[0].thought == "thought_2"

    # LLM 尚未被调用（trigger 未达到）
    mock_llm.generate.assert_not_called()
    print("[OK] test_processor_medium_absorbs_evicted")


def test_processor_medium_distills_when_triggered():
    """驱逐步骤达到 distill_trigger_steps 后，LLM 应被调用进行蒸馏。"""
    mock_llm = make_mock_llm("[distilled summary]")
    cfg = make_short_medium_cfg(max_turns=2, distill_trigger=2)
    proc = MemoryProcessor(cfg, llm=mock_llm)

    # 添加 4 步：驱逐 step_0/step_1（共 2 步）→ 触发蒸馏
    for i in range(4):
        proc.add(make_step(i))

    # LLM generate 应被调用
    assert mock_llm.generate.call_count >= 1, "LLM should have been called to distill"
    print(f"  LLM.generate called {mock_llm.generate.call_count} time(s)")

    # medium_term 蒸馏结果应出现在 recall 中
    result = proc.recall("q")
    assert result.medium_term == "[distilled summary]", (
        f"Expected distillate, got: {result.medium_term!r}"
    )
    print("[OK] test_processor_medium_distills_when_triggered")


def test_processor_commit_flushes_medium():
    """commit 时应 flush 中期记忆（若有 pending 步骤则触发蒸馏）。"""
    mock_llm = make_mock_llm("[flushed distillate]")
    cfg = make_short_medium_cfg(max_turns=2, distill_trigger=100)  # 不自动触发
    proc = MemoryProcessor(cfg, llm=mock_llm)

    # 添加 3 步：step_0 被驱逐进中期 pending，但未达 trigger
    for i in range(3):
        proc.add(make_step(i))

    assert mock_llm.generate.call_count == 0, "Should not distill before commit"

    proc.commit("my question", "my answer")

    # commit → flush → LLM 被调用
    assert mock_llm.generate.call_count >= 1, "commit should flush and call LLM"
    print("[OK] test_processor_commit_flushes_medium")


# ─────────────────────────────────────────────
# MemoryProcessor — 含 mock LongTermMemory
# ─────────────────────────────────────────────

def test_processor_recall_includes_long_term():
    """recall 结果中应包含 LongTermMemory.smart_recall 的返回值。"""
    mock_llm = make_mock_llm()
    mock_lt = make_mock_long_term("[retrieved long-term knowledge]")

    cfg = make_short_only_cfg()
    cfg.medium_term.enabled = False
    # 注入 mock 长期记忆（不经过 init 逻辑）
    proc = MemoryProcessor(cfg, llm=None, long_term=mock_lt)

    proc.add(make_step(0))
    result = proc.recall("important query")

    mock_lt.smart_recall.assert_called_once()
    call_kwargs = mock_lt.smart_recall.call_args
    assert call_kwargs.kwargs["query"] == "important query" or call_kwargs.args[0] == "important query"

    assert result.long_term == "[retrieved long-term knowledge]"
    print("[OK] test_processor_recall_includes_long_term")


def test_processor_commit_writes_long_term():
    """commit 应向 LongTermMemory.add 写入摘要并调用 save。"""
    mock_lt = make_mock_long_term()
    cfg = make_short_only_cfg()
    proc = MemoryProcessor(cfg, llm=None, long_term=mock_lt)

    proc.add(make_step(0))
    proc.add(make_step(1))
    proc.commit("用户问了什么", "Agent 回答了什么")

    mock_lt.add.assert_called_once()
    written_text: str = mock_lt.add.call_args.args[0]
    assert "用户问了什么" in written_text, "question should appear in long-term entry"
    assert "Agent 回答了什么" in written_text, "answer should appear in long-term entry"
    assert "thought_0" in written_text, "step thought should be included in trace"

    mock_lt.save.assert_called_once()
    print("[OK] test_processor_commit_writes_long_term")


def test_processor_is_session_start_flag():
    """第一次 recall 应以 is_session_start=True 调用 smart_recall，之后为 False。"""
    mock_lt = make_mock_long_term()
    cfg = make_short_only_cfg()
    proc = MemoryProcessor(cfg, llm=None, long_term=mock_lt)

    proc.add(make_step(0))
    proc.recall("first")
    first_call_kwargs = mock_lt.smart_recall.call_args.kwargs
    assert first_call_kwargs.get("is_session_start") is True, (
        "First recall should set is_session_start=True"
    )

    proc.add(make_step(1))
    proc.recall("second")
    second_call_kwargs = mock_lt.smart_recall.call_args.kwargs
    assert second_call_kwargs.get("is_session_start") is False, (
        "Subsequent recalls should set is_session_start=False"
    )
    print("[OK] test_processor_is_session_start_flag")


def test_processor_clear_resets_session_flag():
    """clear() 后 is_session_start 应重置为 True。"""
    mock_lt = make_mock_long_term()
    cfg = make_short_only_cfg()
    proc = MemoryProcessor(cfg, llm=None, long_term=mock_lt)

    proc.recall("first")   # is_session_start → False
    proc.clear()
    proc.recall("after clear")

    calls = mock_lt.smart_recall.call_args_list
    assert calls[0].kwargs.get("is_session_start") is True
    assert calls[1].kwargs.get("is_session_start") is True, (
        "After clear(), is_session_start should reset to True"
    )
    print("[OK] test_processor_clear_resets_session_flag")


# ─────────────────────────────────────────────
# 场景测试：模拟多轮 Agent 推理流程
# ─────────────────────────────────────────────

def test_full_interaction_scenario():
    """
    模拟一个 Agent 完整推理会话：
      Round 1: 3 步 → commit
      Round 2: 2 步 → commit
    验证长期记忆写入两次、各含正确内容。
    """
    mock_llm = make_mock_llm("[medium distillate]")
    mock_lt  = make_mock_long_term("[recalled from past]")

    cfg = make_short_medium_cfg(max_turns=3, distill_trigger=100)
    proc = MemoryProcessor(cfg, llm=mock_llm, long_term=mock_lt)

    # ── Round 1 ──────────────────────────
    for i in range(3):
        proc.add(make_step(i))

    r1 = proc.recall("round-1 question")
    assert len(r1.short_term) == 3
    assert r1.long_term == "[recalled from past]"

    proc.commit("round-1 question", "round-1 answer")
    assert mock_lt.add.call_count == 1
    assert mock_lt.save.call_count == 1
    entry_r1: str = mock_lt.add.call_args_list[0].args[0]
    assert "round-1 question" in entry_r1
    assert "round-1 answer" in entry_r1

    proc.clear()

    # ── Round 2 ──────────────────────────
    for i in range(2):
        proc.add(make_step(i + 10))

    r2 = proc.recall("round-2 question")
    assert len(r2.short_term) == 2
    # clear 重置了 is_session_start，所以 smart_recall 应以 is_session_start=True 调用
    last_call = mock_lt.smart_recall.call_args.kwargs
    assert last_call.get("is_session_start") is True, (
        "After clear, round-2 first recall should be session_start=True"
    )

    proc.commit("round-2 question", "round-2 answer")
    assert mock_lt.add.call_count == 2
    assert mock_lt.save.call_count == 2
    entry_r2: str = mock_lt.add.call_args_list[1].args[0]
    assert "round-2 question" in entry_r2
    assert "round-2 answer" in entry_r2

    print("[OK] test_full_interaction_scenario")


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────

ALL_TESTS = [
    # ShortTermMemory
    test_short_term_basic_add,
    test_short_term_turn_eviction,
    test_short_term_token_eviction,
    test_short_term_clear,
    # MemoryProcessor — 仅短期
    test_processor_short_only_recall_empty,
    test_processor_short_only_add_and_recall,
    test_processor_short_only_window_slides,
    test_processor_commit_and_clear_no_crash,
    test_processor_trace_accumulates,
    # MemoryProcessor — 短期 + 中期
    test_processor_medium_absorbs_evicted,
    test_processor_medium_distills_when_triggered,
    test_processor_commit_flushes_medium,
    # MemoryProcessor — 含长期记忆
    test_processor_recall_includes_long_term,
    test_processor_commit_writes_long_term,
    test_processor_is_session_start_flag,
    test_processor_clear_resets_session_flag,
    # 场景测试
    test_full_interaction_scenario,
]


if __name__ == "__main__":
    print("=" * 60)
    print("  Memory Module Tests")
    print("=" * 60)
    passed = 0
    failed = 0
    for test_fn in ALL_TESTS:
        try:
            test_fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"  FAIL  {test_fn.__name__}")
            import traceback
            traceback.print_exc()
    print("=" * 60)
    print(f"  Result: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(1 if failed else 0)
