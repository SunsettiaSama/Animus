"""剧情预热编排：后台异步生成候选大纲，灌入 StoryMaterialPool。

生成方式（复用现有编剧产出代码，零新 LLM 代码）：
- 全量候选：`Screenwriter.init_presence(background_agent=False)` —— 走
  编剧 Agent 同步产出（多步 LLM，秒级）；
- 骨架候选：`init_presence(background_agent=True, upgrade_agent=False)` ——
  纯启发式落盘，无 LLM；被消费时若嫌糙由编剧正常 upgrade 流程接管。

生成写入**临时 SessionSchedulingState**（scratch），不触碰任何在途回话；
收集 snapshot 后组装 StoryPoolEntry。预算护栏：池内 fresh 条目已达
`pool_depth` 时跳过；同一 key 同时只允许一个预热线程。
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from ..orchestrator.state.runtime.store import SessionSchedulingState
from .pool import StoryMaterialPool, StoryPoolEntry


def _entry_from_state(
    state: SessionSchedulingState, *, full: bool, opening: str, seed_note: str
) -> StoryPoolEntry | None:
    arc = getattr(state, "plot_arc", None)
    if arc is None or not getattr(arc, "ready", False):
        return None
    opening_text = str(opening or "").strip()
    if not opening_text:
        opening_text = str(
            (getattr(state, "director_cache", {}) or {}).get("narrative_opening") or ""
        ).strip()
    return StoryPoolEntry(
        entry_id=uuid.uuid4().hex[:10],
        created_at=time.time(),
        full=full,
        plot_arc=dict(arc.snapshot()),
        plot_flow=dict(state.plot_flow.snapshot()),
        presence_card=dict(state.presence_card.snapshot()),
        narrative_card=dict(state.narrative_card.snapshot()),
        opening=opening_text,
        seed_note=seed_note,
        meta={"origin": "prewarm", "full": full},
    )


class StoryPrewarmer:
    """信号触发的后台预热器；对 SpeakService 暴露两个入口：

    - ``prewarm_async``：connect / page_enter 等入场信号时调用（不阻塞）；
    - ``refill_async``：池被消费后补水（同预算护栏）。
    """

    def __init__(
        self,
        *,
        screenwriter: Any,
        pool: StoryMaterialPool,
        pool_depth: int = 3,
        skeleton_count: int = 2,
    ) -> None:
        self._screenwriter = screenwriter
        self._pool = pool
        self._depth = max(1, int(pool_depth))
        self._skeletons = max(0, int(skeleton_count))
        self._inflight: set[str] = set()
        self._lock = threading.Lock()

    # ── 公共入口 ───────────────────────────────────────────────────────────

    def prewarm_async(
        self,
        *,
        pool_key: str,
        user_text: str = "",
        materials: dict[str, Any] | None = None,
    ) -> bool:
        return self._kick(pool_key, user_text=user_text, materials=materials)

    def refill_async(self, *, pool_key: str) -> bool:
        return self._kick(pool_key, user_text="", materials=None)

    # ── 编排 ───────────────────────────────────────────────────────────────

    def _kick(
        self,
        pool_key: str,
        *,
        user_text: str,
        materials: dict[str, Any] | None,
    ) -> bool:
        key = str(pool_key or "").strip()
        if not key:
            return False
        with self._lock:
            if key in self._inflight:
                return False
            self._inflight.add(key)

        def _run() -> None:
            try:
                if self._pool.fresh_count(key) >= self._depth:
                    return
                entries = self._generate(
                    user_text=user_text, materials=materials
                )
                if entries:
                    self._pool.replace_candidates(key, entries)
            except Exception:
                # 预热失败静默：首进回退到正常 ensure_screenwriter_init 路径
                pass
            finally:
                with self._lock:
                    self._inflight.discard(key)

        threading.Thread(
            target=_run,
            daemon=True,
            name=f"story-prewarm-{key[:16]}",
        ).start()
        return True

    def _generate(
        self,
        *,
        user_text: str,
        materials: dict[str, Any] | None,
    ) -> list[StoryPoolEntry]:
        entries: list[StoryPoolEntry] = []

        # 1) 全量候选（编剧 Agent 同步；LLM 不可用时自然回落启发式）
        full_state = SessionSchedulingState(session_id=f"pool-full-{uuid.uuid4().hex[:8]}")
        try:
            self._screenwriter.init_presence(
                full_state,
                session_id=full_state.session_id,
                user_text=user_text,
                materials=materials,
                turn_index=0,
                background_agent=False,
            )
            entry = _entry_from_state(
                full_state, full=True, opening="", seed_note=str(user_text or "")[:120]
            )
            if entry is not None:
                entries.append(entry)
        except Exception:
            pass

        # 2) 骨架候选（纯启发式，无 LLM；upgrade 门控关闭）
        for i in range(max(0, min(self._skeletons, self._depth - len(entries)))):
            skeleton_state = SessionSchedulingState(
                session_id=f"pool-skel-{uuid.uuid4().hex[:8]}"
            )
            try:
                self._screenwriter.init_presence(
                    skeleton_state,
                    session_id=skeleton_state.session_id,
                    user_text=user_text,
                    materials=materials,
                    turn_index=0,
                    background_agent=True,
                    upgrade_agent=False,
                )
                entry = _entry_from_state(
                    skeleton_state,
                    full=False,
                    opening="",
                    seed_note=f"skeleton#{i}",
                )
                if entry is not None:
                    entries.append(entry)
            except Exception:
                continue
        return entries
