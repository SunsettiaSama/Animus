"""probes — 就绪探测原语。

约定：
- 每个探测函数返回纯 dict（可 JSON 化），不自建异常体系——探测失败也是
  一种"结果"，由上层决定如何呈现；
- ``state`` 为 duck-typed 宿主状态（webui 的 AppState / 未来无头宿主的等价物），
  只经 ``getattr`` 读取，缺属性按"未就绪"处理，不抛错；
- 重探测（yaml 装载、DBConfig 解析）在函数内 try 包裹，保证快照永不 500。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any


def python_env() -> dict[str, Any]:
    return {
        "version": sys.version.split()[0],
        "platform": sys.platform,
    }


def config_health() -> dict[str, Any]:
    """run.yaml 可装载 + llm_core 配置文件存在。"""
    detail = ""
    ok = True
    try:
        from config import paths
        from config.agent.run_config import RunConfig

        RunConfig.load()
        llm_cfg = getattr(paths, "llm_config_yaml", "")
        if llm_cfg and not os.path.exists(llm_cfg):
            ok = False
            detail = f"缺少 LLM 配置：{llm_cfg}"
    except Exception as exc:  # noqa: BLE001 — 配置损坏属于"结果"而非错误
        ok = False
        detail = f"配置装载失败：{exc}"
    return {"ok": ok, "detail": detail}


def llm_probe(state: Any) -> dict[str, Any]:
    service = getattr(state, "llm_service", None)
    status: dict = {}
    if service is not None:
        try:
            status = dict(service.status() or {})
        except Exception:  # noqa: BLE001
            status = {}
    handle_ready = bool(
        service is not None and getattr(service, "handle", None) is not None
    )
    return {
        "loaded": service is not None,
        "handle_ready": handle_ready,
        "state": status.get("state"),
        "model": status.get("model"),
        "backend": status.get("backend"),
        "degraded_reason": status.get("degraded_reason"),
    }


def storage_probe() -> dict[str, Any]:
    try:
        from config.infra.db_config import DBConfig

        db_cfg = DBConfig.load_default()
        backend = db_cfg.resolved_storage_backend()
        mysql_enabled = bool(db_cfg.mysql.enabled)
        return {
            "backend": backend,
            "mysql_enabled": mysql_enabled,
            "mysql_blocking": backend == "mysql",
            "ok": True if backend != "mysql" else mysql_enabled,
        }
    except Exception as exc:  # noqa: BLE001
        return {"backend": None, "mysql_enabled": False,
                "mysql_blocking": False, "ok": False, "error": str(exc)}


def persona_probe(state: Any) -> dict[str, Any]:
    cfg_file = getattr(state, "persona_cfg_file", "")
    d: dict = {}
    if cfg_file and os.path.exists(cfg_file):
        try:
            with open(cfg_file, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:  # noqa: BLE001
            d = {}
    persona_dir = getattr(state, "persona_dir", "")
    files = {
        "profile_exists": os.path.isfile(os.path.join(persona_dir, "profile.json")),
        "built_profile_exists": os.path.isfile(
            os.path.join(persona_dir, "built_profile.json")
        ),
        "self_concept_exists": os.path.isfile(
            os.path.join(persona_dir, "self_concept.json")
        ),
    }
    return {"enabled": bool(d.get("enabled", False)), "files": files}


def soul_probe(state: Any) -> dict[str, Any]:
    soul = getattr(state, "soul_service", None)
    running = bool(soul is not None and soul.is_running)
    return {
        "present": soul is not None,
        "running": running,
        "state": getattr(soul, "state", None) if soul is not None else None,
        "speak_initialized": bool(
            running and soul is not None and soul.speak_initialized
        ),
        "init_error": str(getattr(state, "soul_init_error", "") or ""),
    }


def embedding_probe(state: Any) -> dict[str, Any]:
    model = ""
    try:
        from config.soul.memory.infra_config import SoulMemoryInfraConfig

        model = str(SoulMemoryInfraConfig.load_default().model_name_or_path)
    except Exception:  # noqa: BLE001
        model = ""
    router = getattr(state, "inbound_router", None)
    embedder = getattr(router, "_embedder", None) if router is not None else None
    ready = bool(embedder is not None and embedder.is_ready())
    return {
        "model": model,
        "wired": embedder is not None,
        "ready": ready,  # 懒加载：未 ready 不代表故障，仅未预热
    }
