#!/usr/bin/env python3
"""Smoke test LandmarkAgenda drafting trace and optional storyview preview."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_T0 = time.perf_counter()

_DEFAULT_PERSONA_NARRATIVE = (
    "你是莉奈娅，边境探险队的博物学家与记录者。"
    "你说话不急，习惯先听清环境与风声再开口；"
    "出野外前会核对标本册、放大镜与记录本，"
    "观察时有耐心，记录克制，不轻易下结论，也不热衷追逐惊奇的旁支线索。"
)


def _log(message: str) -> None:
    elapsed = time.perf_counter() - _T0
    print(f"[life-landmark-agenda-smoke +{elapsed:7.2f}s] {message}", flush=True)


def _preview(value: object, *, limit: int = 220) -> str:
    text = str(value).replace("\n", " ").strip()
    if len(text) > limit:
        return f"{text[:limit]}..."
    return text


def _load_llm_config(args: argparse.Namespace):
    from config.llm_core.config import LLMConfig

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
    if cfg_path.is_file() and (not model or not base_url or not api_key):
        cfg = LLMConfig.from_yaml(str(cfg_path))
        model = model or cfg.model.strip()
        base_url = base_url or (cfg.base_url or "").strip()
        api_key = api_key or cfg.api_key.strip()

    if not model or not api_key:
        raise RuntimeError(
            "missing LLM config: provide --model/--api-key or config/llm_core/config.yaml"
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
        return root

    stamp = time.strftime("%Y%m%d_%H%M%S")
    root = ROOT / ".react" / "smoke" / f"life_landmark_agenda_{stamp}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _life_dir(args: argparse.Namespace, root: Path) -> Path:
    if args.life_dir:
        life = Path(args.life_dir)
        if not life.is_absolute():
            life = ROOT / life
        life.mkdir(parents=True, exist_ok=True)
        return life
    life = root / "life"
    life.mkdir(parents=True, exist_ok=True)
    return life


def _json_root(args: argparse.Namespace, root: Path) -> Path:
    if args.story_json_root:
        json_root = Path(args.story_json_root)
        if not json_root.is_absolute():
            json_root = ROOT / json_root
        json_root.mkdir(parents=True, exist_ok=True)
        return json_root
    json_root = root / "soul_db"
    json_root.mkdir(parents=True, exist_ok=True)
    return json_root


def _build_stack(args: argparse.Namespace, root: Path, llm):
    from agent.soul.life import LifeManager
    from agent.soul.life.experience import LifeExperienceStack
    from agent.soul.life.virtual.journal.contracts import LandmarkPlanningStrategy
    from agent.soul.presence import PresenceService
    from storyview.bootstrap import ensure_default_world_scenes
    from storyview.bridge import StoryWorldContextBridge
    from storyview.port import StoryPort
    from storyview.service import StoryService
    from storyview.types import SceneGroundingPolicy

    life_dir = _life_dir(args, root)
    manager = LifeManager(life_dir=str(life_dir), llm=llm)
    profile = manager.load_profile()
    world_id = args.world_id.strip() or profile.resolved_world_id("smoke-life-landmark-agenda")
    manager.bind_story_world(world_id)

    story_json_root = _json_root(args, root)
    story = StoryService(
        llm=llm,
        storage_backend="json",
        json_root=str(story_json_root),
    )
    story.start()
    port = StoryPort(story)
    scenes = ensure_default_world_scenes(port, world_id)

    stack = LifeExperienceStack(
        life_dir=str(life_dir),
        anchor_chronicle=manager.anchor.chronicle,
        virtual_chronicle=manager.virtual.chronicle,
        collapser=manager.narrative,
    )
    presence = PresenceService(life_dir=str(life_dir))
    manager.attach_experience_pipeline(stack.life, dialogue=stack.dialogue)
    stack.bind_presence(presence)
    manager.set_story_port(port)
    manager.set_story_arc_max_steps(args.story_arc_max_steps)
    manager.set_scene_grounding_policy(
        SceneGroundingPolicy(
            allow_create=not args.grounding_no_create,
            match_threshold=max(0, args.grounding_match_threshold),
            max_review_rounds=max(1, args.grounding_max_review_rounds),
            attach_to_current=not args.grounding_no_attach_to_current,
            allow_node_mutation=args.allow_node_mutation,
        )
    )
    manager.set_story_world_context_supplier(
        StoryWorldContextBridge(port, world_id=world_id)
    )

    persona_narrative = (
        args.persona_narrative.strip()
        or profile.narrative.strip()
        or _DEFAULT_PERSONA_NARRATIVE
    )
    manager.sync_agent_persona_narrative(persona_narrative)

    return (
        manager,
        stack,
        story,
        port,
        scenes,
        life_dir,
        story_json_root,
        world_id,
        profile,
        LandmarkPlanningStrategy,
    )


def _recent_landmark_dicts(manager, *, limit: int = 5) -> list[dict]:
    items = manager.journal.all_landmarks()
    items.sort(key=lambda item: item.created_at, reverse=True)
    return [item.to_dict() for item in items[:limit]]


def _print_trace(result) -> None:
    for item in result.revision_trace:
        _log(
            f"round={item.round} action={item.action} "
            f"thought={_preview(item.thought, limit=120)} "
            f"patch={_preview(item.patch_summary, limit=120)}"
        )
        if item.observation.strip():
            _log(f"  observation={_preview(item.observation, limit=180)}")


def _log_agenda_scene_details(agenda) -> None:
    scene_id = getattr(agenda, "scene_id", "")
    scene_name = getattr(agenda, "scene_name", "")
    _log(f"agenda scene_id={scene_id}")
    _log(f"agenda scene_name={scene_name}")
    narrative = getattr(agenda, "scene_narrative", "")
    if narrative:
        _log(f"agenda scene_narrative={_preview(narrative, limit=320)}")
    for idx, card in enumerate(getattr(agenda, "scene_cards", ()) or (), start=1):
        affordances = ", ".join(getattr(card, "affordances", ()) or ())
        conditions = ", ".join(getattr(card, "conditions", ()) or ())
        _log(
            f"agenda scene_card[{idx}] id={card.id} title={card.title} "
            f"description={_preview(card.description, limit=220)}"
        )
        if affordances:
            _log(f"  affordances={_preview(affordances, limit=220)}")
        if conditions:
            _log(f"  conditions={_preview(conditions, limit=220)}")


def _run(args: argparse.Namespace, root: Path, llm) -> dict:
    (
        manager,
        stack,
        story,
        _port,
        scenes,
        life_dir,
        story_json_root,
        world_id,
        profile,
        strategy_enum,
    ) = _build_stack(args, root, llm)

    target_date = args.target_date.strip() or (date.today() + timedelta(days=1)).isoformat()
    strategy_name = args.strategy

    _log(f"strategy={strategy_name} target_date={target_date}")
    _log(
        "grounding policy="
        f"allow_create={not args.grounding_no_create} "
        f"match_threshold={max(0, args.grounding_match_threshold)} "
        f"max_review_rounds={max(1, args.grounding_max_review_rounds)} "
        f"attach_to_current={not args.grounding_no_attach_to_current} "
        f"allow_node_mutation={args.allow_node_mutation}"
    )
    started = time.perf_counter()

    if strategy_name == "legacy_write":
        scheduled_at = (
            datetime.now(timezone.utc) + timedelta(minutes=args.schedule_minutes)
        ).isoformat()
        before_recent = _recent_landmark_dicts(manager)
        _log(f"legacy journal before count={len(manager.journal.all_landmarks())}")
        draft = manager.compose_landmark()
        if draft is None:
            raise RuntimeError("compose_landmark returned None")
        _log(f"legacy compose draft={_preview(draft)}")
        planned = manager.plan_landmark(
            intention=draft["intention"],
            scheduled_at=scheduled_at,
            context=draft.get("context", ""),
        )
        if planned is None:
            raise RuntimeError("plan_landmark returned None")
        _log(f"legacy plan_landmark experience_id={planned.get('experience_id', '')}")
        after_recent = _recent_landmark_dicts(manager)
        hot = manager.hot_experiences(hours=None)
        chronicle = manager.recent_chronicle(days=1, tail=20)
        presence_sync = (
            {} if args.skip_presence_sync else stack.sync_presence("tao")
        )
        story.stop()
        manager.stop()
        return {
            "strategy": strategy_name,
            "target_date": target_date,
            "generated_landmark": draft,
            "scheduled_at": scheduled_at,
            "planned_event": planned,
            "journal_before_recent": before_recent,
            "journal_after_recent": after_recent,
            "hot": hot,
            "chronicle": chronicle,
            "presence_sync": presence_sync,
            "world_id": world_id,
            "profile": profile.to_dict(),
            "seed_scenes": scenes,
            "files": {
                "root": str(root),
                "life_dir": str(life_dir),
                "story_json_root": str(story_json_root),
                "journal": str(life_dir / "journal.json"),
                "landmark_agendas": str(life_dir / "landmark_agendas.json"),
                "hot_log": str(life_dir / "experience_hot.jsonl"),
                "virtual_chronicle": str(life_dir / "virtual_chronicle.jsonl"),
            },
        }

    if strategy_name == "agenda_full":
        result = manager.compose_landmark_agenda_for_tomorrow(
            target_date=target_date,
            save=not args.no_save,
        )
    else:
        strategy = strategy_enum(strategy_name)
        result = manager.compose_landmark_with_strategy(
            strategy,
            target_date=target_date,
            save=not args.no_save,
        )
    _log(f"compose finished in {time.perf_counter() - started:.2f}s")

    preview = None
    agenda_dict = None
    completed_event = None
    hot = []
    chronicle = []
    presence_sync = {}
    trace = []

    if hasattr(result, "revision_trace"):
        trace = [item.to_dict() for item in result.revision_trace]
        agenda_dict = result.agenda.to_dict()
        _log(f"agenda title={result.agenda.title}")
        _log(f"agenda summary={_preview(result.agenda.summary)}")
        _log_agenda_scene_details(result.agenda)
        if getattr(result.agenda, "grounding_trace", None):
            for entry in result.agenda.grounding_trace:
                _log(
                    f"grounding R{entry.round} {entry.action}: "
                    f"{_preview(entry.observation, limit=160)}"
                )
        _log(f"agenda full_context={_preview(result.agenda.full_context, limit=320)}")
        _print_trace(result)
        if getattr(result, "question", "").strip():
            preview = {
                "question": result.question,
                "answer": result.answer,
                "public_cue_preview": _preview(result.public_cue, limit=320),
            }
            _log(f"story preview question={_preview(result.question)}")
            _log(f"story preview answer={_preview(result.answer)}")

    if strategy_name == "agenda_full":
        _log("running full landmark agenda GM arc")
        started = time.perf_counter()
        completed_event = manager.fill_landmark_agenda(result.agenda)
        _log(
            "fill_landmark_agenda returned "
            f"in {time.perf_counter() - started:.2f}s "
            f"experience_id={completed_event.get('experience_id', '')}"
        )
        _log(f"gm scene_text={_preview(completed_event.get('scene_text', ''), limit=420)}")
        _log(f"gm question={_preview(completed_event.get('gm_question', ''), limit=420)}")
        _log(f"gm answer={_preview(completed_event.get('soul_answer', ''), limit=240)}")
        _log(f"gm resolution={_preview(completed_event.get('resolution_text', ''), limit=420)}")
        agenda_dict = completed_event["agenda"]
        hot = manager.hot_experiences(hours=None)
        chronicle = manager.recent_chronicle(days=1, tail=20)
        presence_sync = (
            {} if args.skip_presence_sync else stack.sync_presence("tao")
        )

    latest = [item.to_dict() for item in manager.latest_landmark_agendas(limit=5)]

    story.stop()
    manager.stop()

    return {
        "strategy": strategy_name,
        "target_date": target_date,
        "agenda": agenda_dict,
        "revision_trace": trace,
        "grounding_trace": (
            [item.to_dict() for item in result.agenda.grounding_trace]
            if hasattr(result, "agenda") and getattr(result.agenda, "grounding_trace", None)
            else []
        ),
        "scene_cards": (
            [card.to_dict() for card in result.agenda.scene_cards]
            if hasattr(result, "agenda") and getattr(result.agenda, "scene_cards", None)
            else []
        ),
        "story_preview": preview,
        "completed_event": completed_event,
        "latest_agendas": latest,
        "hot": hot,
        "chronicle": chronicle,
        "presence_sync": presence_sync,
        "world_id": world_id,
        "grounding_policy": {
            "allow_create": not args.grounding_no_create,
            "match_threshold": max(0, args.grounding_match_threshold),
            "max_review_rounds": max(1, args.grounding_max_review_rounds),
            "attach_to_current": not args.grounding_no_attach_to_current,
            "allow_node_mutation": args.allow_node_mutation,
        },
        "profile": profile.to_dict(),
        "seed_scenes": scenes,
        "files": {
            "root": str(root),
            "life_dir": str(life_dir),
            "story_json_root": str(story_json_root),
            "landmark_agendas": str(life_dir / "landmark_agendas.json"),
            "journal": str(life_dir / "journal.json"),
            "hot_log": str(life_dir / "experience_hot.jsonl"),
            "virtual_chronicle": str(life_dir / "virtual_chronicle.jsonl"),
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke test LandmarkAgenda drafting and optional story preview"
    )
    parser.add_argument(
        "--strategy",
        default="agenda_draft",
        choices=["legacy_write", "agenda_draft", "agenda_story_preview", "agenda_full"],
    )
    parser.add_argument("--target-date", default="")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--life-dir", default="")
    parser.add_argument("--story-json-root", default="")
    parser.add_argument("--world-id", default="")
    parser.add_argument("--persona-narrative", default="")
    parser.add_argument("--llm-config", default="config/llm_core/config.yaml")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--schedule-minutes", type=float, default=5.0)
    parser.add_argument("--story-arc-max-steps", type=int, default=2)
    parser.add_argument("--grounding-match-threshold", type=int, default=4)
    parser.add_argument("--grounding-max-review-rounds", type=int, default=3)
    parser.add_argument("--grounding-no-create", action="store_true")
    parser.add_argument("--grounding-no-attach-to-current", action="store_true")
    parser.add_argument("--allow-node-mutation", action="store_true")
    parser.add_argument("--skip-presence-sync", action="store_true")
    parser.add_argument("--dump-json", default="")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    root = _output_root(args)
    _log(f"output root: {root}")

    from infra.llm import LLM

    cfg = _load_llm_config(args)
    llm = LLM(cfg)
    payload = _run(args, root, llm)

    if args.dump_json:
        dump_path = Path(args.dump_json)
        if not dump_path.is_absolute():
            dump_path = ROOT / dump_path
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _log(f"dumped json: {dump_path}")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
