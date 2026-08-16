from __future__ import annotations

import json
from typing import Any

from ..manager import ComposeManager
from ..domain.intervention import DirectorMemoryIntervention


class MemoryBufferActionRunner:
    """导演 Agent 工具：对共享记忆 buffer 做离散 unit 级操作。"""

    ACTIONS = frozenset(
        {
            "memory_buffer_list",
            "memory_buffer_get",
            "memory_buffer_search",
            "memory_buffer_inject",
            "memory_buffer_remove",
        }
    )

    def __init__(self, manager: ComposeManager) -> None:
        self._manager = manager
        self._session_id = ""

    def bind_session(self, session_id: str) -> None:
        self._session_id = session_id.strip()

    def run(self, calls: list[dict]) -> list[dict]:
        results: list[dict] = []
        for call in calls:
            action = str(call.get("action") or "").strip()
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            if not isinstance(args, dict):
                args = {}
            results.append(
                {
                    "tool": action,
                    "observation": self._dispatch(action, args),
                }
            )
        return results

    def _dispatch(self, action: str, args: dict[str, Any]) -> str:
        sid = str(args.get("session_id") or self._session_id).strip()
        if not sid:
            return json.dumps({"ok": False, "reason": "missing_session_id"}, ensure_ascii=False)
        if action == "memory_buffer_list":
            units = self._manager.buffer_list_units(sid)
            return json.dumps(
                {
                    "ok": True,
                    "warming": self._manager.buffer_is_warming(sid),
                    "units": [
                        {
                            "unit_id": u.unit_id,
                            "text": u.text[:240],
                            "source": u.source,
                            "has_embedding": bool(u.embedding),
                        }
                        for u in units
                    ],
                },
                ensure_ascii=False,
            )
        if action == "memory_buffer_get":
            unit = self._manager.buffer_get_unit(sid, str(args.get("unit_id") or ""))
            if unit is None:
                return json.dumps({"ok": False, "reason": "not_found"}, ensure_ascii=False)
            return json.dumps(
                {
                    "ok": True,
                    "unit": {
                        "unit_id": unit.unit_id,
                        "text": unit.text,
                        "source": unit.source,
                        "score": unit.score,
                        "has_embedding": bool(unit.embedding),
                    },
                },
                ensure_ascii=False,
            )
        if action == "memory_buffer_search":
            hits = self._manager.buffer_search(
                sid,
                str(args.get("query") or ""),
                top_k=int(args.get("top_k") or 3),
                mode=str(args.get("mode") or "hybrid"),
            )
            return json.dumps(
                {
                    "ok": True,
                    "hits": [
                        {
                            "unit_id": h.unit.unit_id,
                            "text": h.unit.text[:240],
                            "score": h.score,
                            "mode": h.mode,
                        }
                        for h in hits
                    ],
                },
                ensure_ascii=False,
            )
        if action == "memory_buffer_inject":
            result = self._manager.apply_director_memory_intervention(
                sid,
                DirectorMemoryIntervention(
                    action="inject",
                    unit_id=str(args.get("unit_id") or ""),
                    text=str(args.get("text") or ""),
                ),
            )
            return json.dumps(result, ensure_ascii=False)
        if action == "memory_buffer_remove":
            result = self._manager.apply_director_memory_intervention(
                sid,
                DirectorMemoryIntervention(
                    action="remove",
                    unit_id=str(args.get("unit_id") or ""),
                ),
            )
            return json.dumps(result, ensure_ascii=False)
        return json.dumps(
            {
                "ok": False,
                "reason": f"unknown_action:{action}",
                "allowed": sorted(self.ACTIONS),
            },
            ensure_ascii=False,
        )
