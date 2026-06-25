#!/usr/bin/env python3
"""Run a live smoke test for soul.life.virtual."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


_T0 = time.perf_counter()


def _log(message: str) -> None:
    elapsed = time.perf_counter() - _T0
    print(f"[life-virtual-smoke +{elapsed:7.2f}s] {message}", flush=True)


def _preview(value: object, *, limit: int = 220) -> str:
    text = str(value).replace("\n", " ").strip()
    if len(text) > limit:
        return f"{text[:limit]}..."
    return text


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in path.open("r", encoding="utf-8"))


def _load_llm_config(args: argparse.Namespace):
    from config.llm_core.config import LLMConfig

    _log("resolving LLM config")
    model = args.model or os.environ.get("REACT_TEST_LLM_MODEL", "").strip()
    model = model or os.environ.get("SPEAK_SMOKE_MODEL", "").strip()
    base_url = args.base_url or os.environ.get("REACT_TEST_LLM_BASE_URL", "").strip()
    base_url = base_url or os.environ.get("SPEAK_SMOKE_BASE_URL", "").strip()
    api_key = args.api_key or os.environ.get("REACT_TEST_LLM_API_KEY", "").strip()
    api_key = api_key or os.environ.get("SPEAK_SMOKE_API_KEY", "").strip()
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "").strip()

    cfg_path = Path(args.llm_config)
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path
    _log(f"LLM config candidate: {cfg_path} exists={cfg_path.is_file()}")
    if cfg_path.is_file() and (not model or not base_url or not api_key):
        cfg = LLMConfig.from_yaml(str(cfg_path))
        model = model or cfg.model.strip()
        base_url = base_url or (cfg.base_url or "").strip()
        api_key = api_key or cfg.api_key.strip()

    if not model or not api_key:
        raise RuntimeError(
            "missing LLM config: provide --model/--api-key or config/llm_core/config.yaml"
        )

    _log(
        "LLM config resolved "
        f"model={model} base_url={base_url or '(default)'} api_key_set={bool(api_key)}"
    )
    return LLMConfig(
        backend="openai",
        model=model,
        base_url=base_url or None,
        api_key=api_key,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )


def _output_root(args: argparse.Namespace) -> Path:
    if args.output_root:
        root = Path(args.output_root)
        if not root.is_absolute():
            root = ROOT / root
        root.mkdir(parents=True, exist_ok=True)
        _log(f"using output root: {root}")
        return root

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = ROOT / ".react" / "smoke" / f"life_virtual_{stamp}"
    root.mkdir(parents=True, exist_ok=True)
    _log(f"created output root: {root}")
    return root


def _summary_files(root: Path) -> dict[str, str]:
    life = root / "life"
    return {
        "root": str(root),
        "life_dir": str(life),
        "hot_log": str(life / "experience_hot.jsonl"),
        "virtual_chronicle": str(life / "virtual_chronicle.jsonl"),
        "anchor_chronicle": str(life / "anchor_chronicle.jsonl"),
        "journal": str(life / "journal.json"),
        "soul_db": str(root / "soul_db"),
    }


def _seed_home_scenes(port, world_id: str) -> dict[str, str]:
    home_loc = f"{world_id}-home-loc"
    home_id = port.upsert_scene(
        world_id,
        name="家",
        narrative="你熟悉的小屋，木桌、旧窗与一盏常亮的灯。",
        location_id=home_loc,
        tags=["home"],
        scene_id=f"{world_id}-scene-home",
    )
    desk_id = port.upsert_scene(
        world_id,
        name="窗边书桌",
        narrative="窗边的书桌，纸页与墨痕，风从半开的窗缝进来。",
        location_id=home_loc,
        tags=["desk"],
        scene_id=f"{world_id}-scene-desk",
    )
    door_id = port.upsert_scene(
        world_id,
        name="门口庭院",
        narrative="门口连着一小片庭院，石阶微湿，远处有雨后的凉意。",
        location_id=f"{world_id}-yard-loc",
        tags=["yard"],
        scene_id=f"{world_id}-scene-door",
    )
    port.link_scenes(
        world_id,
        from_scene_id=home_id,
        to_scene_id=desk_id,
        transition_text="你走到窗边的书桌前。",
        weight=20,
    )
    port.link_scenes(
        world_id,
        from_scene_id=home_id,
        to_scene_id=door_id,
        transition_text="你推开门，踏入庭院。",
        weight=15,
    )
    port.apply_scene(world_id, home_id)
    return {"home": home_id, "desk": desk_id, "door": door_id}


def _smoke_gm_answer(question) -> str:
    choices = [str(choice).strip() for choice in getattr(question, "choices", ()) if str(choice).strip()]
    if getattr(question, "is_move", False) and len(choices) > 1:
        return choices[1]
    if choices:
        return choices[0]
    return "我先观察。"


def _seed_due_landmark(life_api, *, intention: str, due_at: str, context: str) -> dict:
    landmark = life_api.journal.add_landmark(intention, due_at, context)
    if landmark is None:
        return {"planned": False, "reason": "journal rejected landmark"}
    life_api.save_journal()
    return {
        "planned": True,
        "landmark_id": landmark.id,
        "intention": landmark.intention,
        "context": landmark.context,
        "scheduled_at": landmark.scheduled_at,
        "seed_only": True,
    }


def _build_virtual_stack(root: Path, llm, world_id: str, *, arc_steps: int = 3):
    from agent.soul.life import LifeManager
    from agent.soul.life.experience import LifeExperienceStack
    from agent.soul.presence import PresenceService
    from storyview.bridge import StoryWorldContextBridge
    from storyview.port import StoryPort
    from storyview.service import StoryService

    life_dir = str(root / "life")
    _log(f"building virtual stack life_dir={life_dir} world_id={world_id}")
    _log("constructing StoryService(json backend)")
    story = StoryService(
        llm=llm,
        storage_backend="json",
        json_root=str(root / "soul_db"),
    )
    _log("starting StoryService worker")
    story.start()
    port = StoryPort(story)
    _log("seeding home scenes")
    scenes = _seed_home_scenes(port, world_id)
    _log(f"seeded scenes={scenes}")

    _log("constructing LifeManager")
    manager = LifeManager(life_dir=life_dir, llm=llm)
    _log("constructing LifeExperienceStack")
    stack = LifeExperienceStack(
        life_dir=life_dir,
        anchor_chronicle=manager.anchor.chronicle,
        virtual_chronicle=manager.virtual.chronicle,
        collapser=manager.narrative,
    )
    _log("constructing PresenceService")
    presence = PresenceService(life_dir=life_dir)
    _log("attaching experience pipeline")
    manager.attach_experience_pipeline(stack.life, dialogue=stack.dialogue)
    _log("binding presence")
    stack.bind_presence(presence)
    _log("wiring story port and world context supplier")
    manager.set_story_port(port)
    manager.set_gm_answerer(_smoke_gm_answer)
    manager.set_story_arc_max_steps(arc_steps)
    manager.set_story_world_context_supplier(
        StoryWorldContextBridge(port, world_id=world_id)
    )
    _log("loading life profile")
    manager.load_profile()
    manager.bind_story_world(world_id)
    _log("virtual stack ready")
    return manager, stack, story, scenes


def _run_virtual_mode(args: argparse.Namespace, root: Path, llm) -> dict:
    manager, stack, story, scenes = _build_virtual_stack(
        root,
        llm,
        args.world_id,
        arc_steps=args.arc_steps,
    )
    scheduled_at = (
        datetime.now(timezone.utc) + timedelta(minutes=args.schedule_minutes)
    ).isoformat()

    if args.action == "plan-fixed":
        _log(
            "action plan-fixed: manager.plan_landmark "
            f"intention={_preview(args.intention)} scheduled_at={scheduled_at}"
        )
        _log("note: plan-fixed only verifies reservation/pre-experience; use fill-fixed for GM Q&A")
        started = time.perf_counter()
        result = manager.plan_landmark(
            intention=args.intention,
            scheduled_at=scheduled_at,
            context=args.context,
        )
        _log(f"action plan-fixed done in {time.perf_counter() - started:.2f}s")
    elif args.action == "compose-and-plan":
        _log("action compose-and-plan: manager.compose_landmark (LLM call expected)")
        started = time.perf_counter()
        draft = manager.compose_landmark()
        _log(
            f"compose_landmark returned in {time.perf_counter() - started:.2f}s "
            f"draft={_preview(draft)}"
        )
        if draft is None:
            result = {"planned": False, "reason": "compose returned None"}
        else:
            _log("planning composed landmark")
            started = time.perf_counter()
            result = manager.plan_landmark(
                intention=draft["intention"],
                scheduled_at=scheduled_at,
                context=draft.get("context", ""),
            )
            _log(f"plan composed landmark done in {time.perf_counter() - started:.2f}s")
    elif args.action == "fill-fixed":
        due_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        _log(
            "action fill-fixed: seeding due landmark without plan beat "
            f"intention={_preview(args.intention)} due_at={due_at}"
        )
        started = time.perf_counter()
        planned = _seed_due_landmark(
            manager,
            intention=args.intention,
            due_at=due_at,
            context=args.context,
        )
        _log(f"due landmark seeded in {time.perf_counter() - started:.2f}s")
        _log("calling manager.fill_due_landmarks (GM Q&A + private dice + Story resolve + subjective fill expected)")
        started = time.perf_counter()
        fills = manager.fill_due_landmarks()
        _log(f"fill_due_landmarks done in {time.perf_counter() - started:.2f}s")
        fill = fills[0] if fills else {}
        if fill:
            for idx, step in enumerate(fill.get("arc_steps", []) or [], start=1):
                _log(f"arc step {idx} GM question: {_preview(step.get('gm_question', ''))}")
                _log(f"arc step {idx} Soul answer: {_preview(step.get('soul_answer', ''))}")
                _log(f"arc step {idx} objective feedback: {_preview(step.get('resolution_text', ''))}")
            _log(f"selected scene_id={fill.get('scene_id')}")
            _log(f"objective arc: {_preview(fill.get('resolution_text', ''))}")
            _log(f"decision importance: {_preview(fill.get('decision_importance', ''))}")
            _log(f"subjective narrative: {_preview(fill.get('narrative', ''))}")
        result = {
            "planned": planned,
            "fills": fills,
            "seed_scenes": scenes,
        }
    elif args.action == "surprise":
        _log(
            "action surprise: manager.run_surprise_tick "
            f"elapsed_sec={args.elapsed_sec}"
        )
        started = time.perf_counter()
        result = manager.run_surprise_tick(args.elapsed_sec)
        _log(f"surprise tick done in {time.perf_counter() - started:.2f}s")
        if result.get("triggered"):
            for idx, step in enumerate(result.get("arc_steps", []) or [], start=1):
                _log(f"arc step {idx} GM question: {_preview(step.get('gm_question', ''))}")
                _log(f"arc step {idx} Soul answer: {_preview(step.get('soul_answer', ''))}")
                _log(f"arc step {idx} objective feedback: {_preview(step.get('resolution_text', ''))}")
            _log(f"objective arc: {_preview(result.get('resolution_text', ''))}")
            _log(f"decision importance: {_preview(result.get('decision_importance', ''))}")
            _log(f"subjective narrative: {_preview(result.get('narrative', ''))}")
        result = {**result, "seed_scenes": scenes}
    else:
        raise ValueError(f"unknown action: {args.action!r}")

    _log("collecting hot experiences")
    hot = manager.hot_experiences(hours=None)
    _log(f"hot experiences collected count={len(hot)}")
    _log("collecting recent chronicle")
    chronicle = manager.recent_chronicle(days=1, tail=20)
    _log(f"chronicle collected count={len(chronicle)}")
    _log("syncing presence from life hot log")
    presence_sync = stack.sync_presence("tao")
    _log(f"presence sync result={_preview(presence_sync)}")

    summary = {
        "mode": "virtual",
        "action": args.action,
        "result": result,
        "hot": hot,
        "chronicle": chronicle,
        "journal": manager.journal.to_dict(),
        "presence_sync": presence_sync,
        "life_status": manager.service_status(),
    }
    _log("stopping StoryService and LifeManager")
    story.stop()
    manager.stop()
    _log("virtual mode finished")
    return summary


def _run_soul_mode(args: argparse.Namespace, root: Path, llm) -> dict:
    from agent.soul.service import SoulService
    from config.agent.persona_config import PersonaConfig
    from config.soul.config import SoulConfig
    from config.soul.memory.infra_config import SoulMemoryInfraConfig
    from infra.memory import MemoryInfraService

    _log("building SoulService config")
    soul_cfg = SoulConfig()
    soul_cfg.landmark_write_max_per_window = 10
    persona_cfg = PersonaConfig(
        enabled=True,
        persona_dir=str(root / "persona"),
        evolution_enabled=False,
    )
    memory_infra = MemoryInfraService(
        cfg=SoulMemoryInfraConfig(enabled=False),
        embedding=None,
        vectors=None,
    )
    service = SoulService(
        life_dir=str(root / "life"),
        persona_cfg=persona_cfg,
        primary_llm=llm,
        cfg=soul_cfg,
        memory_infra=memory_infra,
        storage_backend="json",
        json_root=str(root / "soul_db"),
    )
    _log("starting SoulService (full worker wiring)")
    started = time.perf_counter()
    service.start()
    service.life.api.set_story_arc_max_steps(args.arc_steps)
    _log(f"SoulService started in {time.perf_counter() - started:.2f}s")
    if args.action == "fill-fixed":
        _log("soul fill-fixed: seeding due landmark through life.api journal")
        planned = _seed_due_landmark(
            service.life.api,
            intention=args.intention,
            due_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            context=args.context,
        )
        _log(f"soul fill-fixed: seeded due landmark={planned}")
        _log("soul fill-fixed: calling run_trigger_landmarks")
        started = time.perf_counter()
        fills = service.run_trigger_landmarks()
        _log(f"run_trigger_landmarks done in {time.perf_counter() - started:.2f}s")
        result = {
            "planned": planned,
            "fills": fills,
        }
    elif args.action == "surprise":
        _log(f"soul surprise: calling run_surprise_tick elapsed_sec={args.elapsed_sec}")
        started = time.perf_counter()
        result = service.run_surprise_tick(args.elapsed_sec)
        _log(f"run_surprise_tick done in {time.perf_counter() - started:.2f}s")
    else:
        _log("soul plan: calling execute_plan_landmark")
        started = time.perf_counter()
        result = service.execute_plan_landmark()
        _log(f"execute_plan_landmark done in {time.perf_counter() - started:.2f}s")

    _log("soul mode: collecting hot/chronicle/status")
    hot = service.query_life_hot(hours=None)
    chronicle = service.query_life_chronicle(days=1, tail=20)
    summary = {
        "mode": "soul",
        "action": args.action,
        "result": result,
        "hot": hot,
        "chronicle": chronicle,
        "journal": service.life.api.journal.to_dict(),
        "life_status": service.life.api.service_status(),
    }
    _log(f"soul mode collected hot={len(hot)} chronicle={len(chronicle)}")
    _log("stopping SoulService")
    service.stop()
    _log("soul mode finished")
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke test soul.life.virtual with a real LLM API")
    parser.add_argument("--mode", choices=("virtual", "soul"), default="virtual")
    parser.add_argument(
        "--action",
        choices=("plan-fixed", "compose-and-plan", "fill-fixed", "surprise"),
        default="fill-fixed",
    )
    parser.add_argument("--llm-config", default="config/llm_core/config.yaml")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--output-root", default="")
    parser.add_argument("--world-id", default="smoke-life-virtual")
    parser.add_argument("--intention", default="在雨后的庭院里观察一盏将熄未熄的灯")
    parser.add_argument("--context", default="雨后空气很凉，你想确认那盏灯是否还能撑过这一阵风。")
    parser.add_argument("--schedule-minutes", type=float, default=5.0)
    parser.add_argument("--elapsed-sec", type=float, default=3600.0)
    parser.add_argument("--arc-steps", type=int, default=3)
    return parser


def main() -> None:
    _log("script entry")
    args = _build_parser().parse_args()
    _log(
        f"parsed args mode={args.mode} action={args.action} "
        f"world_id={args.world_id} max_tokens={args.max_tokens}"
    )
    root = _output_root(args)
    cfg = _load_llm_config(args)

    from infra.llm import LLM

    _log("constructing LLM facade")
    llm = LLM(cfg)
    _log(f"LLM facade ready model={cfg.model} root={root}")
    if args.base_url or cfg.base_url:
        _log(f"base_url={cfg.base_url}")
    files = _summary_files(root)
    _log("artifact paths:")
    for name, path in files.items():
        _log(f"  {name}: {path}")

    if args.mode == "virtual":
        summary = _run_virtual_mode(args, root, llm)
    else:
        summary = _run_soul_mode(args, root, llm)

    summary["files"] = files
    life_dir = Path(files["life_dir"])
    _log(
        "artifact counts "
        f"hot_lines={_count_lines(life_dir / 'experience_hot.jsonl')} "
        f"virtual_chronicle_lines={_count_lines(life_dir / 'virtual_chronicle.jsonl')} "
        f"anchor_chronicle_lines={_count_lines(life_dir / 'anchor_chronicle.jsonl')}"
    )
    _log("final summary json follows")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
