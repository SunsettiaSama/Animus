"""
����ģ�鼯�ɲ���
================
�����������ĺ��Ľ������̣�

  ���ڼ��� (ShortTermMemory)
  ������ ������ʱ������ɲ���
  ������ token ��������
  ������ clear �����

  ������ (MemoryProcessor) �� ������
  ������ recall ���ص�ǰ����
  ������ commit / clear ������

  ������ �� ���� + ���� (mock LLM)
  ������ ���𲽽�������
  ������ �ﵽ distill_trigger_steps ʱ���󱻵���
  ������ commit ���� flush

  ������ �� ���� + ���� + ���� (mock)
  ������ recall ��������ۺϽ��
  ������ commit д�볤�ڲ� save

�������κ��ⲿ������ LLM API���� Qdrant/BGE���޴���д�룩��
���з�ʽ��
  cd E:/ReAct
  python -m pytest src/test/test_memory.py -v
  # ��ֱ�ӣ�
  python src/test/test_memory.py
"""

from __future__ import annotations

import importlib.machinery
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# ���� �������κ���Ŀģ�鵼��֮ǰִ�� ��������������������������������������������������������������������������������������������
#
# ���⣺react/__init__.py �� import TaoLoop���ⴥ����
#   tao.py �� react.parser �� langchain_core �� transformers �� (torch check)
# �Լ�
#   long_term/store.py �� qdrant_client / embedding.embedder������������
#
# �����
#   1. �� react �����滻Ϊһ��"��·���Ŀտǰ�"���� Python ���� __init__.py��
#      ������ͨ�� __path__ �ҵ���������ģ�顣
#   2. �� qdrant_client �� embedding.embedder ����С����׮���� store.py ����
#      ���벻������
# ����������������������������������������������������������������������������������������������������������������������������������������������������������������

SRC = Path(__file__).resolve().parent.parent.parent
REACT_DIR = SRC / "agent" / "react"


def _pkg_stub(dotted_name: str, path: Path | None = None) -> types.ModuleType:
    """ע��һ���� __path__ �Ŀտǰ����� Python �ܼ�����������ģ�飩��"""
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
    """ע��һ����ͨ�տ�ģ�飨���Ӱ�����"""
    m = types.ModuleType(dotted_name)
    m.__spec__ = importlib.machinery.ModuleSpec(dotted_name, loader=None)
    sys.modules[dotted_name] = m
    return m


# 1. react �������� __init__.py����������ʵ __path__ ����ģ���Ѱ
_pkg_stub("agent.react", REACT_DIR)

# 2. qdrant_client��׮ס store.py ������ QdrantClient �� models
_qdrant = _pkg_stub("qdrant_client")
_qdrant_models = _mod_stub("qdrant_client.models")
_qdrant.QdrantClient = MagicMock(name="QdrantClient")
for _mn in ("Distance", "FieldCondition", "Filter", "FilterSelector",
            "MatchValue", "PointIdsList", "PointStruct", "VectorParams"):
    setattr(_qdrant_models, _mn, MagicMock(name=_mn))
_qdrant.models = _qdrant_models

# 3. embedding.embedder��׮ס Embedder �� infer_dim
_emb_pkg = _pkg_stub("embedding")
_emb_embedder = _mod_stub("embedding.embedder")
_emb_embedder.Embedder = MagicMock(name="Embedder")
_emb_embedder.infer_dim = MagicMock(name="infer_dim", return_value=512)
_emb_pkg.embedder = _emb_embedder

# ����������������������������������������������������������������������������������������������������������������������������������������������������������

sys.path.insert(0, str(SRC))

from config.agent.memory.medium_term_config import MediumTermMemoryConfig
from config.agent.memory.memory_config import MemoryConfig, LongTermMemoryConfig
from agent.react.context.memory import Step
from agent.react.context.processor import MemoryProcessor


# ������������������������������������������������������������������������������������������
# ��������
# ������������������������������������������������������������������������������������������

def make_step(n: int) -> Step:
    """���ɱ��Ϊ n �����ⲽ�衣"""
    return Step(
        thought=f"thought_{n}",
        action=f"action_{n}",
        action_input={"k": n},
        observation=f"observation_{n}",
    )


) -> MemoryConfig:
    """���ö��� + ���ڼ�������á�distill_on_write Ĭ�Ϲرգ�ʹ���ڲ����� LLM��"""
    return MemoryConfig(
        medium_term=MediumTermMemoryConfig(enabled=True, distill_on_write=distill_on_write),
        long_term=LongTermMemoryConfig(enabled=False),
    )


def make_mock_llm(distillate: str = "[distilled content]") -> MagicMock:
    """���ش� generate() �� mock LLM��"""
    llm = MagicMock()
    llm.generate.return_value = distillate
    return llm


def make_mock_long_term(recall_text: str = "[long-term recall]") -> MagicMock:
    """���ش� smart_recall / add / save �� mock LongTermMemory��"""
    lt = MagicMock()
    lt.smart_recall.return_value = recall_text
    return lt


def make_mock_medium(distillate: str = "") -> MagicMock:
    """���ش� append / render �� mock RecentHistoryMemory��"""
    medium = MagicMock()
    medium.render.return_value = distillate
    return medium


# ������������������������������������������������������������������������������������������
# ������������������������������������������������������������������������������������������

# ������������������������������������������������������������������������������������������
# MemoryProcessor �� ������
# ������������������������������������������������������������������������������������������

def test_processor_short_only_recall_empty():
    """δ�����κβ���ʱ recall Ӧ���ؿս����"""
    proc = MemoryProcessor(MemoryConfig(medium_term=MediumTermMemoryConfig(enabled=False), long_term=LongTermMemoryConfig(enabled=False)))
    result = proc.recall("anything")
    assert result.short_term == []
    assert result.medium_term == ""
    assert result.long_term == ""
    print("[OK] test_processor_short_only_recall_empty")


def test_processor_short_only_add_and_recall():
    """���Ӳ���� recall Ӧ��ӳ��ǰ���ڴ��ڡ�"""
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
    """���ڴ���������ɲ��軬����recall ֻ�������� max_turns ����"""
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
    """commit / clear ������/���ڼ���ʱ��Ӧ������"""
    proc = MemoryProcessor(MemoryConfig(medium_term=MediumTermMemoryConfig(enabled=False), long_term=LongTermMemoryConfig(enabled=False)))
    proc.add(make_step(0))
    proc.commit("question", "answer")  # �� long_term��Ӧ�����˳�
    proc.clear()
    assert proc.recall("q").short_term == []
    print("[OK] test_processor_commit_and_clear_no_crash")


def test_processor_trace_accumulates():
    """trace ����Ӧ�������������Ӳ��裨���ܶ��ڴ���Ӱ�죩��"""
    proc = MemoryProcessor(make_short_only_cfg(max_turns=2))
    for i in range(4):
        proc.add(make_step(i))

    # ���ڴ���ֻ������� 2 ��
    assert len(proc.recall("q").short_term) == 2
    # trace ����ȫ�� 4 ��
    assert len(proc.trace) == 4
    assert proc.trace[0].thought == "thought_0"
    print("[OK] test_processor_trace_accumulates")


# ������������������������������������������������������������������������������������������
# MemoryProcessor �� ���� + ���� (mock LLM)
# ������������������������������������������������������������������������������������������

def test_processor_medium_absorbs_evicted():
    """���ڴ��ڻ����������ڼ䲻���� LLM��commit ǰ medium.append �������á�"""
    mock_llm = make_mock_llm()
    mock_medium = make_mock_medium()
    cfg = make_short_medium_cfg(max_turns=2)
    proc = MemoryProcessor(cfg, llm=mock_llm, medium_term=mock_medium)

    for i in range(4):
        proc.add(make_step(i))

    # ���ڱ������ 2 ��
    result = proc.recall("q")
    assert len(result.short_term) == 2
    assert result.short_term[0].thought == "thought_2"

    # commit δ���� �� LLM δ�����á�medium.append δ������
    mock_llm.generate.assert_not_called()
    mock_medium.append.assert_not_called()
    print("[OK] test_processor_medium_absorbs_evicted")


def test_processor_medium_distills_when_triggered():
    """commit ʱ medium.append ������һ�Σ�mock render ����ժҪ��recall �п�ȡ����"""
    mock_medium = make_mock_medium("[distilled summary]")
    cfg = make_short_medium_cfg(max_turns=2)
    proc = MemoryProcessor(cfg, llm=make_mock_llm(), medium_term=mock_medium)

    for i in range(4):
        proc.add(make_step(i))

    proc.commit("question", "answer")

    # commit �� medium.append ������һ��
    mock_medium.append.assert_called_once_with("question", "answer")

    # recall �а��� medium_term render �ķ���ֵ
    result = proc.recall("q")
    assert result.medium_term == "[distilled summary]", (
        f"Expected distillate, got: {result.medium_term!r}"
    )
    print("[OK] test_processor_medium_distills_when_triggered")


def test_processor_commit_flushes_medium():
    """commit Ӧ���� medium.append ������ Q&A д�����ڼ��䡣"""
    mock_medium = make_mock_medium()
    cfg = make_short_medium_cfg(max_turns=2)
    proc = MemoryProcessor(cfg, llm=make_mock_llm(), medium_term=mock_medium)

    # ���� 3 ����commit ǰ��д����
    for i in range(3):
        proc.add(make_step(i))

    mock_medium.append.assert_not_called()

    proc.commit("my question", "my answer")

    # commit �� medium.append �����ã����뱾�� Q&A
    mock_medium.append.assert_called_once_with("my question", "my answer")
    print("[OK] test_processor_commit_flushes_medium")


# ������������������������������������������������������������������������������������������
# MemoryProcessor �� �� mock LongTermMemory
# ������������������������������������������������������������������������������������������

def test_processor_recall_includes_long_term():
    """recall �����Ӧ���� LongTermMemory.smart_recall �ķ���ֵ��"""
    mock_llm = make_mock_llm()
    mock_lt = make_mock_long_term("[retrieved long-term knowledge]")

    cfg = MemoryConfig(medium_term=MediumTermMemoryConfig(enabled=False), long_term=LongTermMemoryConfig(enabled=False))
    cfg.medium_term.enabled = False
    # ע�� mock ���ڼ��䣨������ init �߼���
    proc = MemoryProcessor(cfg, llm=None, long_term=mock_lt)

    proc.add(make_step(0))
    result = proc.recall("important query")

    mock_lt.smart_recall.assert_called_once()
    call_kwargs = mock_lt.smart_recall.call_args
    assert call_kwargs.kwargs["query"] == "important query" or call_kwargs.args[0] == "important query"

    assert result.long_term == "[retrieved long-term knowledge]"
    print("[OK] test_processor_recall_includes_long_term")


def test_processor_commit_writes_long_term():
    """commit Ӧ�� LongTermMemory.add д�� answer��distill_enabled=False Ĭ����Ϊ����
    question �� metadata ��ʽ���룬������ save��"""
    mock_lt = make_mock_long_term()
    cfg = MemoryConfig(medium_term=MediumTermMemoryConfig(enabled=False), long_term=LongTermMemoryConfig(enabled=False))
    proc = MemoryProcessor(cfg, llm=None, long_term=mock_lt)

    proc.add(make_step(0))
    proc.add(make_step(1))
    proc.commit("�û�����ʲô", "Agent �ش���ʲô")

    mock_lt.add.assert_called_once()
    written_text: str = mock_lt.add.call_args.args[0]
    # distill_enabled=False ʱд������Ϊ answer ԭ��
    assert "Agent �ش���ʲô" in written_text, "answer should appear in long-term entry"
    # question �� metadata ��ʽ���룬����������
    assert mock_lt.add.call_args.kwargs.get("question") == "�û�����ʲô", (
        "question should be passed as metadata kwarg"
    )

    mock_lt.save.assert_called_once()
    print("[OK] test_processor_commit_writes_long_term")


def test_processor_is_session_start_flag():
    """��һ�� recall Ӧ�� is_session_start=True ���� smart_recall��֮��Ϊ False��"""
    mock_lt = make_mock_long_term()
    cfg = MemoryConfig(medium_term=MediumTermMemoryConfig(enabled=False), long_term=LongTermMemoryConfig(enabled=False))
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
    """clear() �� is_session_start Ӧ����Ϊ True��"""
    mock_lt = make_mock_long_term()
    cfg = MemoryConfig(medium_term=MediumTermMemoryConfig(enabled=False), long_term=LongTermMemoryConfig(enabled=False))
    proc = MemoryProcessor(cfg, llm=None, long_term=mock_lt)

    proc.recall("first")   # is_session_start �� False
    proc.clear()
    proc.recall("after clear")

    calls = mock_lt.smart_recall.call_args_list
    assert calls[0].kwargs.get("is_session_start") is True
    assert calls[1].kwargs.get("is_session_start") is True, (
        "After clear(), is_session_start should reset to True"
    )
    print("[OK] test_processor_clear_resets_session_flag")


# ������������������������������������������������������������������������������������������
# �������ԣ�ģ����� Agent ��������
# ������������������������������������������������������������������������������������������

def test_full_interaction_scenario():
    """
    ģ��һ�� Agent ���������Ự��
      Round 1: 3 �� �� commit
      Round 2: 2 �� �� commit
    ��֤���ڼ���д�����Σ�answer Ϊ���ġ�question Ϊ metadata����
    ���� append ÿ�ָ�����һ�Ρ�
    """
    mock_llm = make_mock_llm("[medium distillate]")
    mock_lt  = make_mock_long_term("[recalled from past]")
    mock_medium = make_mock_medium("[medium render]")

    cfg = make_short_medium_cfg(max_turns=3)
    proc = MemoryProcessor(cfg, llm=mock_llm, long_term=mock_lt, medium_term=mock_medium)

    # ���� Round 1 ����������������������������������������������������
    for i in range(3):
        proc.add(make_step(i))

    r1 = proc.recall("round-1 question")
    assert len(r1.short_term) == 3
    assert r1.long_term == "[recalled from past]"

    proc.commit("round-1 question", "round-1 answer")
    assert mock_lt.add.call_count == 1
    assert mock_lt.save.call_count == 1
    entry_r1: str = mock_lt.add.call_args_list[0].args[0]
    # distill_enabled=False �� answer only in body
    assert "round-1 answer" in entry_r1
    assert mock_lt.add.call_args_list[0].kwargs.get("question") == "round-1 question"
    mock_medium.append.assert_called_once_with("round-1 question", "round-1 answer")

    proc.clear()

    # ���� Round 2 ����������������������������������������������������
    for i in range(2):
        proc.add(make_step(i + 10))

    r2 = proc.recall("round-2 question")
    assert len(r2.short_term) == 2
    # clear ������ is_session_start������ smart_recall Ӧ�� is_session_start=True ����
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


# ������������������������������������������������������������������������������������������
# LongTermStore ʱ�������Ԫ���ԣ��� FAISS��
# ������������������������������������������������������������������������������������������

def _make_long_term_store():
    """����һ�������� Qdrant / BGE �� LongTermStore�������أ�����������/���̣���"""
    from config.agent.memory.memory_config import LongTermMemoryConfig
    from agent.soul.memory.long_term.store import LongTermStore
    cfg = LongTermMemoryConfig(enabled=True, load_from_disk=False, memory_dir=".test_mem")
    return LongTermStore(entries=[], cfg=cfg)


def _inject_entries(store, texts: list[str]) -> None:
    """ֱ���� _entries �����α��ʱ����� MemoryEntry�������� FAISS��"""
    from agent.soul.memory.long_term.store import MemoryEntry
    from datetime import datetime, timezone, timedelta
    base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    for i, text in enumerate(texts):
        ts = (base + timedelta(hours=i)).isoformat()
        store._entries.append(MemoryEntry(id=str(i), text=text, created_at=ts))


def test_recall_timeline_order():
    """recall_timeline Ӧ�����루ʱ�䣩˳�򷵻أ��������� n ���ơ�"""
    store = _make_long_term_store()
    _inject_entries(store, ["alpha", "beta", "gamma", "delta", "epsilon"])

    pairs = store.recall_timeline(n=3)
    assert len(pairs) == 3
    # ��� 3 ����gamma / delta / epsilon����������˳��oldest first��
    texts = [t for _, t in pairs]
    assert texts == ["gamma", "delta", "epsilon"], f"Unexpected: {texts}"
    print("[OK] test_recall_timeline_order")


def test_recall_timeline_empty_store():
    """�� store �� recall_timeline Ӧ���ؿ��б�����������"""
    store = _make_long_term_store()
    assert store.recall_timeline(5) == []
    print("[OK] test_recall_timeline_empty_store")


def test_recall_timeline_n_larger_than_entries():
    """n > ��Ŀ����ʱӦ����ȫ����Ŀ��"""
    store = _make_long_term_store()
    _inject_entries(store, ["x", "y"])
    pairs = store.recall_timeline(n=10)
    assert len(pairs) == 2
    print("[OK] test_recall_timeline_n_larger_than_entries")


def test_recall_timeline_has_created_at():
    """ÿ������� created_at ӦΪ�ǿ� ISO �ַ�����"""
    store = _make_long_term_store()
    _inject_entries(store, ["hello", "world"])
    for created_at, _ in store.recall_timeline(2):
        assert created_at, "created_at should be non-empty"
        assert "T" in created_at or " " in created_at, (
            f"created_at looks invalid: {created_at!r}"
        )
    print("[OK] test_recall_timeline_has_created_at")


# ������������������������������������������������������������������������������������������
# LongTermMemory.recall_timeline ��ʽ����
# ������������������������������������������������������������������������������������������

def _make_long_term_memory():
    from config.agent.memory.memory_config import LongTermMemoryConfig
    from agent.soul.memory.long_term.store import LongTermStore
    from agent.soul.memory.long_term.memory import LongTermMemory
    cfg = LongTermMemoryConfig(enabled=True, load_from_disk=False, memory_dir=".test_mem")
    store = LongTermStore(entries=[], cfg=cfg)
    return LongTermMemory(store=store, cfg=cfg), store


def test_long_term_memory_recall_timeline_format():
    """recall_timeline ���ص��ַ���Ӧ�� [DATE] ǰ׺��ԭʼ�ı���"""
    mem, store = _make_long_term_memory()
    _inject_entries(store, ["�û�ϲ���Ȳ�", "�û���ϲ������"])

    result = mem.recall_timeline(n=2)
    assert result, "result should not be empty"
    assert "[2025-01-01" in result, f"Expected date prefix, got:\n{result}"
    assert "�û�ϲ���Ȳ�" in result
    assert "�û���ϲ������" in result
    print("[OK] test_long_term_memory_recall_timeline_format")


def test_long_term_memory_recall_timeline_empty():
    """�ռ��� recall_timeline Ӧ���ؿ��ַ�����"""
    mem, _ = _make_long_term_memory()
    assert mem.recall_timeline(5) == ""
    print("[OK] test_long_term_memory_recall_timeline_empty")


# ������������������������������������������������������������������������������������������
# triggers.py �� ģʽ��ⵥԪ����
# ������������������������������������������������������������������������������������������

def test_detect_mode_timeline_keywords():
    """��ʱ̬�ؼ��ʵĲ�ѯӦ���� TIMELINE ģʽ��"""
    from config.agent.memory.retrieve_config import RetrieveConfig
    from agent.soul.memory.long_term.retrieve.triggers import detect_mode
    from agent.soul.memory.long_term.retrieve.base import RetrieveMode

    cfg = RetrieveConfig()
    for kw in ["���������ʲô", "������ʲô��չ", "recently what happened", "last week"]:
        mode = detect_mode(kw, cfg)
        assert mode == RetrieveMode.TIMELINE, (
            f"Expected TIMELINE for {kw!r}, got {mode}"
        )
    print("[OK] test_detect_mode_timeline_keywords")


def test_detect_mode_heavy_keywords():
    """����ʷ����ؼ��ʵĲ�ѯӦ���� HEAVY ģʽ�����ȼ����� TIMELINE����"""
    from config.agent.memory.retrieve_config import RetrieveConfig
    from agent.soul.memory.long_term.retrieve.triggers import detect_mode
    from agent.soul.memory.long_term.retrieve.base import RetrieveMode

    cfg = RetrieveConfig()
    for kw in ["�㻹�ǵ��ϴ���˵��", "as i mentioned earlier"]:
        mode = detect_mode(kw, cfg)
        assert mode == RetrieveMode.HEAVY, (
            f"Expected HEAVY for {kw!r}, got {mode}"
        )
    print("[OK] test_detect_mode_heavy_keywords")


def test_detect_mode_profile_on_session_start():
    """�Ự����ʱӦ���� PROFILE ģʽ�����۲�ѯ������Ρ�"""
    from config.agent.memory.retrieve_config import RetrieveConfig
    from agent.soul.memory.long_term.retrieve.triggers import detect_mode
    from agent.soul.memory.long_term.retrieve.base import RetrieveMode

    cfg = RetrieveConfig()
    mode = detect_mode("���������ʲô", cfg, is_session_start=True)
    assert mode == RetrieveMode.PROFILE, f"Expected PROFILE, got {mode}"
    print("[OK] test_detect_mode_profile_on_session_start")


def test_detect_mode_light_default():
    """��ͨ��ѯ������ʷ/ʱ̬�ؼ���ʱӦ���� LIGHT ģʽ��"""
    from config.agent.memory.retrieve_config import RetrieveConfig
    from agent.soul.memory.long_term.retrieve.triggers import detect_mode
    from agent.soul.memory.long_term.retrieve.base import RetrieveMode

    cfg = RetrieveConfig(supplement_context_min_len=0)  # �ر� SUPPLEMENT ����
    mode = detect_mode("����� Python ��ȡ�ļ�", cfg)
    assert mode == RetrieveMode.LIGHT, f"Expected LIGHT, got {mode}"
    print("[OK] test_detect_mode_light_default")


# ������������������������������������������������������������������������������������������
# ���
# ������������������������������������������������������������������������������������������

ALL_TESTS = [
    # MemoryProcessor �� ������
    test_processor_short_only_recall_empty,
    test_processor_short_only_add_and_recall,
    test_processor_short_only_window_slides,
    test_processor_commit_and_clear_no_crash,
    test_processor_trace_accumulates,
    # MemoryProcessor �� ���� + ����
    test_processor_medium_absorbs_evicted,
    test_processor_medium_distills_when_triggered,
    test_processor_commit_flushes_medium,
    # MemoryProcessor �� �����ڼ���
    test_processor_recall_includes_long_term,
    test_processor_commit_writes_long_term,
    test_processor_is_session_start_flag,
    test_processor_clear_resets_session_flag,
    # ��������
    test_full_interaction_scenario,
    # LongTermStore ʱ�����
    test_recall_timeline_order,
    test_recall_timeline_empty_store,
    test_recall_timeline_n_larger_than_entries,
    test_recall_timeline_has_created_at,
    # LongTermMemory.recall_timeline
    test_long_term_memory_recall_timeline_format,
    test_long_term_memory_recall_timeline_empty,
    # triggers ģʽ���
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
