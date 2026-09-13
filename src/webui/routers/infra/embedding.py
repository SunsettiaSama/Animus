from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter()


# ── Embedding 模型全局配置 ────────────────────────────────────────────────────
#
# 协议：config/embedding/model.yaml（EmbeddingConfig）是整个项目 embedding 模型的
# 唯一权威来源 —— SoulMemoryInfraConfig.load_default() 与 webui InboundRouter 都
# 从这里读。UI 不再向 config/soul/memory/infra.yaml 写 embedding 段（那里写的值
# 会在加载时被本文件覆盖）。
#
# 生效时机：修改后需要重启 —— embedding 模型变更涉及 torch 模型重载，且向量维度
# 可能变化导致 Qdrant collection 需要重建；本协议刻意不提供热切换。


@router.get("/api/embedding/config")
def get_embedding_config():
    from config import paths
    from config.agent.memory.embedding_config import EmbeddingConfig

    path = str(paths.embedding_model_yaml)
    if not paths.embedding_model_yaml.exists():
        cfg = EmbeddingConfig()
        exists = False
    else:
        cfg = EmbeddingConfig.from_yaml(path)
        exists = True
    return {
        "config": {
            "model_name_or_path": cfg.model_name_or_path,
            "use_fp16": cfg.use_fp16,
            "device": cfg.device,
            "query_prefix": cfg.query_prefix,
            "passage_prefix": cfg.passage_prefix,
        },
        "path": path,
        "exists": exists,
        "requires_restart": True,
    }


@router.post("/api/embedding/config/save")
def save_embedding_config(body: dict[str, Any]):
    """写入 model.yaml 唯一权威源；不热应用（返回 requires_restart）。"""
    import yaml

    from config import paths

    cfg = (body or {}).get("config") or body or {}

    # 与 EmbeddingConfig 字段对齐；host/port/workers 属于部署配置，不从设置页写。
    data = {
        "model_name_or_path": str(cfg.get("model_name_or_path", "") or ""),
        "use_fp16": bool(cfg.get("use_fp16", True)),
        "device": str(cfg.get("device", "auto") or "auto"),
        "query_prefix": str(cfg.get("query_prefix", "query: ") or ""),
        "passage_prefix": str(cfg.get("passage_prefix", "") or ""),
    }
    if not data["model_name_or_path"]:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=400,
            content={"error": "model_name_or_path 不能为空"},
        )

    # host/port/workers 保留文件中已有值（若存在），避免被设置页意外重置。
    if paths.embedding_model_yaml.exists():
        with open(paths.embedding_model_yaml, encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}
        for key in ("host", "port", "workers"):
            if key in existing:
                data[key] = existing[key]

    path = str(paths.embedding_model_yaml)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return {"status": "ok", "path": path, "requires_restart": True}
