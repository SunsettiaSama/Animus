#!/usr/bin/env python3
"""Orchestrator 初始化 smoke：compose cache、记忆预热 buffer、会话同步调度。"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _sep(title: str) -> None:
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}", flush=True)


def _ensure_pkg(name: str, path: Path | None = None) -> None:
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    if path is not None:
        mod.__path__ = [str(path)]
    sys.modules[name] = mod


def _load(relpath: str, fullname: str) -> object:
    path = SRC / relpath
    spec = importlib.util.spec_from_file_location(fullname, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载: {path}")
    mod = importlib.util.module_from_spec(spec)
    parent = fullname.rsplit(".", 1)[0] if "." in fullname else ""
    mod.__package__ = parent
    sys.modules[fullname] = mod
    spec.loader.exec_module(mod)
    return mod


def _stub_pick_weights() -> None:
    pw = types.ModuleType("agent.soul.speak.pipelines.request_driven.orchestrator.blocks.guidance.runtime.memory.pick_weights")
    pw.PICK_WEIGHT_DEFAULT = 1.0
    pw.PICK_PENALTY_FACTOR = 0.38
    pw.PICK_WEIGHT_FLOOR = 0.15
    sys.modules["agent.soul.speak.pipelines.request_driven.orchestrator.blocks.guidance.runtime.memory.pick_weights"] = pw


def _bootstrap() -> object:
    for name, rel in (
        ("agent", SRC / "agent"),
        ("agent.soul", SRC / "agent" / "soul"),
        ("agent.soul.speak", SRC / "agent" / "soul" / "speak"),
        ("agent.soul.speak.session", SRC / "agent" / "soul" / "speak" / "session"),
        ("agent.soul.speak.session.queue", SRC / "agent" / "soul" / "speak" / "session" / "queue"),
        ("agent.soul.speak.pipelines.request_driven.orchestrator", SRC / "agent" / "soul" / "speak" / "pipelines" / "request_driven" / "orchestrator"),
        ("agent.soul.speak.pipelines.request_driven.orchestrator.blocks", SRC / "agent" / "soul" / "speak" / "pipelines" / "request_driven" / "orchestrator" / "blocks"),
        ("agent.soul.speak.pipelines.request_driven.orchestrator.blocks.memory", SRC / "agent" / "soul" / "speak" / "pipelines" / "request_driven" / "orchestrator" / "blocks" / "memory"),
        ("agent.soul.speak.pipelines.request_driven.orchestrator.blocks.guidance", SRC / "agent" / "soul" / "speak" / "pipelines" / "request_driven" / "orchestrator" / "blocks" / "guidance"),
        ("agent.soul.speak.pipelines.request_driven.orchestrator.blocks.guidance.runtime", SRC / "agent" / "soul" / "speak" / "pipelines" / "request_driven" / "orchestrator" / "blocks" / "guidance" / "runtime"),
        ("agent.soul.memory", SRC / "agent" / "soul" / "memory"),
        ("agent.soul.memory.emergence", SRC / "agent" / "soul" / "memory" / "emergence"),
        ("agent.soul.memory.graph", SRC / "agent" / "soul" / "memory" / "graph"),
    ):
        _ensure_pkg(name, rel)

    _load("agent/soul/memory/graph/keywords.py", "agent.soul.memory.graph.keywords")
    _load("agent/soul/memory/emergence/line_dedup.py", "agent.soul.memory.emergence.line_dedup")
    _load("agent/soul/speak/pipelines/request_driven/orchestrator/queue/memory.py", "agent.soul.speak.pipelines.request_driven.orchestrator.queue.memory")
    _load("agent/soul/speak/pipelines/request_driven/orchestrator/blocks/memory/warm_buffer.py", "agent.soul.speak.pipelines.request_driven.orchestrator.blocks.memory.warm_buffer")
    _load("agent/soul/speak/pipelines/request_driven/orchestrator/compose_cache.py", "agent.soul.speak.pipelines.request_driven.orchestrator.compose_cache")
    return _load("agent/soul/speak/pipelines/request_driven/orchestrator/blocks/memory/warm_buffer.py", "agent.soul.speak.pipelines.request_driven.orchestrator.blocks.memory.warm_buffer")


def main() -> int:
    warm_mod = _bootstrap()
    MemoryWarmBuffer = warm_mod.MemoryWarmBuffer
    MemoryBufferItem = sys.modules["agent.soul.speak.pipelines.request_driven.orchestrator.queue.memory"].MemoryBufferItem

    _sep("memory warm buffer")
    buf = MemoryWarmBuffer(max_turn_gap=3)
    sid = "smoke-session"
    buf.set_social_prefetch(
        sid,
        MemoryBufferItem(
            turn_index=0,
            lines=("荧在蒙德城与你重逢", "上次讨论深渊教团"),
            unit_ids=("u_social_1", "u_social_2"),
            source="social_prefetch",
        ),
    )
    buf.enqueue_turn(
        sid,
        MemoryBufferItem(
            turn_index=1,
            lines=("深渊教团在风起地出没",),
            unit_ids=("u_kw_1",),
            source="keyword",
        ),
    )
    pulled = buf.pull_for_compose(
        sid,
        1,
        keyword_wait_ms=0,
        budget=3,
        user_text="深渊教团现在在哪？",
    )
    print("inject:", pulled.inject_lines)
    print("sources:", pulled.sources)
    print("pick_weight u_social_2:", buf.recall_pick_weight(sid, "u_social_2"))
    print("pick_weight u_kw_1:", buf.recall_pick_weight(sid, "u_kw_1"))

    _sep("compose cache")
    cache_mod = sys.modules["agent.soul.speak.pipelines.request_driven.orchestrator.compose_cache"]
    cache = cache_mod.SessionComposeCache(session_id=sid)
    cache.update_from_meta(
        {
            "compose_session_generation": 2,
            "turn_compose_assembly": {
                "session_id": sid,
                "slots": [
                    {"block": "persona", "narrative": "自叙片段", "version": 3},
                    {"block": "guidance", "narrative": "引导片段", "version": 5},
                ],
            },
        }
    )
    print(json.dumps(cache.snapshot(), ensure_ascii=False, indent=2))

    _sep("regex similarity")
    score = warm_mod.regex_similarity_score(
        "深渊教团现在在哪？",
        "上次讨论深渊教团",
    )
    print("social line score:", score)

    _sep("turn inject ledger")
    ledger_mod = _load(
        "agent/soul/speak/pipelines/request_driven/orchestrator/turn_inject_ledger.py",
        "agent.soul.speak.pipelines.request_driven.orchestrator.turn_inject_ledger",
    )
    store = ledger_mod.TurnInjectLedgerStore()
    ledger = store.ledger(sid, 2)
    ledger.emergence_requested = True
    print("ledger snapshot:", ledger.snapshot())

    _sep("director JSON parse")
    director_mod = _load(
        "agent/soul/speak/llm/director_engine.py",
        "agent.soul.speak.llm.director_engine",
    )
    parsed = director_mod.parse_director_json(
        '{"action":"enqueue_brew","lines":["嗯，我在听"],"reason":"smoke"}'
    )
    print("director:", parsed.snapshot())

    _sep("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
