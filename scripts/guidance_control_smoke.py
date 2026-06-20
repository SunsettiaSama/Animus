#!/usr/bin/env python3
"""Guidance 对话控制弧 smoke：fallback / 真实 LLM API，打印 planner 与出站 prompt。"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

_LLM_CANDIDATES = [
    ROOT / "config" / "llm_core" / "config.yaml",
    ROOT / "config" / "llm.yaml",
]


def _sep(title: str) -> None:
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}", flush=True)


def _ensure_pkg(name: str, path: Path | None = None) -> None:
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    if path is not None:
        mod.__path__ = [str(path)]
    sys.modules[name] = mod


def _load_module(relpath: str, fullname: str) -> object:
    path = SRC / relpath
    spec = importlib.util.spec_from_file_location(fullname, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = fullname.rsplit(".", 1)[0] if "." in fullname else ""
    sys.modules[fullname] = mod
    spec.loader.exec_module(mod)
    return mod


def _bootstrap_guidance_modules():
    _ensure_pkg("agent", SRC / "agent")
    _ensure_pkg("agent.soul", SRC / "agent" / "soul")
    _ensure_pkg("agent.soul.speak", SRC / "agent" / "soul" / "speak")
    _ensure_pkg("agent.soul.speak.orchestrator", SRC / "agent" / "soul" / "speak" / "orchestrator")
    _ensure_pkg(
        "agent.soul.speak.orchestrator.blocks",
        SRC / "agent" / "soul" / "speak" / "orchestrator" / "blocks",
    )
    _ensure_pkg(
        "agent.soul.speak.orchestrator.blocks.guidance",
        SRC / "agent" / "soul" / "speak" / "orchestrator" / "blocks" / "guidance",
    )
    _ensure_pkg(
        "agent.soul.speak.orchestrator.blocks.guidance.runtime",
        SRC / "agent" / "soul" / "speak" / "orchestrator" / "blocks" / "guidance" / "runtime",
    )
    _ensure_pkg(
        "agent.soul.speak.orchestrator.blocks.guidance.runtime.control",
        SRC / "agent" / "soul" / "speak" / "orchestrator" / "blocks" / "guidance" / "runtime" / "control",
    )
    _ensure_pkg("agent.soul.speak.orchestrator.io", SRC / "agent" / "soul" / "speak" / "orchestrator" / "io")
    _ensure_pkg(
        "agent.soul.speak.orchestrator.io.inbound",
        SRC / "agent" / "soul" / "speak" / "orchestrator" / "io" / "inbound",
    )
    _ensure_pkg(
        "agent.soul.speak.orchestrator.io.inbound.guidance",
        SRC / "agent" / "soul" / "speak" / "orchestrator" / "io" / "inbound" / "guidance",
    )
    _ensure_pkg(
        "agent.soul.speak.orchestrator.io.outbound",
        SRC / "agent" / "soul" / "speak" / "orchestrator" / "io" / "outbound",
    )
    _ensure_pkg(
        "agent.soul.speak.orchestrator.io.outbound.guidance",
        SRC / "agent" / "soul" / "speak" / "orchestrator" / "io" / "outbound" / "guidance",
    )

    base = "agent.soul.speak.orchestrator.blocks.guidance.runtime.control"
    state = _load_module(
        "agent/soul/speak/orchestrator/blocks/guidance/runtime/control/state.py",
        f"{base}.state",
    )
    _load_module(
        "agent/soul/speak/orchestrator/blocks/guidance/runtime/control/store.py",
        f"{base}.store",
    )
    render = _load_module(
        "agent/soul/speak/orchestrator/blocks/guidance/runtime/control/render.py",
        f"{base}.render",
    )
    planner = _load_module(
        "agent/soul/speak/orchestrator/blocks/guidance/runtime/control/planner.py",
        f"{base}.planner",
    )
    service = _load_module(
        "agent/soul/speak/orchestrator/blocks/guidance/runtime/control/service.py",
        f"{base}.service",
    )
    control_pkg = sys.modules[base]
    control_pkg.GuidanceControlService = service.GuidanceControlService
    control_pkg.GuidanceControlState = state.GuidanceControlState
    control_pkg.GuidanceTrigger = state.GuidanceTrigger
    control_pkg.GuidancePlanInput = planner.GuidancePlanInput
    guidance_pkg = sys.modules["agent.soul.speak.orchestrator.blocks.guidance"]
    guidance_pkg.GuidanceControlService = service.GuidanceControlService
    guidance_pkg.GuidanceControlState = state.GuidanceControlState
    guidance_pkg.GuidanceTrigger = state.GuidanceTrigger
    guidance_pkg.GuidancePlanInput = planner.GuidancePlanInput
    guidance_pkg.render_control_arc = render.render_control_arc
    _load_module(
        "agent/soul/speak/orchestrator/io/inbound/guidance/request.py",
        "agent.soul.speak.orchestrator.io.inbound.guidance.request",
    )
    inbound = _load_module(
        "agent/soul/speak/orchestrator/io/inbound/guidance/gateway.py",
        "agent.soul.speak.orchestrator.io.inbound.guidance.gateway",
    )
    outbound = _load_module(
        "agent/soul/speak/orchestrator/io/outbound/guidance/gateway.py",
        "agent.soul.speak.orchestrator.io.outbound.guidance.gateway",
    )
    return state, render, planner, service, inbound, outbound


def _load_llm_config():
    from config.llm_core.config import LLMConfig

    api_key = os.environ.get("REACT_TEST_LLM_API_KEY", "").strip()
    model = os.environ.get("REACT_TEST_LLM_MODEL", "").strip()
    base_url = os.environ.get("REACT_TEST_LLM_BASE_URL", "").strip() or None
    if api_key and model:
        return LLMConfig(
            backend="openai",
            api_key=api_key,
            model=model,
            base_url=base_url,
            max_tokens=int(os.environ.get("REACT_TEST_LLM_MAX_TOKENS", "512")),
            temperature=float(os.environ.get("REACT_TEST_LLM_TEMPERATURE", "0.3")),
        )
    for path in _LLM_CANDIDATES:
        if path.is_file():
            cfg = LLMConfig.from_yaml(str(path))
            if cfg.api_key.strip() and cfg.model.strip():
                if cfg.backend not in ("openai", "vllm", "vllm-clone"):
                    cfg.backend = "openai"
                return cfg
    return None


def _lynaya_context() -> dict[str, str]:
    return {
        "distilled_context": (
            "你与荧在前往冒险家协会的路上偶遇；你刚在纳塔地底见过背上有发光宝石的群居蜥蜴，"
            "很兴奋但还没告诉对方细节。"
        ),
        "persona_portrait": "你是博物学家莉奈亚，平时开朗乐观，说话自然。",
        "interactor_portrait": "荧，提瓦特旅行者，你的好朋友。",
    }


def _print_state(label: str, state) -> None:
    print(f"\n--- {label} ---", flush=True)
    print(json.dumps(state.snapshot(), ensure_ascii=False, indent=2), flush=True)


def _print_render(render_mod, state) -> None:
    block = render_mod.render_control_arc(state)
    _sep("出站 prompt · guidance.control_arc")
    print(block, flush=True)


def main() -> None:
    state_mod, render_mod, planner_mod, service_mod, inbound_mod, outbound_mod = (
        _bootstrap_guidance_modules()
    )
    GuidanceControlService = service_mod.GuidanceControlService
    GuidancePlanInput = planner_mod.GuidancePlanInput
    InboundGuidanceGateway = inbound_mod.InboundGuidanceGateway
    OutboundGuidanceGateway = outbound_mod.OutboundGuidanceGateway
    GuidancePlanRequest = sys.modules[
        "agent.soul.speak.orchestrator.io.inbound.guidance.request"
    ].GuidancePlanRequest

    from config.soul.presence.config import SHARE_INTENT_QUEUE_MAX_ITEMS

    ctx = _lynaya_context()
    session_id = "smoke-guidance"

    _sep("1) Fallback planner（无 LLM）")
    control = GuidanceControlService(llm=None)
    inbound = InboundGuidanceGateway(control)
    outbound = OutboundGuidanceGateway(control)

    init_req = GuidancePlanRequest(
        session_id=session_id,
        turn_index=1,
        distilled_context=ctx["distilled_context"],
        persona_portrait=ctx["persona_portrait"],
        interactor_portrait=ctx["interactor_portrait"],
        share_queue_count=0,
        share_queue_full=False,
        trigger="init",
    )
    inbound.sync_for_compose(init_req, force=True)
    snap = outbound.snapshot(session_id)
    _print_state("API · get_guidance_control / snapshot", control.active(session_id))
    print(f"version={outbound.version(session_id)}", flush=True)
    _print_render(render_mod, control.active(session_id))

    _sep("2) Share 队列已满 · 联动刷新")
    share_req = GuidancePlanRequest(
        session_id=session_id,
        turn_index=2,
        distilled_context=ctx["distilled_context"],
        persona_portrait=ctx["persona_portrait"],
        interactor_portrait=ctx["interactor_portrait"],
        share_queue_count=SHARE_INTENT_QUEUE_MAX_ITEMS,
        share_queue_full=True,
    )
    refreshed = inbound.sync_for_compose(share_req, force=True)
    print(f"sync_for_compose refreshed={refreshed}", flush=True)
    _print_state("联动后 snapshot", control.active(session_id))
    print(
        f"version_changed(since 1)={outbound.version_changed(session_id, since_version=1)}",
        flush=True,
    )
    _print_render(render_mod, control.active(session_id))

    llm_cfg = _load_llm_config()
    if llm_cfg is None:
        _sep("3) 真实 LLM API · 跳过")
        print("未找到 config/llm_core/config.yaml 或 REACT_TEST_LLM_* 环境变量。", flush=True)
        return

    _sep("3) 真实 LLM API · plan_control_arc")
    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from infra.llm import LLM

    engine = SpeakLLMEngine(LLM(llm_cfg))
    llm_control = GuidanceControlService(llm=engine)
    cand_types = _load_module(
        "agent/soul/speak/orchestrator/blocks/guidance/runtime/control/candidate_types.py",
        "agent.soul.speak.orchestrator.blocks.guidance.runtime.control.candidate_types",
    )
    SharePlannerCandidate = cand_types.SharePlannerCandidate
    RecallPlannerCandidate = cand_types.RecallPlannerCandidate

    share_candidates = (
        SharePlannerCandidate(
            planner_index=0,
            queue_index=0,
            brief="纳塔地底群居蜥蜴，背上有发光宝石",
            share_desire="eager",
            salience=0.92,
        ),
    )
    recall_candidates = (
        RecallPlannerCandidate(
            planner_index=0,
            unit_id="mem-rain",
            line="曾在雨夜与同伴失散，想起来仍心口发紧",
        ),
    )
    share_preview = (
        "摘要：纳塔地底见闻\n"
        "分享候选（按情绪强度优先列出，仅下列下标可 emit_share_index）：\n"
        "- [0] queue=0 纳塔地底群居蜥蜴，背上有发光宝石（意愿：eager，显著性=0.92）"
    )
    recall_preview = (
        "回忆候选（social 固定取最新检索 1 条；event 为漫游/涌现池抽样 1 条；"
        "有候选≠必须叙述，仅下列下标可 emit_recall_index）：\n"
        "- [0] （social·最新）曾在雨夜与同伴失散，想起来仍心口发紧"
    )
    plan_input = GuidancePlanInput(
        session_id=f"{session_id}-llm",
        turn_index=3,
        distilled_context=ctx["distilled_context"],
        persona_portrait=ctx["persona_portrait"],
        interactor_portrait=ctx["interactor_portrait"],
        share_preview=share_preview,
        recall_preview=recall_preview,
        share_candidates=share_candidates,
        recall_candidates=recall_candidates,
        last_rhythm_brief="你先用短句接话，等对方问起再展开。",
        share_queue_count=SHARE_INTENT_QUEUE_MAX_ITEMS,
        share_queue_full=True,
        trigger="share_queue_full",
    )
    llm_state = llm_control.plan_and_set(plan_input)
    _print_state("LLM planner 输出 state", llm_state)
    nar = llm_state.narrative
    print(
        f"narrative_chars={len(nar)} "
        f"in_range[100-280]={100 <= len(nar) <= 280} "
        f"share_linked={llm_state.share_linked} "
        f"has_share_tag={'（分享：' in nar} "
        f"has_recall_tag={'（回忆：' in nar} "
        f"emit_share_queue_index={llm_state.emit_share_queue_index} "
        f"emit_recall_unit_id={llm_state.emit_recall_unit_id}",
        flush=True,
    )
    _print_render(render_mod, llm_state)

    _sep("完成")


if __name__ == "__main__":
    main()
