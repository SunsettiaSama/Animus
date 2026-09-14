"""status — 聚合快照：``GET /api/launch/status`` 与 ``run.py --check`` 的共同正本。

snapshot(state) 纯读不写、永不抛错（探测异常在 probes 内消化）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import guide, phases, probes


def _phase(pid: str, state: str, detail: str = "") -> dict[str, Any]:
    return {"id": pid, "label": dict(phases.PHASES)[pid],
            "state": state, "detail": detail}


def snapshot(state: Any) -> dict[str, Any]:
    env = probes.python_env()
    config = probes.config_health()
    llm = probes.llm_probe(state)
    storage = probes.storage_probe()
    embedding = probes.embedding_probe(state)
    persona = probes.persona_probe(state)
    soul = probes.soul_probe(state)

    # ── 阶段灯 ────────────────────────────────────────────────────────────
    phase_list = [
        _phase(phases.ENV, phases.OK,
               f"Python {env['version']} · {env['platform']}"),
        _phase(phases.CONFIG,
               phases.OK if config["ok"] else phases.FAIL,
               config["detail"] or "run.yaml · llm_core"),
    ]

    if not llm["handle_ready"]:
        infra_state = phases.FAIL
    elif llm.get("degraded_reason"):
        infra_state = phases.WARN
    else:
        infra_state = phases.OK
    infra_detail = f"LLM {llm['backend'] or '—'} · {llm['model'] or '—'} · 存储 {storage['backend'] or '—'}"
    phase_list.append(_phase(phases.INFRA, infra_state, infra_detail))

    if soul["running"] and soul["speak_initialized"]:
        soul_state = phases.OK
    elif soul["running"]:
        soul_state = phases.WARN
    elif soul["init_error"]:
        soul_state = phases.FAIL
    else:
        soul_state = phases.PENDING
    # 阶段卡只放短句；完整 init_error 经 payload 的 soul.init_error 供悬停提示
    if soul["init_error"]:
        soul_detail = "启动失败 · 见下方指引"
    elif soul["running"]:
        soul_detail = "soul=running"
    else:
        soul_detail = f"soul={soul['state'] or '未启动'}"
    phase_list.append(_phase(phases.SOUL, soul_state, soul_detail))

    # serve：本快照能被请求到即说明宿主在役
    phase_list.append(_phase(phases.SERVE, phases.OK, "WebUI 在役"))

    # ── 未就绪检查项（附人话指引） ────────────────────────────────────────
    raw_checks: list[tuple[str, bool]] = [
        ("llm", llm["handle_ready"]),
        ("config", config["ok"]),
        ("storage", storage["ok"]),
        ("persona_enabled", persona["enabled"]),
        ("profile", persona["files"]["profile_exists"]),
        ("soul", soul["running"]),
        ("speak", soul["speak_initialized"]),
    ]
    checks = []
    for check_id, ok in raw_checks:
        if ok:
            continue
        label, hint_text = guide.hint(check_id)
        checks.append({"id": check_id, "label": label, "hint": hint_text})
    if llm.get("degraded_reason"):
        label, hint_text = guide.hint("llm_degraded")
        checks.append({"id": "llm_degraded", "label": label, "hint": hint_text})
    if not embedding["ready"]:
        label, hint_text = guide.hint("embedding_warm")
        checks.append({"id": "embedding_warm", "label": label, "hint": hint_text})

    return {
        "form": "local",  # 产品形态 A · 本地部署
        "phases": phase_list,
        "checks": checks,
        "llm": llm,
        "storage": storage,
        "embedding": embedding,
        "persona": persona,
        "soul": {
            "running": soul["running"],
            "state": soul["state"],
            "speak_initialized": soul["speak_initialized"],
            "init_error": soul["init_error"],
        },
        "soul_ready": soul["running"] and soul["speak_initialized"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
