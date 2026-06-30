#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
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
    print(f"[story-scene-grounding-smoke +{elapsed:6.2f}s] {message}", flush=True)


def _log_block(title: str, content: str) -> None:
    _log(f"{title} BEGIN")
    print(content.strip() or "（空）", flush=True)
    _log(f"{title} END")


def _preview(value: object, *, limit: int = 360) -> str:
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


class RecordingLLM:
    def __init__(self, llm, *, logger=None, full_log: bool = True) -> None:
        self._llm = llm
        self.calls: list[dict] = []
        self._logger = logger
        self._full_log = full_log

    def generate_messages(self, messages) -> str:
        call_no = len(self.calls) + 1
        system = messages[0].content if messages else ""
        human = messages[-1].content if messages else ""
        if self._logger is not None:
            self._logger(
                f"real_llm_call[{call_no}] start "
                f"system={_preview(system, limit=120)} "
                f"human={_preview(human, limit=180)}"
            )
        started = time.perf_counter()
        raw = self._llm.generate_messages(messages)
        elapsed = time.perf_counter() - started
        if self._logger is not None:
            self._logger(
                f"real_llm_call[{call_no}] done in {elapsed:.2f}s "
                f"raw={_preview(raw, limit=240)}"
            )
            if self._full_log:
                _log_block(f"real_llm_call[{call_no}].system_full", system)
                _log_block(f"real_llm_call[{call_no}].human_full", human)
                _log_block(f"real_llm_call[{call_no}].raw_full", raw)
        self.calls.append(
            {
                "system": system,
                "human": human,
                "raw": raw,
                "system_preview": _preview(system, limit=220),
                "human_preview": _preview(human, limit=420),
                "raw_preview": _preview(raw, limit=900),
                "elapsed_sec": round(elapsed, 3),
            }
        )
        return raw


def _card(card_id: str, title: str, description: str, affordances: list[str]) -> dict:
    return {
        "id": card_id,
        "title": title,
        "description": description,
        "affordances": affordances,
        "conditions": ["仅使用当前场景中已声明的地点与物件"],
        "entities": [],
    }


def _result_to_dict(result) -> dict:
    return {
        "scene_id": result.scene_id,
        "scene_name": result.scene_name,
        "matched_by": result.matched_by,
        "score": result.score,
        "created": result.created,
        "blocked_reason": result.blocked_reason,
        "narrative": result.narrative,
        "cards": [card.to_dict() for card in result.cards],
        "trace": [entry.to_dict() for entry in result.trace],
    }


def _scene_to_dict(scene) -> dict:
    return {
        "id": scene.id,
        "name": scene.name,
        "narrative": scene.narrative,
        "tags": list(scene.tags),
        "cards": scene.meta.get("cards") or [],
    }


def _edge_to_dict(edge) -> dict:
    return {
        "id": edge.id,
        "from_scene_id": edge.from_scene_id,
        "to_scene_id": edge.to_scene_id,
        "transition_text": edge.transition_text,
        "weight": edge.weight,
    }


def _log_grounding_result(label: str, result) -> None:
    status = "blocked" if result.blocked_reason else "ok"
    _log(
        f"{label}: status={status} scene={result.scene_name or '(none)'} "
        f"matched_by={result.matched_by or '(none)'} created={result.created}"
    )
    if result.blocked_reason:
        _log(f"{label}: blocked_reason={result.blocked_reason}")
    if result.narrative:
        _log(f"{label}: description={result.narrative}")
    if result.trace:
        for entry in result.trace:
            _log(f"{label}: trace R{entry.round} {entry.action}: {entry.observation}")
    if result.cards:
        for card in result.cards:
            affordances = "、".join(card.affordances) if card.affordances else "（无）"
            conditions = "、".join(card.conditions) if card.conditions else "（无）"
            _log(
                f"{label}: card={card.title} description={card.description} "
                f"affordances={affordances} conditions={conditions}"
            )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Story Scene Grounding construction and worldview review smoke."
    )
    parser.add_argument("--json-root", default="")
    parser.add_argument("--world-id", default="grounding-smoke")
    parser.add_argument("--dump-json", default="")
    parser.add_argument(
        "--real-create",
        action="store_true",
        help="Run one real LLM scene creation through drafter + inspector.",
    )
    parser.add_argument(
        "--real-create-cue",
        default="明天在北坡风蚀岩棚建立苔藓湿度与裂隙朝向的观察点",
    )
    parser.add_argument("--llm-config", default="config/llm_core/config.yaml")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--real-draft-rounds", type=int, default=4)
    parser.add_argument("--real-review-rounds", type=int, default=2)
    parser.add_argument(
        "--allow-node-mutation",
        action="store_true",
        help="Allow the real scene drafter to propose and apply existing-node/card mutations.",
    )
    parser.add_argument(
        "--compact-llm-log",
        action="store_true",
        help="Only print preview snippets for LLM interactions.",
    )
    return parser


def _json_root(args: argparse.Namespace) -> Path:
    if args.json_root.strip():
        path = Path(args.json_root)
        return path if path.is_absolute() else ROOT / path
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ROOT / ".react" / "smoke" / "story_scene_grounding" / stamp


def run(args: argparse.Namespace) -> dict:
    from infra.storage import JsonStorageService
    from storyview.engine import StoryEngine
    from storyview.scene.cards import cards_to_meta
    from storyview.store.json import StoryStoreBundle
    from storyview.types import SceneCard, SceneDraft, SceneGroundingPolicy
    from storyview.world.inspector import WorldviewInspector
    from storyview.world.provider import WorldviewProvider

    root = _json_root(args)
    root.mkdir(parents=True, exist_ok=True)
    world_id = args.world_id.strip() or "grounding-smoke"
    _log(f"json root: {root}")
    _log(f"world id: {world_id}")

    stores = StoryStoreBundle(JsonStorageService(str(root)))
    stores.world.ensure(
        world_id,
        title="边境自然志",
        era="低技术边境营地",
        setting="观察、记录与复核自然样本的日常世界。",
        tone="克制、具体、以可观察行动为主",
        canon_json={
            "forbidden": ["星门", "史诗战争"],
            "must": ["不离开已声明场景网络"],
            "prefer": ["优先使用已有场景和固定观察点"],
        },
    )
    engine = StoryEngine(stores, llm=None)

    home_id = engine.upsert_scene(
        world_id,
        name="营地帐篷",
        narrative="营地帐篷里有基础补给与路线牌，是场景网络的 home 节点。",
        tags=["home", "camp"],
    )
    engine.apply_scene(world_id, home_id)
    desk_cards = [
        SceneCard.from_dict(_card("desk-record", "记录台", "整理标本册与观察记录的固定台面。", ["整理记录", "核对标签"])),
        SceneCard.from_dict(_card("desk-box", "标本盒", "暂存待核对样本的盒子。", ["核对样本", "标记遗漏"])),
        SceneCard.from_dict(_card("desk-lamp", "冷光台灯", "提供稳定照明的桌面灯。", ["检查细节", "复核编号"])),
    ]
    desk_id = engine.upsert_scene(
        world_id,
        name="窗边书桌",
        narrative="窗边书桌用于整理标本册、核对标签与补写观察记录。",
        tags=["desk", "records"],
        meta=cards_to_meta(desk_cards),
    )
    engine.link_scenes(
        world_id,
        from_scene_id=home_id,
        to_scene_id=desk_id,
        transition_text="从营地帐篷走到窗边书桌",
        weight=10,
    )
    no_card_id = engine.upsert_scene(
        world_id,
        name="无卡档案柜",
        narrative="旧档案柜里堆放着没有整理完的资料，但尚未配置互动卡片。",
        tags=["archive"],
    )
    engine.link_scenes(
        world_id,
        from_scene_id=home_id,
        to_scene_id=no_card_id,
        transition_text="从营地帐篷走到无卡档案柜",
        weight=5,
    )

    _log("grounding existing scene with continuous Chinese cue")
    existing = engine.ground_scene_for_cue(
        world_id,
        "明天在窗边书桌整理标本册并核对标签",
        policy=SceneGroundingPolicy(allow_create=True, match_threshold=4),
    )
    _log_grounding_result("existing", existing)

    _log("grounding matched scene without cards")
    missing_cards = engine.ground_scene_for_cue(
        world_id,
        "明天在无卡档案柜整理旧资料",
        policy=SceneGroundingPolicy(allow_create=True, match_threshold=4),
    )
    _log_grounding_result("missing_cards", missing_cards)

    _log("auto-creating scene and linking it into network")
    created = engine.ground_scene_for_cue(
        world_id,
        "明天在溪岸样线复核苔藓观察记录",
        policy=SceneGroundingPolicy(allow_create=True, match_threshold=99),
    )
    _log_grounding_result("created", created)

    _log("running worldview forbidden-canon review")
    provider = WorldviewProvider(stores)
    inspector = WorldviewInspector(provider, llm=None)
    forbidden_draft = SceneDraft(
        name="星门战场",
        narrative="这里出现星门，并引发史诗战争。",
        cards=(
            SceneCard(id="bad-1", title="星门", description="世界观禁止的装置。"),
            SceneCard(id="bad-2", title="战旗", description="史诗战争的旗帜。"),
            SceneCard(id="bad-3", title="指挥台", description="推动高冲突支线。"),
        ),
    )
    review = inspector.review_scene_draft(
        world_id,
        "明天观察星门战场",
        forbidden_draft,
        context=provider.existing_context(world_id),
    )
    _log(f"worldview_review: status={getattr(review.status, 'value', review.status)}")
    _log(f"worldview_review: reason={review.reason}")

    real_created = None
    real_llm_calls: list[dict] = []
    if args.real_create:
        from infra.llm import LLM
        from storyview.scene.drafting import SceneDraftingEngine
        from storyview.scene.grounding import SceneGroundingService

        _log("running real LLM scene creation through drafter + inspector")
        recording_llm = RecordingLLM(
            LLM(_load_llm_config(args)),
            logger=_log,
            full_log=not args.compact_llm_log,
        )
        engine.set_llm(recording_llm)
        real_provider = WorldviewProvider(stores)
        real_inspector = WorldviewInspector(real_provider, llm=recording_llm)
        real_drafter = SceneDraftingEngine(
            real_provider,
            llm=recording_llm,
            max_rounds=max(1, args.real_draft_rounds),
        )
        engine._grounding = SceneGroundingService(
            stores,
            engine.scene_network,
            worldview_provider=real_provider,
            inspector=real_inspector,
            drafter=real_drafter,
            llm=recording_llm,
        )
        real_created = engine.ground_scene_for_cue(
            world_id,
            args.real_create_cue,
            policy=SceneGroundingPolicy(
                allow_create=True,
                match_threshold=99,
                max_review_rounds=max(1, args.real_review_rounds),
                attach_to_current=True,
                allow_node_mutation=args.allow_node_mutation,
            ),
        )
        _log_grounding_result("real_created", real_created)
        real_llm_calls = list(recording_llm.calls)
        if args.compact_llm_log:
            for idx, call in enumerate(real_llm_calls, start=1):
                _log(f"real_llm_call[{idx}].system={call['system_preview']}")
                _log(f"real_llm_call[{idx}].human={call['human_preview']}")
                _log(f"real_llm_call[{idx}].raw={call['raw_preview']}")

    scenes = engine.list_scenes(world_id)
    edges = stores.scene.edges.list_by_world(world_id)
    outgoing_from_home = [edge for edge in edges if edge.from_scene_id == home_id]
    created_linked = any(edge.to_scene_id == created.scene_id for edge in outgoing_from_home)
    real_created_linked = (
        any(edge.to_scene_id == real_created.scene_id for edge in outgoing_from_home)
        if real_created is not None and real_created.scene_id
        else False
    )

    checks = {
        "existing_scene_matched": existing.scene_id == desk_id and not existing.created,
        "continuous_chinese_cue_matched": existing.scene_id == desk_id,
        "matched_scene_without_cards_blocked": bool(missing_cards.blocked_reason),
        "auto_created_scene": created.created and bool(created.scene_id),
        "auto_created_scene_linked_from_home": created_linked,
        "worldview_forbidden_rejected": str(review.status) == "SceneReviewStatus.rejected"
        or str(review.status) == "rejected",
    }
    if args.real_create:
        checks["real_llm_created_scene"] = (
            real_created is not None
            and real_created.created
            and bool(real_created.scene_id)
            and not real_created.blocked_reason
        )
        checks["real_llm_created_scene_linked_from_home"] = real_created_linked
    _log(f"checks: {json.dumps(checks, ensure_ascii=False)}")
    _log("network outgoing_from_home:")
    for edge in outgoing_from_home:
        target = next((scene for scene in scenes if scene.id == edge.to_scene_id), None)
        target_name = target.name if target is not None else edge.to_scene_id
        target_desc = target.narrative if target is not None else ""
        _log(
            f"- {target_name}: transition={edge.transition_text} "
            f"weight={edge.weight} description={target_desc}"
        )

    return {
        "world_id": world_id,
        "json_root": str(root),
        "seed": {
            "home_id": home_id,
            "desk_id": desk_id,
            "no_card_id": no_card_id,
        },
        "grounding": {
            "existing": _result_to_dict(existing),
            "missing_cards": _result_to_dict(missing_cards),
            "created": _result_to_dict(created),
        },
        "worldview_review": {
            "status": str(getattr(review.status, "value", review.status)),
            "reason": review.reason,
        },
        "real_creation": {
            "cue": args.real_create_cue,
            "result": _result_to_dict(real_created) if real_created is not None else None,
            "llm_calls": real_llm_calls,
            "linked_from_home": real_created_linked,
            "allow_node_mutation": args.allow_node_mutation,
        } if args.real_create else None,
        "network": {
            "scenes": [_scene_to_dict(scene) for scene in scenes],
            "edges": [_edge_to_dict(edge) for edge in edges],
            "outgoing_from_home": [_edge_to_dict(edge) for edge in outgoing_from_home],
        },
        "checks": checks,
    }


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    payload = run(args)
    if args.dump_json.strip():
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
