"""infra.retrieval — 检索引擎基座：结构化 rewriter、成长引擎、kmeans 入口定位、语义束搜索。

分层契约：只做检索侧实现，数据层无关（端口只认 (id, vector) /
(to_id, weight) / HitSignal 等通用类型）。知识库/文档接入属数据层职责，
通过同一端口对接本包。
"""
from __future__ import annotations

from infra.retrieval.growth import (
    AuthorLLM,
    GrowthConfig,
    GrowthEngine,
    TemplateStats,
)
from infra.retrieval.locate import LocatorConfig, SemanticLocator
from infra.retrieval.rewriter import (
    HitSignal,
    QueryRewriter,
    RewriteResult,
    TemplateRewriter,
)
from infra.retrieval.templates import (
    BUILTIN_TEMPLATES,
    DEFAULT_DROP_POS,
    RewriteTemplate,
    TemplateStore,
)
from infra.retrieval.tokenizer import TokenizedTerm, backend, tokenize
from infra.retrieval.walk import SemanticBeamWalker, WalkHit

__all__ = [
    "AuthorLLM",
    "BUILTIN_TEMPLATES",
    "DEFAULT_DROP_POS",
    "GrowthConfig",
    "GrowthEngine",
    "HitSignal",
    "LocatorConfig",
    "QueryRewriter",
    "RewriteResult",
    "RewriteTemplate",
    "SemanticBeamWalker",
    "SemanticLocator",
    "TemplateStats",
    "TemplateRewriter",
    "TemplateStore",
    "TokenizedTerm",
    "WalkHit",
    "backend",
    "get_default_rewriter",
    "tokenize",
]


def build_rewriter(
    *,
    store_root: str = ".react/retrieval",
    llm: AuthorLLM | None = None,
    growth_enabled: bool = True,
    cache_size: int = 512,
) -> TemplateRewriter:
    """便捷装配：store + growth（可选 LLM）+ rewriter。评测/接线用。"""
    from pathlib import Path

    root = Path(store_root)
    store = TemplateStore(root / "templates.json")
    growth = GrowthEngine(
        store,
        llm=llm,
        cfg=GrowthConfig(enabled=growth_enabled),
        stats_path=str(root / "growth_stats.json"),
    )
    return TemplateRewriter(store, growth=growth, cache_size=cache_size)


_DEFAULT_REWRITER: TemplateRewriter | None = None


def get_default_rewriter() -> TemplateRewriter | None:
    """进程级默认 rewriter（生产接线用）。

    - 开关读 config/infra/retrieval.yaml 的 rewriter.enabled（默认开）；
    - growth 统计先行（R4.1）：模板使用/命中反馈持久化到
      ``<store_root>/growth_stats.json``（入口 B 的 report() 回调喂给这里）；
      生产不注入 LLM——authoring（造模板）默认关闭，待统计跑出分化后再放开（D4）；
    - 模板库带持久化（``<store_root>/templates.json``，grown 模板可复用）；
    - 失败安全：任何装配异常返回 None（调用方拿到 None = 维持旧行为）。
    """
    global _DEFAULT_REWRITER
    if _DEFAULT_REWRITER is not None:
        return _DEFAULT_REWRITER
    try:
        from pathlib import Path

        from config.infra.retrieval_config import RetrievalConfig

        cfg = RetrievalConfig.load_default()
        if not cfg.rewriter.enabled:
            return None
        root = Path(cfg.store_root)
        store = TemplateStore(root / "templates.json")
        growth = (
            GrowthEngine(
                store,
                llm=None,
                cfg=cfg.growth,
                stats_path=str(root / "growth_stats.json"),
            )
            if cfg.growth.enabled
            else None
        )
        _DEFAULT_REWRITER = TemplateRewriter(store, growth=growth, cache_size=cfg.rewriter.cache_size)
    except Exception:
        return None
    return _DEFAULT_REWRITER
