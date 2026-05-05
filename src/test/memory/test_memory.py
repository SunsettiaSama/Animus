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

不依赖任何外部服务（无 LLM API、无 Qdrant/BGE、无磁盘写入）。
运行方式：
  cd E:/ReAct
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
#   long_term/store.py → qdrant_client / embedding.embedder（重型依赖）
#
# 解决：
#   1. 把 react 本身替换为一个"有路径的空壳包"，让 Python 跳过 __init__.py，
#      但仍能通过 __path__ 找到真正的子模块。
#   2. 对 qdrant_client 和 embedding.embedder 打最小化的桩，让 store.py 顶层
#      导入不崩溃。
# ────────────────────────────────────────────────────────────────────────────────

SRC = Path(__file__).resolve().parent.parent.parent
REACT_DIR = SRC / "agent" / "react"


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
_pkg_stub("agent.react", REACT_DIR)

# 2. qdrant_client：桩住 store.py 依赖的 QdrantClient 和 models
_qdrant = _pkg_stub("qdrant_client")
_qdrant_models = _mod_stub("qdrant_client.models")
_qdrant.QdrantClient = MagicMock(name="QdrantClient")
for _mn in ("Distance", "FieldCondition", "Filter", "FilterSelector",
            "MatchValue", "PointIdsList", "PointStruct", "VectorParams"):
    setattr(_qdrant_models, _mn, MagicMock(name=_mn))
_qdrant.models = _qdrant_models

# 3. embedding.embedder：桩住 Embedder 和 infer_dim
_emb_pkg = _pkg_stub("embedding")
_emb_embedder = _mod_stub("embedding.embedder")
_emb_embedder.Embedder = MagicMock(name="Embedder")
_emb_embedder.infer_dim = MagicMock(name="infer_dim", return_value=512)
_emb_pkg.embedder = _emb_embedder

# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, str(SRC))

from config.agent.memory.short_term_config import ShortTermMemoryConfig
from config.agent.memory.medium_term_config import MediumTermMemoryConfig
from config.agent.memory.memory_config import MemoryConfig, LongTermMemoryConfig
from agent.react.memory.memory import Step
from agent.react.memory.short_term.memory import ShortTermMemory
from agent.react.memory.processor import MemoryProcessor


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
    distill_on_write: bool = False,
) -> MemoryConfig:
    """启用短期 + 中期记忆的配置。distill_on_write 默认关闭，使中期不依赖 LLM。"""
    return MemoryConfig(
        short_term=ShortTermMemoryConfig(enabled=True, max_turns=max_turns, max_tokens=max_tokens),
        medium_term=MediumTermMemoryConfig(enabled=True, distill_on_write=distill_on_write),
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


def make_mock_medium(distillate: str = "") -> MagicMock:
    """返回带 append / render 的 mock RecentHistoryMemory。"""
    medium = MagicMock()
    medium.render.return_value = distillate
    return medium


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
    """短期窗口滑动后，添加期间不调用 LLM；commit 前 medium.append 不被调用。"""
    mock_llm = make_mock_llm()
    mock_medium = make_mock_medium()
    cfg = make_short_medium_cfg(max_turns=2)
    proc = MemoryProcessor(cfg, llm=mock_llm, medium_term=mock_medium)

    for i in range(4):
        proc.add(make_step(i))

    # 短期保留最后 2 步
    result = proc.recall("q")
    assert len(result.short_term) == 2
    assert result.short_term[0].thought == "thought_2"

    # commit 未调用 → LLM 未被调用、medium.append 未被调用
    mock_llm.generate.assert_not_called()
    mock_medium.append.assert_not_called()
    print("[OK] test_processor_medium_absorbs_evicted")


def test_processor_medium_distills_when_triggered():
    """commit 时 medium.append 被调用一次；mock render 返回摘要，recall 中可取到。"""
    mock_medium = make_mock_medium("[distilled summary]")
    cfg = make_short_medium_cfg(max_turns=2)
    proc = MemoryProcessor(cfg, llm=make_mock_llm(), medium_term=mock_medium)

    for i in range(4):
        proc.add(make_step(i))

    proc.commit("question", "answer")

    # commit → medium.append 被调用一次
    mock_medium.append.assert_called_once_with("question", "answer")

    # recall 中包含 medium_term render 的返回值
    result = proc.recall("q")
    assert result.medium_term == "[distilled summary]", (
        f"Expected distillate, got: {result.medium_term!r}"
    )
    print("[OK] test_processor_medium_distills_when_triggered")


def test_processor_commit_flushes_medium():
    """commit 应调用 medium.append 将本轮 Q&A 写入中期记忆。"""
    mock_medium = make_mock_medium()
    cfg = make_short_medium_cfg(max_turns=2)
    proc = MemoryProcessor(cfg, llm=make_mock_llm(), medium_term=mock_medium)

    # 添加 3 步，commit 前不写中期
    for i in range(3):
        proc.add(make_step(i))

    mock_medium.append.assert_not_called()

    proc.commit("my question", "my answer")

    # commit → medium.append 被调用，传入本轮 Q&A
    mock_medium.append.assert_called_once_with("my question", "my answer")
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
    """commit 应向 LongTermMemory.add 写入 answer（distill_enabled=False 默认行为），
    question 以 metadata 方式传入，并调用 save。"""
    mock_lt = make_mock_long_term()
    cfg = make_short_only_cfg()
    proc = MemoryProcessor(cfg, llm=None, long_term=mock_lt)

    proc.add(make_step(0))
    proc.add(make_step(1))
    proc.commit("用户问了什么", "Agent 回答了什么")

    mock_lt.add.assert_called_once()
    written_text: str = mock_lt.add.call_args.args[0]
    # distill_enabled=False 时写入内容为 answer 原文
    assert "Agent 回答了什么" in written_text, "answer should appear in long-term entry"
    # question 以 metadata 方式传入，不在正文中
    assert mock_lt.add.call_args.kwargs.get("question") == "用户问了什么", (
        "question should be passed as metadata kwarg"
    )

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
    验证长期记忆写入两次（answer 为正文、question 为 metadata），
    中期 append 每轮各调用一次。
    """
    mock_llm = make_mock_llm("[medium distillate]")
    mock_lt  = make_mock_long_term("[recalled from past]")
    mock_medium = make_mock_medium("[medium render]")

    cfg = make_short_medium_cfg(max_turns=3)
    proc = MemoryProcessor(cfg, llm=mock_llm, long_term=mock_lt, medium_term=mock_medium)

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
    # distill_enabled=False → answer only in body
    assert "round-1 answer" in entry_r1
    assert mock_lt.add.call_args_list[0].kwargs.get("question") == "round-1 question"
    mock_medium.append.assert_called_once_with("round-1 question", "round-1 answer")

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
    assert "round-2 answer" in entry_r2
    assert mock_lt.add.call_args_list[1].kwargs.get("question") == "round-2 question"
    assert mock_medium.append.call_count == 2

    print("[OK] test_full_interaction_scenario")


# ─────────────────────────────────────────────
# LongTermStore 时序检索单元测试（无 FAISS）
# ─────────────────────────────────────────────

def _make_long_term_store():
    """构建一个不依赖 Qdrant / BGE 的 LongTermStore（懒加载，不触发网络/磁盘）。"""
    from config.agent.memory.memory_config import LongTermMemoryConfig
    from agent.react.memory.long_term.store import LongTermStore
    cfg = LongTermMemoryConfig(enabled=True, load_from_disk=False, memory_dir=".test_mem")
    return LongTermStore(entries=[], cfg=cfg)


def _inject_entries(store, texts: list[str]) -> None:
    """直接向 _entries 插入带伪造时间戳的 MemoryEntry，不经过 FAISS。"""
    from agent.react.memory.long_term.store import MemoryEntry
    from datetime import datetime, timezone, timedelta
    base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    for i, text in enumerate(texts):
        ts = (base + timedelta(hours=i)).isoformat()
        store._entries.append(MemoryEntry(id=str(i), text=text, created_at=ts))


def test_recall_timeline_order():
    """recall_timeline 应按插入（时间）顺序返回，且数量受 n 限制。"""
    store = _make_long_term_store()
    _inject_entries(store, ["alpha", "beta", "gamma", "delta", "epsilon"])

    pairs = store.recall_timeline(n=3)
    assert len(pairs) == 3
    # 最近 3 条：gamma / delta / epsilon（保留插入顺序，oldest first）
    texts = [t for _, t in pairs]
    assert texts == ["gamma", "delta", "epsilon"], f"Unexpected: {texts}"
    print("[OK] test_recall_timeline_order")


def test_recall_timeline_empty_store():
    """空 store 的 recall_timeline 应返回空列表，不崩溃。"""
    store = _make_long_term_store()
    assert store.recall_timeline(5) == []
    print("[OK] test_recall_timeline_empty_store")


def test_recall_timeline_n_larger_than_entries():
    """n > 条目总数时应返回全部条目。"""
    store = _make_long_term_store()
    _inject_entries(store, ["x", "y"])
    pairs = store.recall_timeline(n=10)
    assert len(pairs) == 2
    print("[OK] test_recall_timeline_n_larger_than_entries")


def test_recall_timeline_has_created_at():
    """每条结果的 created_at 应为非空 ISO 字符串。"""
    store = _make_long_term_store()
    _inject_entries(store, ["hello", "world"])
    for created_at, _ in store.recall_timeline(2):
        assert created_at, "created_at should be non-empty"
        assert "T" in created_at or " " in created_at, (
            f"created_at looks invalid: {created_at!r}"
        )
    print("[OK] test_recall_timeline_has_created_at")


# ─────────────────────────────────────────────
# LongTermMemory.recall_timeline 格式测试
# ─────────────────────────────────────────────

def _make_long_term_memory():
    from config.agent.memory.memory_config import LongTermMemoryConfig
    from agent.react.memory.long_term.store import LongTermStore
    from agent.react.memory.long_term.memory import LongTermMemory
    cfg = LongTermMemoryConfig(enabled=True, load_from_disk=False, memory_dir=".test_mem")
    store = LongTermStore(entries=[], cfg=cfg)
    return LongTermMemory(store=store, cfg=cfg), store


def test_long_term_memory_recall_timeline_format():
    """recall_timeline 返回的字符串应含 [DATE] 前缀和原始文本。"""
    mem, store = _make_long_term_memory()
    _inject_entries(store, ["用户喜欢喝茶", "用户不喜欢咖啡"])

    result = mem.recall_timeline(n=2)
    assert result, "result should not be empty"
    assert "[2025-01-01" in result, f"Expected date prefix, got:\n{result}"
    assert "用户喜欢喝茶" in result
    assert "用户不喜欢咖啡" in result
    print("[OK] test_long_term_memory_recall_timeline_format")


def test_long_term_memory_recall_timeline_empty():
    """空记忆 recall_timeline 应返回空字符串。"""
    mem, _ = _make_long_term_memory()
    assert mem.recall_timeline(5) == ""
    print("[OK] test_long_term_memory_recall_timeline_empty")


# ─────────────────────────────────────────────
# triggers.py — 模式检测单元测试
# ─────────────────────────────────────────────

def test_detect_mode_timeline_keywords():
    """含时态关键词的查询应触发 TIMELINE 模式。"""
    from config.agent.memory.retrieve_config import RetrieveConfig
    from agent.react.memory.long_term.retrieve.triggers import detect_mode
    from agent.react.memory.long_term.retrieve.base import RetrieveMode

    cfg = RetrieveConfig()
    for kw in ["最近发生了什么", "这周有什么进展", "recently what happened", "last week"]:
        mode = detect_mode(kw, cfg)
        assert mode == RetrieveMode.TIMELINE, (
            f"Expected TIMELINE for {kw!r}, got {mode}"
        )
    print("[OK] test_detect_mode_timeline_keywords")


def test_detect_mode_heavy_keywords():
    """含历史回忆关键词的查询应触发 HEAVY 模式（优先级低于 TIMELINE）。"""
    from config.agent.memory.retrieve_config import RetrieveConfig
    from agent.react.memory.long_term.retrieve.triggers import detect_mode
    from agent.react.memory.long_term.retrieve.base import RetrieveMode

    cfg = RetrieveConfig()
    for kw in ["你还记得上次我说的", "as i mentioned earlier"]:
        mode = detect_mode(kw, cfg)
        assert mode == RetrieveMode.HEAVY, (
            f"Expected HEAVY for {kw!r}, got {mode}"
        )
    print("[OK] test_detect_mode_heavy_keywords")


def test_detect_mode_profile_on_session_start():
    """会话启动时应触发 PROFILE 模式，无论查询内容如何。"""
    from config.agent.memory.retrieve_config import RetrieveConfig
    from agent.react.memory.long_term.retrieve.triggers import detect_mode
    from agent.react.memory.long_term.retrieve.base import RetrieveMode

    cfg = RetrieveConfig()
    mode = detect_mode("最近发生了什么", cfg, is_session_start=True)
    assert mode == RetrieveMode.PROFILE, f"Expected PROFILE, got {mode}"
    print("[OK] test_detect_mode_profile_on_session_start")


def test_detect_mode_light_default():
    """普通查询、无历史/时态关键词时应触发 LIGHT 模式。"""
    from config.agent.memory.retrieve_config import RetrieveConfig
    from agent.react.memory.long_term.retrieve.triggers import detect_mode
    from agent.react.memory.long_term.retrieve.base import RetrieveMode

    cfg = RetrieveConfig(supplement_context_min_len=0)  # 关闭 SUPPLEMENT 触发
    mode = detect_mode("如何用 Python 读取文件", cfg)
    assert mode == RetrieveMode.LIGHT, f"Expected LIGHT, got {mode}"
    print("[OK] test_detect_mode_light_default")


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
    # LongTermStore 时序检索
    test_recall_timeline_order,
    test_recall_timeline_empty_store,
    test_recall_timeline_n_larger_than_entries,
    test_recall_timeline_has_created_at,
    # LongTermMemory.recall_timeline
    test_long_term_memory_recall_timeline_format,
    test_long_term_memory_recall_timeline_empty,
    # triggers 模式检测
    test_detect_mode_timeline_keywords,
    test_detect_mode_heavy_keywords,
    test_detect_mode_profile_on_session_start,
    test_detect_mode_light_default,
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
