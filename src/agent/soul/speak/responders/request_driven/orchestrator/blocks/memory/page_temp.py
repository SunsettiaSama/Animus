from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any

from agent.soul.speak.responders.request_driven.composer.ports.memory import (
    MemoryUnit,
)


@dataclass(frozen=True)
class PageTempGeneration:
    """一页会话上下文注入的一代临时记忆。"""

    generation: int
    page_key: str
    units: tuple[MemoryUnit, ...]


@dataclass
class PageTempMemoryRing:
    """页面临时记忆环：最多保留两代（当前 + 上一代）；更旧的清除。"""

    max_generations: int = 2
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _by_session: dict[str, list[PageTempGeneration]] = field(default_factory=dict)
    _seq: dict[str, int] = field(default_factory=dict)

    def enter_page(
        self,
        session_id: str,
        *,
        page_key: str,
        lines: list[str],
    ) -> PageTempGeneration:
        sid = session_id.strip()
        key = page_key.strip() or "page"
        with self._lock:
            seq = int(self._seq.get(sid, 0)) + 1
            self._seq[sid] = seq
            units = tuple(self._lines_to_units(sid, seq, key, lines))
            gen = PageTempGeneration(generation=seq, page_key=key, units=units)
            ring = list(self._by_session.get(sid) or [])
            # 同 page_key 再进：替换该页旧代，不额外占槽
            ring = [g for g in ring if g.page_key != key]
            ring.append(gen)
            keep = max(1, int(self.max_generations))
            if len(ring) > keep:
                ring = ring[-keep:]
            self._by_session[sid] = ring
            return gen

    def generations(self, session_id: str) -> list[PageTempGeneration]:
        sid = session_id.strip()
        with self._lock:
            return list(self._by_session.get(sid) or [])

    def all_units(self, session_id: str) -> list[MemoryUnit]:
        out: list[MemoryUnit] = []
        for gen in self.generations(session_id):
            out.extend(gen.units)
        return out

    def clear(self, session_id: str) -> None:
        sid = session_id.strip()
        with self._lock:
            self._by_session.pop(sid, None)
            self._seq.pop(sid, None)

    def snapshot(self, session_id: str) -> dict[str, Any]:
        gens = self.generations(session_id)
        return {
            "count": len(gens),
            "generations": [
                {
                    "generation": g.generation,
                    "page_key": g.page_key,
                    "unit_count": len(g.units),
                    "unit_ids": [u.unit_id for u in g.units],
                }
                for g in gens
            ],
        }

    def _lines_to_units(
        self,
        session_id: str,
        generation: int,
        page_key: str,
        lines: list[str],
    ) -> list[MemoryUnit]:
        units: list[MemoryUnit] = []
        for i, raw in enumerate(lines):
            text = str(raw or "").strip()
            if not text:
                continue
            uid = f"page_temp:{session_id}:{generation}:{page_key}:{i}"
            units.append(
                MemoryUnit(
                    unit_id=uid,
                    text=text,
                    source="page_temp",
                    score=1.0,
                )
            )
        return units
