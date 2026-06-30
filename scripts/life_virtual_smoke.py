#!/usr/bin/env python3
"""Run a live smoke test for soul.life.virtual."""

from __future__ import annotations

import argparse
import json
import os
import shutil
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

_DEFAULT_LANDMARK_INTENTION = (
    "前往北坡风蚀岩棚观察点，复核苔藓湿度监测区与裂隙朝向标记板，"
    "记录岩棚内外湿度差异和裂隙走向"
)

_DEFAULT_LANDMARK_CONTEXT = (
    "营地北侧已有一处由风蚀岩棚改造出的固定观察点，"
    "木制工作台旁放有袖珍湿度计、裂隙朝向标记板、记录石板与测量绳；"
    "岩棚内侧有三个苔藓湿度监测位置，边界由木桩与麻线围出。"
    "这次只在既有观察点内读取、校准、复核和记录，不离开已声明的场景网络。"
)

_DEFAULT_GROUNDED_SCENE_JSON = (
    ".react/smoke/story_scene_grounding/latest_real.json"
)


def _resolve_persona_narrative(args: argparse.Namespace) -> str:
    return (args.persona_narrative or _DEFAULT_PERSONA_NARRATIVE).strip()


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
        if args.reset_output_root and root.exists():
            shutil.rmtree(root)
            _log(f"reset output root: {root}")
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
    from storyview.bootstrap import ensure_default_world_scenes

    return ensure_default_world_scenes(port, world_id)


def _load_grounded_scene(path: str) -> dict:
    scene_path = Path(path)
    if not scene_path.is_absolute():
        scene_path = ROOT / scene_path
    if not scene_path.is_file():
        raise RuntimeError(f"grounded scene json not found: {scene_path}")
    payload = json.loads(scene_path.read_text(encoding="utf-8"))
    scene = payload.get("real_creation", {}).get("result") or {}
    if not scene.get("scene_name") or not scene.get("narrative"):
        raise RuntimeError(f"grounded scene json missing real_creation.result: {scene_path}")
    return scene


def _resolve_home_scene_id(port, world_id: str, seeded: dict[str, str]) -> str:
    if seeded.get("home"):
        return seeded["home"]
    for scene in port.list_scenes(world_id):
        tags = set(getattr(scene, "tags", ()) or ())
        if "home" in tags or getattr(scene, "name", "") == "营地帐篷":
            return scene.id
    raise RuntimeError(f"home scene not found for world_id={world_id}")


def _seed_grounded_scene(
    port,
    world_id: str,
    *,
    grounded_scene_json: str,
    seeded: dict[str, str],
    apply_as_current: bool,
) -> dict[str, str]:
    scene = _load_grounded_scene(grounded_scene_json)
    scene_id = port.upsert_scene(
        world_id,
        name=scene["scene_name"],
        narrative=scene["narrative"],
        location_id=f"{world_id}-north-slope-rock-shelter-loc",
        tags=["agenda", "grounded", "observation"],
        scene_id=scene.get("scene_id") or None,
        meta={"cards": scene.get("cards") or []},
    )
    home_id = _resolve_home_scene_id(port, world_id, seeded)
    port.link_scenes(
        world_id,
        from_scene_id=home_id,
        to_scene_id=scene_id,
        transition_text=f"前往 {scene['scene_name']}",
        weight=12,
    )
    if apply_as_current:
        port.apply_scene(
            world_id,
            scene_id,
            transition_text=f"进入 {scene['scene_name']}",
        )
    _log(
        "seeded grounded scene "
        f"scene_id={scene_id} name={scene['scene_name']} cards={len(scene.get('cards') or [])} "
        f"apply_as_current={apply_as_current}"
    )
    return {"grounded_scene": scene_id, "grounded_scene_name": scene["scene_name"]}


def _preview_public_landmark_cue(
    *,
    landmark_id: str,
    intention: str,
    context: str = "",
) -> str:
    parts = [
        "【触发来源】journal_landmark",
        f"【journal_landmark_id】{landmark_id}",
        f"【公开预约意图】{intention.strip()}",
    ]
    if context.strip():
        parts.append(f"【公开预约背景】{context.strip()}")
    parts.append(
        "【主持规则】以上意图为 Soul 与 storyview 共享的公开行动声明；"
        "你只能据此主持问题和选项，不得替 Soul 决定最终行动或动机。"
    )
    return "\n".join(parts)


def _log_location_snapshots(port, world_id: str, *, label: str = "location") -> None:
    current = port.current_location_snapshot(world_id)
    recent = port.list_location_snapshots(world_id, limit=5)
    if current is None:
        _log(f"{label}: no current location snapshot")
        return
    _log(
        f"{label} current scene_id={current.scene_id} "
        f"reason={getattr(current.reason, 'value', current.reason)} "
        f"text={_preview(current.scene_text, limit=160)}"
    )
    if recent:
        _log(f"{label} recent snapshots count={len(recent)}")


def _log_fill_payload(fill: dict, *, port=None, world_id: str = "") -> None:
    if not fill:
        _log("fill result empty")
        return
    _log(f"landmark_id={fill.get('landmark_id')} intention={_preview(fill.get('intention', ''))}")
    _log(f"journal diary hint={_preview(fill.get('hint', fill.get('narrative', '')))}")
    for idx, step in enumerate(fill.get("arc_steps", []) or [], start=1):
        _log(f"arc step {idx} GM question: {_preview(step.get('gm_question', ''))}")
        _log(f"arc step {idx} Soul answer: {_preview(step.get('soul_answer', ''))}")
        _log(f"arc step {idx} objective feedback: {_preview(step.get('resolution_text', ''))}")
        _log(
            f"arc step {idx} dice d100={step.get('dice_value', 0)} "
            f"tendency={_preview(step.get('dice_tendency', ''))} "
            f"story_direction={_preview(step.get('story_direction', ''))} "
            f"decision_importance={_preview(step.get('decision_importance', ''))}"
        )
    episode = fill.get("episode") or {}
    if episode:
        _log(f"episode_id={episode.get('episode_id')} scene_id={episode.get('scene_id')}")
        _log(f"episode summary={_preview(episode.get('objective_summary', ''))}")
    typed_items = fill.get("typed_memory_items") or []
    if typed_items:
        _log(f"typed memory item drafts count={len(typed_items)}")
        for item in typed_items[:6]:
            _log(
                f"  - {item.get('item_type')} focus={_preview(item.get('focus', ''))} "
                f"text={_preview(item.get('text', ''))}"
            )
    rejected = fill.get("rejected_memory_items") or []
    if rejected:
        _log(f"rejected memory items count={len(rejected)}")
        for item in rejected[:4]:
            _log(
                f"  - {item.get('item_type')} reason={_preview(item.get('rejection_reason', ''))}"
            )
    _log(f"selected scene_id={fill.get('scene_id')}")
    _log(f"objective arc: {_preview(fill.get('resolution_text', ''))}")
    _log(f"decision importance: {_preview(fill.get('decision_importance', ''))}")
    _log(f"subjective narrative: {_preview(fill.get('narrative', ''))}")
    if port is not None and world_id:
        _log_location_snapshots(port, world_id, label="after fill")


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


class _MemoryNarrativeContextSupplier:
    def __init__(self, memory) -> None:
        self._memory = memory

    def refresh(self, layer, purpose, *, query: str = "") -> None:
        _ = purpose
        q = query.strip()
        if not q:
            layer.update_context(continuity_memories=[])
            return
        lines = self._memory.continuity_for_narrative(q)
        layer.update_context(continuity_memories=list(lines[:2]))


def _disabled_memory_infra():
    from config.soul.memory.infra_config import SoulMemoryInfraConfig
    from infra.memory import MemoryInfraService

    return MemoryInfraService(
        cfg=SoulMemoryInfraConfig(enabled=False),
        embedding=None,
        vectors=None,
    )


def _build_memory_service(root: Path, llm, *, vector_infra: bool = False):
    from agent.soul.memory.service import MemoryService
    from config.soul.memory.service_config import MemoryServiceConfig
    from infra.memory import MemoryInfraService

    cfg = MemoryServiceConfig.load_default()
    cfg.async_ingest = False
    memory_infra = MemoryInfraService.build() if vector_infra else _disabled_memory_infra()
    memory = MemoryService.build(
        llm=llm,
        cfg=cfg,
        memory_infra=memory_infra,
        storage_backend="json",
        json_root=str(root / "soul_db"),
    )
    memory.init_infra()
    return memory


def _node_to_summary(node) -> dict:
    if node is None:
        return {}
    return {
        "id": getattr(node, "id", ""),
        "type": getattr(node, "MEMORY_TYPE", ""),
        "focus": getattr(node, "focus", ""),
        "fact": getattr(node, "fact", ""),
        "perception": getattr(node, "perception", ""),
        "life_event_id": getattr(node, "life_event_id", ""),
        "meta": dict(getattr(node, "meta", {}) or {}),
    }


def _recall_queries(args: argparse.Namespace, fill: dict) -> list[str]:
    queries = [item.strip() for item in (args.recall_query or []) if item.strip()]
    if queries:
        return queries
    defaults = [
        str(fill.get("intention") or args.intention or "").strip(),
        str((fill.get("episode") or {}).get("scene_name") or "").strip(),
        str((fill.get("episode") or {}).get("objective_summary") or "").strip(),
    ]
    for item in fill.get("typed_memory_items", []) or []:
        text = str(item.get("text") or "").strip()
        if text:
            defaults.append(text)
            break
    return list(dict.fromkeys(q for q in defaults if q))[:3]


def _observe_memory(memory, args: argparse.Namespace, *, fill: dict) -> dict:
    if memory is None or not fill:
        return {"enabled": False}
    experience_id = str(fill.get("experience_id") or "").strip()
    root = memory.get_unit(experience_id) if experience_id else None
    recent = memory.search("recent", limit=args.memory_recent_limit)
    episode_recent = [
        item
        for item in recent
        if (item.get("meta") or {}).get("source_experience_id") == experience_id
        or item.get("id") == experience_id
    ]
    queries = _recall_queries(args, fill)
    recalls = []
    for query in queries:
        block = memory.recall(query, top_k=args.memory_top_k)
        continuity = memory.continuity_for_narrative(query)
        rendered = block.render() if hasattr(block, "render") else str(block)
        recalls.append(
            {
                "query": query,
                "recall": rendered,
                "continuity_for_narrative": list(continuity),
            }
        )
        _log(f"memory recall query={_preview(query)}")
        _log(_preview(rendered, limit=420))
        if continuity:
            _log(f"memory continuity: {_preview(' | '.join(continuity), limit=420)}")
    root_summary = _node_to_summary(root)
    if root_summary:
        _log(
            "memory root node "
            f"id={root_summary.get('id')} type={root_summary.get('type')} "
            f"meta={root_summary.get('meta')}"
        )
    _log(
        "memory recent "
        f"total={len(recent)} episode_related={len(episode_recent)}"
    )
    return {
        "enabled": True,
        "experience_id": experience_id,
        "root": root_summary,
        "recent": recent,
        "episode_recent": episode_recent,
        "recalls": recalls,
    }


def _flush_soul_memory(service) -> None:
    service.workers.memory.submit(lambda: None).result()


def _build_virtual_stack(
    root: Path,
    llm,
    world_id: str,
    *,
    arc_steps: int = 3,
    start_policy: str = "history",
    persona_narrative: str = "",
    seed_grounded_scene: bool = False,
    grounded_scene_json: str = "",
    grounded_scene_as_current: bool = True,
    enable_memory: bool = False,
    vector_infra: bool = False,
):
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
    grounded: dict = {}
    if seed_grounded_scene:
        scenes.update(
            _seed_grounded_scene(
                port,
                world_id,
                grounded_scene_json=grounded_scene_json,
                seeded=scenes,
                apply_as_current=grounded_scene_as_current,
            )
        )
        _log_location_snapshots(port, world_id, label="after grounded scene seed")
        grounded = _load_grounded_scene(grounded_scene_json)

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
    memory = None
    if enable_memory:
        _log(
            "constructing MemoryService(json backend) "
            f"vector_infra={vector_infra}"
        )
        memory = _build_memory_service(root, llm, vector_infra=vector_infra)
        memory.set_agent_persona_provider(lambda: manager.virtual.profile_narrative)
        manager.set_memory_port(memory.life_port)
        manager.set_narrative_context_supplier(_MemoryNarrativeContextSupplier(memory))
        _log("wired memory promotion and narrative continuity supplier")
    _log("binding presence")
    stack.bind_presence(presence)
    _log("wiring story port and world context supplier")
    manager.set_story_port(port)
    manager.set_gm_answerer(_smoke_gm_answer)
    manager.set_story_arc_max_steps(arc_steps)
    manager.set_story_start_policy(start_policy)
    manager.set_story_world_context_supplier(
        StoryWorldContextBridge(port, world_id=world_id)
    )
    _log("loading life profile")
    manager.load_profile()
    manager.bind_story_world(world_id)
    if seed_grounded_scene:
        manager.set_bound_scene(
            scenes["grounded_scene"],
            scene_name=scenes.get("grounded_scene_name", grounded.get("scene_name", "")),
            scene_cards=grounded.get("cards") or [],
        )
        _log(
            "bound landmark scene "
            f"scene_id={scenes['grounded_scene']} cards={len(grounded.get('cards') or [])}"
        )
    if persona_narrative.strip():
        manager.sync_agent_persona_narrative(persona_narrative)
        _log(f"applied persona narrative: {_preview(persona_narrative, limit=160)}")
    _log("virtual stack ready")
    return manager, stack, story, port, scenes, memory


def _run_virtual_mode(args: argparse.Namespace, root: Path, llm) -> dict:
    persona_narrative = _resolve_persona_narrative(args)
    manager, stack, story, port, scenes, memory = _build_virtual_stack(
        root,
        llm,
        args.world_id,
        arc_steps=args.arc_steps,
        start_policy=args.start_policy,
        persona_narrative=persona_narrative,
        seed_grounded_scene=args.seed_grounded_scene,
        grounded_scene_json=args.grounded_scene_json,
        grounded_scene_as_current=not args.keep_home_current,
        enable_memory=args.enable_memory,
        vector_infra=args.vector_infra,
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
        _log(f"persona narrative: {_preview(persona_narrative, limit=160)}")
        if planned.get("landmark_id"):
            public_cue = _preview_public_landmark_cue(
                landmark_id=str(planned["landmark_id"]),
                intention=args.intention,
                context=args.context,
            )
            _log(f"public journal cue preview:\n{public_cue}")
        only_ids = None
        if args.fill_seeded_only and planned.get("landmark_id"):
            only_ids = [str(planned["landmark_id"])]
            skipped = [
                lm.id
                for lm in manager.journal.due_landmarks()
                if lm.id not in set(only_ids)
            ]
            if skipped:
                _log(
                    "warning: skipping historical due landmarks "
                    f"count={len(skipped)} ids={skipped[:4]}"
                )
        _log(
            "calling manager.fill_due_landmarks "
            f"(start_policy={args.start_policy}, arc_steps={args.arc_steps}, "
            f"fill_seeded_only={bool(only_ids)}, "
            "public journal cue -> GM arc -> diary fill expected)"
        )
        started = time.perf_counter()
        fills = manager.fill_due_landmarks(only_ids=only_ids)
        _log(f"fill_due_landmarks done in {time.perf_counter() - started:.2f}s count={len(fills)}")
        _log(f"processed landmark_ids={[item.get('landmark_id') for item in fills]}")
        fill = fills[0] if fills else {}
        _log_fill_payload(fill, port=port, world_id=args.world_id)
        memory_observation = _observe_memory(memory, args, fill=fill)
        result = {
            "planned": planned,
            "fills": fills,
            "seed_scenes": scenes,
            "start_policy": args.start_policy,
            "fill_seeded_only": bool(only_ids),
            "processed_landmark_ids": [item.get("landmark_id") for item in fills],
            "memory": memory_observation,
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
            _log_fill_payload(result)
            if port is not None:
                _log_location_snapshots(port, args.world_id, label="after surprise")
        result = {**result, "seed_scenes": scenes, "start_policy": args.start_policy}
        if result.get("triggered"):
            result["memory"] = _observe_memory(memory, args, fill=result)
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
    service.life.api.set_story_start_policy(args.start_policy)
    persona_narrative = _resolve_persona_narrative(args)
    service.life.api.sync_agent_persona_narrative(persona_narrative)
    _log(f"applied persona narrative: {_preview(persona_narrative, limit=160)}")
    _log(f"SoulService started in {time.perf_counter() - started:.2f}s")
    story_port = getattr(service, "_story_port", None)
    if args.seed_grounded_scene and story_port is not None:
        seeded = _seed_home_scenes(story_port, args.world_id)
        seeded.update(
            _seed_grounded_scene(
                story_port,
                args.world_id,
                grounded_scene_json=args.grounded_scene_json,
                seeded=seeded,
                apply_as_current=not args.keep_home_current,
            )
        )
        grounded = _load_grounded_scene(args.grounded_scene_json)
        service.life.api.set_bound_scene(
            seeded["grounded_scene"],
            scene_name=seeded.get("grounded_scene_name", grounded.get("scene_name", "")),
            scene_cards=grounded.get("cards") or [],
        )
        _log_location_snapshots(story_port, args.world_id, label="soul after grounded scene seed")
    if args.action == "fill-fixed":
        _log(
            "soul fill-fixed: seeding due landmark through life.api journal "
            f"(start_policy={args.start_policy})"
        )
        planned = _seed_due_landmark(
            service.life.api,
            intention=args.intention,
            due_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            context=args.context,
        )
        _log(f"soul fill-fixed: seeded due landmark={planned}")
        if planned.get("landmark_id"):
            public_cue = _preview_public_landmark_cue(
                landmark_id=str(planned["landmark_id"]),
                intention=args.intention,
                context=args.context,
            )
            _log(f"public journal cue preview:\n{public_cue}")
        only_ids = None
        if args.fill_seeded_only and planned.get("landmark_id"):
            only_ids = [str(planned["landmark_id"])]
        if only_ids:
            skipped = [
                lm.id
                for lm in service.life.api.journal.due_landmarks()
                if lm.id not in set(only_ids)
            ]
            if skipped:
                _log(
                    "warning: skipping historical due landmarks "
                    f"count={len(skipped)} ids={skipped[:4]}"
                )
        _log("soul fill-fixed: calling fill_due_landmarks")
        started = time.perf_counter()
        fills = service.life.api.fill_due_landmarks(only_ids=only_ids)
        _log(f"fill_due_landmarks done in {time.perf_counter() - started:.2f}s count={len(fills)}")
        fill = fills[0] if fills else {}
        _log_fill_payload(
            fill,
            port=story_port,
            world_id=service.life.api.profile.resolved_world_id(),
        )
        _flush_soul_memory(service)
        memory_observation = _observe_memory(service.memory.api, args, fill=fill)
        result = {
            "planned": planned,
            "fills": fills,
            "start_policy": args.start_policy,
            "fill_seeded_only": bool(only_ids),
            "processed_landmark_ids": [item.get("landmark_id") for item in fills],
            "memory": memory_observation,
        }
    elif args.action == "surprise":
        _log(f"soul surprise: calling run_surprise_tick elapsed_sec={args.elapsed_sec}")
        started = time.perf_counter()
        result = service.run_surprise_tick(args.elapsed_sec)
        _log(f"run_surprise_tick done in {time.perf_counter() - started:.2f}s")
        if result.get("triggered"):
            _log_fill_payload(result, port=story_port, world_id=service.life.api.profile.resolved_world_id())
            _flush_soul_memory(service)
            result["memory"] = _observe_memory(service.memory.api, args, fill=result)
        result = {**result, "start_policy": args.start_policy}
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
    parser.add_argument(
        "--reset-output-root",
        action="store_true",
        help="when --output-root is fixed, delete it before running",
    )
    parser.add_argument(
        "--fill-seeded-only",
        action="store_true",
        help="fill-fixed only processes the landmark seeded in this run",
    )
    parser.add_argument(
        "--enable-memory",
        action="store_true",
        help="virtual mode wires MemoryService so landmark episodes promote into memory graph",
    )
    parser.add_argument(
        "--vector-infra",
        action="store_true",
        help="enable configured memory vector infrastructure instead of recent-only JSON recall",
    )
    parser.add_argument("--memory-top-k", type=int, default=5)
    parser.add_argument("--memory-recent-limit", type=int, default=20)
    parser.add_argument(
        "--recall-query",
        action="append",
        default=[],
        help="memory query to run after fill; can be provided multiple times",
    )
    parser.add_argument("--world-id", default="smoke-life-virtual")
    parser.add_argument(
        "--persona-narrative",
        default="",
        help="agent persona for diary/GM context; default uses 莉奈娅 expedition biologist profile",
    )
    parser.add_argument("--intention", default=_DEFAULT_LANDMARK_INTENTION)
    parser.add_argument("--context", default=_DEFAULT_LANDMARK_CONTEXT)
    parser.add_argument(
        "--seed-grounded-scene",
        action="store_true",
        help="seed the grounded rock shelter scene before running the life flow",
    )
    parser.add_argument(
        "--grounded-scene-json",
        default=_DEFAULT_GROUNDED_SCENE_JSON,
        help="story_scene_grounding smoke json containing real_creation.result",
    )
    parser.add_argument(
        "--keep-home-current",
        action="store_true",
        help="seed the grounded scene but keep the current runtime scene at home",
    )
    parser.add_argument("--schedule-minutes", type=float, default=5.0)
    parser.add_argument("--elapsed-sec", type=float, default=3600.0)
    parser.add_argument("--arc-steps", type=int, default=3)
    parser.add_argument(
        "--start-policy",
        choices=("history", "home"),
        default="history",
        help="story arc start position: history (default) or home",
    )
    return parser


def main() -> None:
    _log("script entry")
    args = _build_parser().parse_args()
    _log(
        f"parsed args mode={args.mode} action={args.action} "
        f"world_id={args.world_id} arc_steps={args.arc_steps} "
        f"start_policy={args.start_policy} max_tokens={args.max_tokens}"
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
