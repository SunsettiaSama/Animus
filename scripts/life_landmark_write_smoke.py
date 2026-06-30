#!/usr/bin/env python3
"""Smoke test landmark composition and journal writing."""

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

_DEFAULT_PERSONA_NARRATIVE = (
    "你是莉奈娅，边境探险队的博物学家与记录者。"
    "你说话不急，习惯先听清环境与风声再开口；"
    "出野外前会核对标本册、放大镜与记录本，"
    "观察时有耐心，记录克制，不轻易下结论，也不热衷追逐惊奇的旁支线索。"
)


def _log(message: str) -> None:
    elapsed = time.perf_counter() - _T0
    print(f"[life-landmark-write-smoke +{elapsed:7.2f}s] {message}", flush=True)


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
    root = ROOT / ".react" / "smoke" / f"life_landmark_write_{stamp}"
    root.mkdir(parents=True, exist_ok=True)
    _log(f"created output root: {root}")
    return root


def _life_dir(args: argparse.Namespace, root: Path) -> Path:
    if args.life_dir:
        life = Path(args.life_dir)
        if not life.is_absolute():
            life = ROOT / life
        life.mkdir(parents=True, exist_ok=True)
        _log(f"using provided life_dir: {life}")
        return life
    life = root / "life"
    life.mkdir(parents=True, exist_ok=True)
    _log(f"using isolated life_dir: {life}")
    return life


def _json_root(args: argparse.Namespace, root: Path) -> Path:
    if args.story_json_root:
        json_root = Path(args.story_json_root)
        if not json_root.is_absolute():
            json_root = ROOT / json_root
        json_root.mkdir(parents=True, exist_ok=True)
        _log(f"using provided story json root: {json_root}")
        return json_root
    json_root = root / "soul_db"
    json_root.mkdir(parents=True, exist_ok=True)
    _log(f"using isolated story json root: {json_root}")
    return json_root


def _seed_home_scenes(port, world_id: str) -> dict[str, str]:
    from storyview.bootstrap import ensure_default_world_scenes

    return ensure_default_world_scenes(port, world_id)


def _recent_landmark_dicts(manager, *, limit: int = 5) -> list[dict]:
    items = manager.journal.all_landmarks()
    items.sort(key=lambda item: item.created_at, reverse=True)
    return [item.to_dict() for item in items[:limit]]


def _build_stack(args: argparse.Namespace, root: Path, llm):
    from agent.soul.life import LifeManager
    from agent.soul.life.experience import LifeExperienceStack
    from agent.soul.presence import PresenceService
    from storyview.bridge import StoryWorldContextBridge
    from storyview.port import StoryPort
    from storyview.service import StoryService

    life_dir = _life_dir(args, root)
    manager = LifeManager(life_dir=str(life_dir), llm=llm)
    profile = manager.load_profile()
    world_id = args.world_id.strip() or profile.resolved_world_id("smoke-life-landmark")
    manager.bind_story_world(world_id)

    story_json_root = _json_root(args, root)
    _log("constructing StoryService(json backend)")
    story = StoryService(
        llm=llm,
        storage_backend="json",
        json_root=str(story_json_root),
    )
    _log("starting StoryService worker")
    story.start()
    port = StoryPort(story)
    _log("seeding story scenes")
    scenes = _seed_home_scenes(port, world_id)
    _log(f"seeded scenes={scenes}")

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
    manager.set_story_world_context_supplier(
        StoryWorldContextBridge(port, world_id=world_id)
    )

    persona_narrative = (
        args.persona_narrative.strip()
        or profile.narrative.strip()
        or _DEFAULT_PERSONA_NARRATIVE
    )
    manager.sync_agent_persona_narrative(persona_narrative)
    _log(f"applied persona narrative: {_preview(persona_narrative, limit=180)}")

    return manager, stack, story, port, scenes, life_dir, story_json_root, world_id, profile


def _run(args: argparse.Namespace, root: Path, llm) -> dict:
    manager, stack, story, _port, scenes, life_dir, story_json_root, world_id, profile = (
        _build_stack(args, root, llm)
    )
    scheduled_at = (
        datetime.now(timezone.utc) + timedelta(minutes=args.schedule_minutes)
    ).isoformat()

    before_recent = _recent_landmark_dicts(manager)
    _log(f"journal before count={len(manager.journal.all_landmarks())}")
    if before_recent:
        _log(f"journal latest before={_preview(before_recent[0])}")

    _log("calling manager.compose_landmark")
    started = time.perf_counter()
    draft = manager.compose_landmark()
    _log(
        f"compose_landmark returned in {time.perf_counter() - started:.2f}s "
        f"draft={_preview(draft)}"
    )
    if draft is None:
        raise RuntimeError("compose_landmark returned None")

    planned = None
    if args.action == "compose-and-plan":
        _log(f"planning generated landmark scheduled_at={scheduled_at}")
        started = time.perf_counter()
        planned = manager.plan_landmark(
            intention=draft["intention"],
            scheduled_at=scheduled_at,
            context=draft.get("context", ""),
        )
        _log(f"plan_landmark returned in {time.perf_counter() - started:.2f}s")
        if planned is None:
            raise RuntimeError("plan_landmark returned None")
    else:
        _log("compose-only selected; journal write skipped")

    hot = manager.hot_experiences(hours=None)
    chronicle = manager.recent_chronicle(days=1, tail=20)
    presence_sync = stack.sync_presence("tao") if planned is not None else {}
    journal = manager.journal.to_dict()
    after_recent = _recent_landmark_dicts(manager)

    _log(f"journal after count={len(manager.journal.all_landmarks())}")
    if after_recent:
        _log(f"journal latest after={_preview(after_recent[0])}")
    _log("stopping StoryService and LifeManager")
    story.stop()
    manager.stop()

    return {
        "action": args.action,
        "world_id": world_id,
        "profile": profile.to_dict(),
        "generated_landmark": draft,
        "scheduled_at": scheduled_at,
        "planned_event": planned or {},
        "journal_before_recent": before_recent,
        "journal_after_recent": after_recent,
        "journal": journal,
        "hot": hot,
        "chronicle": chronicle,
        "presence_sync": presence_sync,
        "seed_scenes": scenes,
        "files": {
            "root": str(root),
            "life_dir": str(life_dir),
            "story_json_root": str(story_json_root),
            "journal": str(life_dir / "journal.json"),
            "hot_log": str(life_dir / "experience_hot.jsonl"),
            "virtual_chronicle": str(life_dir / "virtual_chronicle.jsonl"),
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke test current-state landmark composition and journal writing"
    )
    parser.add_argument(
        "--action",
        choices=("compose-only", "compose-and-plan"),
        default="compose-and-plan",
    )
    parser.add_argument("--llm-config", default="config/llm_core/config.yaml")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--output-root", default="")
    parser.add_argument(
        "--life-dir",
        default="",
        help="existing life directory to load and write; default uses isolated smoke output",
    )
    parser.add_argument(
        "--story-json-root",
        default="",
        help="storyview json root; default uses isolated smoke output",
    )
    parser.add_argument(
        "--world-id",
        default="",
        help="story world id; default uses stored life_profile world_id or smoke-life-landmark",
    )
    parser.add_argument(
        "--persona-narrative",
        default="",
        help="agent persona for compose context; default uses stored life_profile narrative or smoke persona",
    )
    parser.add_argument("--schedule-minutes", type=float, default=5.0)
    return parser


def main() -> None:
    _log("script entry")
    args = _build_parser().parse_args()
    _log(
        f"parsed args action={args.action} "
        f"world_id={args.world_id or '(profile/default)'} max_tokens={args.max_tokens}"
    )
    root = _output_root(args)
    cfg = _load_llm_config(args)

    from infra.llm import LLM

    _log("constructing LLM facade")
    llm = LLM(cfg)
    _log(f"LLM facade ready model={cfg.model} root={root}")
    if args.base_url or cfg.base_url:
        _log(f"base_url={cfg.base_url}")

    summary = _run(args, root, llm)
    life_dir = Path(summary["files"]["life_dir"])
    _log(
        "artifact counts "
        f"hot_lines={_count_lines(life_dir / 'experience_hot.jsonl')} "
        f"virtual_chronicle_lines={_count_lines(life_dir / 'virtual_chronicle.jsonl')}"
    )
    _log("final summary json follows")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
