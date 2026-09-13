"""3.3 可替换记忆基座：graph（event/social 双网）/ stack（增量旁路）/ none。

三者都满足 ``MemoryBasePort``（ingest / recall / search），
供 harness 在同一批用例上换基座对比回复行为。
"""
from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

from agent.soul.memory.graph.networks.block import MemoryBlock

from .schema import MemorySeed

log = logging.getLogger("evals.memory_humaneness")


def _temp_jsonl() -> str:
    return str(Path(tempfile.mkdtemp(prefix="memory_bench_stack_")) / "stack_memory.jsonl")


class GraphMemoryBase:
    """graph 基座：MemoryService（event/social 双网 + 可选向量）。"""

    kind = "graph"

    def __init__(self, service, *, close_at_exit: bool = False) -> None:
        self._svc = service
        self._close_at_exit = close_at_exit

    @classmethod
    def build(cls, *, json_root: str | None = None) -> "GraphMemoryBase":
        from agent.soul.memory.service import MemoryService

        root = json_root or tempfile.mkdtemp(prefix="memory_bench_graph_")
        t0 = time.perf_counter()
        svc = MemoryService.build(
            llm=None,
            storage_backend="json",
            json_root=root,
        )
        log.info("graph 基座构建完成（json_root=%s，%.1fs）", root, time.perf_counter() - t0)
        return cls(svc, close_at_exit=True)

    @property
    def service(self):
        return self._svc

    def ingest(self, text: str, *, focus: str = "", emotion: str = "",
               valence: str = "neutral", interactor_id: str = "",
               tags: list[str] | None = None, meta: dict | None = None,
               days_ago: float | None = None) -> str:
        node = self._svc.ingest_fact(
            text,
            focus=focus,
            emotion=emotion,
            valence=valence,
            interactor_id=interactor_id,
            days_ago=days_ago,
            meta=meta,
        )
        return node.id

    def recall(self, query: str, top_k: int = 5, emotional_context: str = "") -> MemoryBlock:
        return self._svc.recall(query, top_k=top_k, emotional_context=emotional_context)

    def search(self, mode: str, **kwargs) -> list[dict]:
        return self._svc.search(mode, **kwargs)

    def dispose(self) -> None:
        pass


class StackMemoryBase:
    """stack 基座：增量式旁路（与 event/social 隔离）。"""

    kind = "stack"

    def __init__(self, service, *, jsonl_path: str = "") -> None:
        self._svc = service
        self._jsonl_path = jsonl_path

    @classmethod
    def build(cls, *, jsonl_path: str | None = None, max_entries: int = 2000) -> "StackMemoryBase":
        from agent.soul.memory.bypass import StackMemoryService

        path = jsonl_path or _temp_jsonl()
        return cls(StackMemoryService(path, max_entries=max_entries), jsonl_path=path)

    @property
    def service(self):
        return self._svc

    def ingest(self, text: str, *, focus: str = "", emotion: str = "",
               valence: str = "neutral", interactor_id: str = "",
               tags: list[str] | None = None, meta: dict | None = None,
               days_ago: float | None = None) -> str:
        return self._svc.ingest(
            text,
            focus=focus,
            emotion=emotion,
            valence=valence,
            interactor_id=interactor_id,
            tags=tags,
            meta=meta,
            days_ago=days_ago,
        )

    def recall(self, query: str, top_k: int = 5, emotional_context: str = "") -> MemoryBlock:
        return self._svc.recall(query, top_k=top_k, emotional_context=emotional_context)

    def search(self, mode: str, **kwargs) -> list[dict]:
        return self._svc.search(mode, **kwargs)

    def dispose(self) -> None:
        pass


class NullMemoryBase:
    """none 基座：无长期记忆对照组（协议兼容，全部返回空）。"""

    kind = "none"

    def ingest(self, text: str, **kwargs) -> str:  # noqa: D401
        return ""

    def recall(self, query: str, top_k: int = 5, emotional_context: str = "") -> MemoryBlock:
        return MemoryBlock(label="记忆", entries=[])

    def search(self, mode: str, **kwargs) -> list[dict]:
        return []

    def dispose(self) -> None:
        pass


class FullMemoryBase:
    """全量注入基座（裸记忆）：不做任何检索，全部记忆原文按时间序进入上下文。

    作为检索类基座的信息上界参照——检索命中不了的东西它全都有，
    但无关记忆也一并进入 prompt（考察噪声与长上下文的代价）。
    ``recall`` 与查询无关，``top_k`` 被忽略。
    """

    kind = "full"

    def __init__(self) -> None:
        self._texts: list[str] = []

    def ingest(self, text: str, *, focus: str = "", emotion: str = "",
               valence: str = "neutral", interactor_id: str = "",
               tags: list[str] | None = None, meta: dict | None = None,
               days_ago: float | None = None) -> str:
        self._texts.append(str(text))
        return f"full-{len(self._texts) - 1}"

    def recall(self, query: str, top_k: int = 5, emotional_context: str = "") -> MemoryBlock:
        entries = [f"[{i}] {text}" for i, text in enumerate(self._texts)]
        return MemoryBlock(label="全部记忆（未检索）", entries=entries)

    def search(self, mode: str, **kwargs) -> list[dict]:
        return [{"id": f"full-{i}", "content": t, "final_score": 1.0}
                for i, t in enumerate(self._texts)]

    def dispose(self) -> None:
        pass


class CompactMemoryBase:
    """长上下文压缩基座：记忆按时间进入上下文，超预算后旧记忆压缩为截断摘要。

    模拟“上下文一直堆、长了就压缩、只保留近期原文”的上下文管理策略：
    最近 ``keep_recent`` 条保留原文，更早的每条压缩为前 ``digest_chars`` 字的摘要。
    ``recall`` 与查询无关（压缩是上下文管理，不是检索）——因此它天然回答
    “旧信息在压缩后还剩多少可用”，信息保真度由 L2 检索基准度量。
    """

    kind = "compact"

    def __init__(self, *, keep_recent: int = 1, digest_chars: int = 24) -> None:
        self._texts: list[str] = []
        self._keep_recent = max(0, int(keep_recent))
        self._digest_chars = max(8, int(digest_chars))

    def ingest(self, text: str, *, focus: str = "", emotion: str = "",
               valence: str = "neutral", interactor_id: str = "",
               tags: list[str] | None = None, meta: dict | None = None,
               days_ago: float | None = None) -> str:
        self._texts.append(str(text))
        return f"compact-{len(self._texts) - 1}"

    def recall(self, query: str, top_k: int = 5, emotional_context: str = "") -> MemoryBlock:
        texts = self._texts
        cut = max(0, len(texts) - self._keep_recent)
        entries: list[str] = []
        for i, text in enumerate(texts[:cut]):
            entries.append(f"[已压缩] {text[:self._digest_chars]}…")
        for i, text in enumerate(texts[cut:], start=cut):
            entries.append(f"[近期] {text}")
        return MemoryBlock(label="压缩上下文", entries=entries)

    def search(self, mode: str, **kwargs) -> list[dict]:
        cut = max(0, len(self._texts) - self._keep_recent)
        return [
            {"id": f"compact-{i}", "content": t,
             "final_score": 1.0 if i >= cut else 0.4}
            for i, t in enumerate(self._texts)
        ]

    def dispose(self) -> None:
        pass

    def dispose(self) -> None:
        pass


def preload(base, seeds: list[MemorySeed]) -> None:
    """把用例的预载记忆写进基座（回填时间戳保证 recency 公平）。"""
    if not seeds:
        return
    t0 = time.perf_counter()
    for seed in seeds:
        base.ingest(
            seed.text,
            focus=seed.focus,
            emotion=seed.emotion,
            valence=seed.valence,
            tags=list(seed.tags),
            days_ago=seed.days_ago,
        )
    log.debug(
        "%s 基座预载 %d 条记忆（%.2fs）", getattr(base, "kind", "?"), len(seeds),
        time.perf_counter() - t0,
    )
