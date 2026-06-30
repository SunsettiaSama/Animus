#!/usr/bin/env python3
"""Smoke test real MemoryService social profile recall."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
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
    print(f"[memory-profile-recall-smoke +{elapsed:7.2f}s] {message}", flush=True)


def _preview(value: object, *, limit: int = 220) -> str:
    text = str(value).replace("\n", " ").strip()
    if len(text) > limit:
        return f"{text[:limit]}..."
    return text


def _absolute_path(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return ROOT / p


def _load_llm_config(args: argparse.Namespace):
    from config.llm_core.config import LLMConfig

    model = args.model or os.environ.get("REACT_TEST_LLM_MODEL", "").strip()
    model = model or os.environ.get("SPEAK_SMOKE_MODEL", "").strip()
    base_url = args.base_url or os.environ.get("REACT_TEST_LLM_BASE_URL", "").strip()
    base_url = base_url or os.environ.get("SPEAK_SMOKE_BASE_URL", "").strip()
    api_key = args.api_key or os.environ.get("REACT_TEST_LLM_API_KEY", "").strip()
    api_key = api_key or os.environ.get("SPEAK_SMOKE_API_KEY", "").strip()
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "").strip()

    cfg_path = _absolute_path(args.llm_config)
    cfg = LLMConfig.from_yaml(str(cfg_path)) if cfg_path.is_file() else LLMConfig()

    model = model or cfg.model.strip()
    base_url = base_url or (cfg.base_url or "").strip()
    api_key = api_key or cfg.api_key.strip()
    backend = args.llm_backend or cfg.backend

    if not model:
        raise RuntimeError("missing LLM model: provide --model or config/llm_core/config.yaml")
    if backend != "transformers" and not api_key:
        raise RuntimeError("missing LLM api key: provide --api-key or config/llm_core/config.yaml")

    return LLMConfig(
        backend=backend,
        model=model,
        base_url=base_url or None,
        api_key=api_key,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        do_sample=cfg.do_sample,
        top_p=cfg.top_p,
        top_k=cfg.top_k,
        repetition_penalty=cfg.repetition_penalty,
        device=cfg.device,
        system_prompt=cfg.system_prompt,
        trained_model_path=cfg.trained_model_path,
    )


def _disabled_memory_infra():
    from config.soul.memory.infra_config import SoulMemoryInfraConfig
    from infra.memory import MemoryInfraService

    return MemoryInfraService(
        cfg=SoulMemoryInfraConfig(enabled=False),
        embedding=None,
        vectors=None,
    )


def _build_service(args: argparse.Namespace):
    from agent.soul.memory.service import MemoryService
    from config.infra.db_config import DBConfig
    from config.soul.memory.service_config import MemoryServiceConfig
    from infra.llm import LLM

    db_cfg = DBConfig.load_default()
    backend = args.storage_backend.strip().lower()
    if backend == "auto":
        backend = db_cfg.resolved_storage_backend()

    mysql_client = None
    if backend == "mysql":
        if not db_cfg.mysql.enabled:
            raise RuntimeError("storage backend is mysql but config/infra/db.yaml mysql.enabled=false")
        mysql_client = db_cfg.mysql.build_client()
        mysql_client.ping()

    json_root = args.json_root or db_cfg.storage.json_root
    json_root_path = _absolute_path(json_root)

    cfg = MemoryServiceConfig.load_default()
    cfg.async_ingest = bool(args.async_ingest)
    cfg.recall_top_k = int(args.top_k)

    memory_infra = None if args.vector_infra else _disabled_memory_infra()
    llm = LLM(_load_llm_config(args))
    service = MemoryService.build(
        llm=llm,
        mysql_client=mysql_client,
        cfg=cfg,
        memory_infra=memory_infra,
        storage_backend=backend,
        json_root=str(json_root_path),
    )
    return service, backend, json_root_path


def _seed_profile(service, args: argparse.Namespace) -> dict[str, str]:
    from agent.soul.memory.domain import EvolutionSource

    stamp = time.strftime("%Y%m%d_%H%M%S")
    tag = args.tag or f"smoke_profile_{stamp}"
    interactor_id = args.interactor_id or f"{tag}_alice"
    other_id = args.related_interactor_id or f"{tag}_bob"
    display_name = args.display_name or "Alice Smoke"

    _log(f"seeding social profile: interactor_id={interactor_id}")
    service.register_core_portrait(
        interactor_id,
        {
            "name": display_name,
            "background_facts": [
                f"memory profile smoke participant, tag={tag}",
                "在互联网公司做产品，最近关注晋升答辩。",
            ],
            "core_traits": ["细心", "表达清晰", f"smoke-token-{tag}"],
            "interpersonal_style": "会先确认对方是否理解，再继续展开细节。",
            "values": ["可靠交付", "诚实反馈"],
            "cognitive_style": "偏结构化，会把模糊问题拆成可验证的片段。",
            "boundaries": ["不喜欢未经确认就替她做决定。"],
        },
        agent_relation="我觉得她愿意倾听，也值得信赖；和她讨论问题时需要给出清晰上下文。",
        display_name=display_name,
    )
    service.register_core_portrait(
        other_id,
        {
            "name": args.related_display_name or "Bob Smoke",
            "background_facts": [f"memory profile smoke related participant, tag={tag}"],
            "core_traits": ["安静", "谨慎"],
        },
        display_name=args.related_display_name or "Bob Smoke",
    )
    service.link_interactor_relation(
        interactor_id,
        other_id,
        label=f"smoke 关系锚点 {tag}",
        content=(
            f"{display_name} 和 {args.related_display_name or 'Bob Smoke'} 常一起讨论产品方案；"
            f"她曾提到自己养了一只名叫蓝莓的橘猫。检索锚点：{tag}。"
        ),
    )
    service._social.add_supplement(
        interactor_id,
        label=f"smoke 检索邻域 {tag}",
        content=(
            f"她最近在准备晋升答辩，会把风险、证据和用户反馈整理成清单。"
            f"蓝莓那只橘猫常在她开会时跳上桌面。检索锚点：{tag}。"
        ),
    )
    service.evolve_core(
        interactor_id,
        delta=f"smoke 观察：她在压力下仍倾向于用清单稳定节奏，tag={tag}",
        source=EvolutionSource.manual,
    )
    return {"tag": tag, "interactor_id": interactor_id, "other_id": other_id}


def _print_block(title: str, text: str) -> None:
    print(f"\n=== {title} ===")
    print(text.strip() or "(empty)")


def _portrait_to_dict(result) -> dict:
    return {
        "session_id": result.session_id,
        "turn_index": result.turn_index,
        "interactor_id": result.interactor_id,
        "display_name": result.display_name,
        "core_traits": list(result.core_traits),
        "portrait_body": result.portrait_body,
        "agent_relation": result.agent_relation,
        "recent_impression": result.recent_impression,
        "neighborhood_snippets": list(result.neighborhood_snippets),
        "portrait_text": result.portrait_text,
    }


def _run_recall(service, args: argparse.Namespace, seeded: dict[str, str]) -> None:
    interactor_id = seeded["interactor_id"]
    tag = seeded["tag"]
    queries = args.query or [
        f"橘猫 蓝莓 {tag}",
        f"晋升答辩 清单 {tag}",
        f"可靠交付 诚实反馈 {tag}",
    ]
    for idx, query in enumerate(queries, start=1):
        _log(f"recall_social query {idx}: {_preview(query)}")
        block = service.recall_social(
            query,
            top_k=args.top_k,
            interactor_id="" if args.global_recall else interactor_id,
        )
        _print_block(f"recall_social #{idx}: {query}", block.render())


def _run_portrait_requests(service, args: argparse.Namespace, seeded: dict[str, str]) -> None:
    interactor_id = seeded["interactor_id"]
    tag = seeded["tag"]
    static_results = []
    dynamic_results = []
    probe_results = []

    service.on_static_portrait_ready(static_results.append)
    service.on_interactor_portrait_ready(dynamic_results.append)

    service.request_static_interactor_portrait(
        interactor_id=interactor_id,
        session_id=f"{tag}_static_session",
        turn_index=0,
    )
    service.request_speak_interactor_portrait(
        session_id=f"{tag}_hinted_session",
        turn_index=1,
        user_text=f"我想继续聊聊蓝莓那只橘猫，还有晋升答辩的清单。tag={tag}",
        agent_text="我记得你会把风险和证据分开整理。",
        hinted_interactor_id=interactor_id,
    )

    service.on_interactor_portrait_ready(probe_results.append)
    service.request_speak_interactor_portrait(
        session_id=f"{tag}_probe_session",
        turn_index=2,
        user_text=f"蓝莓那只橘猫又跳上桌了吗？晋升答辩清单还顺利吗？tag={tag}",
        agent_text="",
        hinted_interactor_id="",
    )

    if args.async_ingest and args.wait_sec > 0:
        time.sleep(args.wait_sec)

    payload = {
        "static": [_portrait_to_dict(item) for item in static_results],
        "dynamic_hinted": [_portrait_to_dict(item) for item in dynamic_results],
        "dynamic_probe": [_portrait_to_dict(item) for item in probe_results],
    }
    _print_block("portrait requests", json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a real MemoryService social profile recall smoke.",
    )
    parser.add_argument("--storage-backend", choices=["auto", "mysql", "json"], default="mysql")
    parser.add_argument("--json-root", default="")
    parser.add_argument("--llm-config", default="config/llm_core/config.yaml")
    parser.add_argument("--llm-backend", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--tag", default="")
    parser.add_argument("--interactor-id", default="")
    parser.add_argument("--display-name", default="")
    parser.add_argument("--related-interactor-id", default="")
    parser.add_argument("--related-display-name", default="")
    parser.add_argument("--global-recall", action="store_true")
    parser.add_argument("--vector-infra", action="store_true")
    parser.add_argument("--async-ingest", action="store_true")
    parser.add_argument("--wait-sec", type=float, default=1.0)
    parser.add_argument("--no-seed", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    _log("building real MemoryService")
    service, backend, json_root = _build_service(args)
    _log(f"MemoryService ready: backend={backend}, json_root={json_root}")

    if args.no_seed:
        if not args.interactor_id:
            raise RuntimeError("--no-seed requires --interactor-id")
        seeded = {
            "tag": args.tag or args.interactor_id,
            "interactor_id": args.interactor_id,
            "other_id": args.related_interactor_id,
        }
    else:
        seeded = _seed_profile(service, args)

    _run_recall(service, args, seeded)
    _run_portrait_requests(service, args, seeded)
    _log("done")


if __name__ == "__main__":
    main()
