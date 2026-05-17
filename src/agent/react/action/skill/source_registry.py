from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode

SourceKind = Literal["arxiv", "blog", "conference", "aggregator"]

_STARS = {5: "★★★★★", 4: "★★★★☆", 3: "★★★☆☆", 2: "★★☆☆☆", 1: "★☆☆☆☆"}
_KIND_LABEL = {
    "arxiv":       "论文预印本",
    "blog":        "顶级机构博客",
    "conference":  "顶级会议",
    "aggregator":  "权威聚合",
}


@dataclass(frozen=True)
class AuthoritySource:
    id: str
    name: str
    url: str
    """arxiv 信源填写 category slug（如 "cs.CL"）；其余填写完整 URL。"""
    kind: SourceKind
    tags: frozenset[str]
    priority: int
    """1 最低，5 最高权威。"""
    institution: str


# ── 信息管道地图（Pipeline Map）────────────────────────────────────────────
# 共 3 类信源：arXiv 分类流 / 顶级机构博客 / 顶会官网 / 权威聚合
# priority 5 = 顶级（顶会 + 头部 AI 实验室）
#           4 = 高（主流研究机构）
#           3 = 中（知名平台/聚合）
# ─────────────────────────────────────────────────────────────────────────────

SOURCES: list[AuthoritySource] = [
    # ── arXiv 分类流 ─────────────────────────────────────────────────────────
    AuthoritySource(
        "arxiv_cs_ai", "arXiv cs.AI", "cs.AI", "arxiv",
        frozenset({"ai", "artificial intelligence", "planning", "reasoning",
                   "agent", "knowledge", "constraint"}),
        5, "arXiv",
    ),
    AuthoritySource(
        "arxiv_cs_lg", "arXiv cs.LG", "cs.LG", "arxiv",
        frozenset({"machine learning", "ml", "deep learning", "optimization",
                   "training", "generalization", "representation"}),
        5, "arXiv",
    ),
    AuthoritySource(
        "arxiv_cs_cl", "arXiv cs.CL", "cs.CL", "arxiv",
        frozenset({"nlp", "natural language", "language model", "llm",
                   "text", "generation", "translation", "dialogue",
                   "transformer", "tokenization", "chat", "instruction"}),
        5, "arXiv",
    ),
    AuthoritySource(
        "arxiv_cs_cv", "arXiv cs.CV", "cs.CV", "arxiv",
        frozenset({"computer vision", "cv", "image", "video", "detection",
                   "segmentation", "multimodal", "visual", "3d", "diffusion"}),
        5, "arXiv",
    ),
    AuthoritySource(
        "arxiv_cs_ro", "arXiv cs.RO", "cs.RO", "arxiv",
        frozenset({"robotics", "robot", "embodied", "manipulation",
                   "navigation", "autonomous", "control", "motion"}),
        5, "arXiv",
    ),
    AuthoritySource(
        "arxiv_cs_ne", "arXiv cs.NE", "cs.NE", "arxiv",
        frozenset({"neural", "neuro", "evolutionary", "brain",
                   "spiking", "neuromorphic", "genetic"}),
        4, "arXiv",
    ),
    AuthoritySource(
        "arxiv_cs_ir", "arXiv cs.IR", "cs.IR", "arxiv",
        frozenset({"retrieval", "rag", "search", "ranking",
                   "recommendation", "information retrieval", "indexing"}),
        4, "arXiv",
    ),
    AuthoritySource(
        "arxiv_stat_ml", "arXiv stat.ML", "stat.ML", "arxiv",
        frozenset({"statistics", "probabilistic", "bayesian", "uncertainty",
                   "inference", "theory", "statistical learning"}),
        4, "arXiv",
    ),
    AuthoritySource(
        "arxiv_cs_ma", "arXiv cs.MA", "cs.MA", "arxiv",
        frozenset({"multiagent", "agent", "multi-agent", "cooperation",
                   "game theory", "social", "swarm"}),
        4, "arXiv",
    ),

    # ── 顶级 AI 研究机构博客 ────────────────────────────────────────────────
    AuthoritySource(
        "openai_blog", "OpenAI Research", "https://openai.com/news/research/",
        "blog",
        frozenset({"llm", "gpt", "safety", "alignment", "rl", "reasoning",
                   "multimodal", "ai", "o1", "o3", "chatgpt", "agent"}),
        5, "OpenAI",
    ),
    AuthoritySource(
        "anthropic_blog", "Anthropic Research", "https://www.anthropic.com/research",
        "blog",
        frozenset({"safety", "alignment", "llm", "interpretability",
                   "claude", "ai", "constitutional", "harmless"}),
        5, "Anthropic",
    ),
    AuthoritySource(
        "deepmind_blog", "Google DeepMind Research",
        "https://deepmind.google/research/publications/",
        "blog",
        frozenset({"ai", "rl", "game", "protein", "science", "robotics",
                   "multimodal", "gemini", "alphafold", "planning"}),
        5, "Google DeepMind",
    ),
    AuthoritySource(
        "google_research", "Google Research Blog",
        "https://research.google/blog/",
        "blog",
        frozenset({"ai", "ml", "nlp", "vision", "quantum", "systems",
                   "llm", "tpu", "efficient", "infrastructure"}),
        4, "Google Research",
    ),
    AuthoritySource(
        "meta_ai", "Meta AI Research",
        "https://ai.meta.com/research/publications/",
        "blog",
        frozenset({"ai", "llm", "cv", "nlp", "open source", "llama",
                   "multimodal", "video", "ar", "vr"}),
        4, "Meta AI",
    ),
    AuthoritySource(
        "microsoft_research", "Microsoft Research AI",
        "https://www.microsoft.com/en-us/research/blog/",
        "blog",
        frozenset({"ai", "ml", "nlp", "vision", "systems", "copilot",
                   "reasoning", "phi", "azure", "efficiency"}),
        4, "Microsoft Research",
    ),
    AuthoritySource(
        "huggingface_blog", "Hugging Face Blog",
        "https://huggingface.co/blog",
        "blog",
        frozenset({"open source", "model", "dataset", "transformer",
                   "nlp", "diffusion", "llm", "fine-tuning", "hub"}),
        3, "Hugging Face",
    ),
    AuthoritySource(
        "bair_blog", "Berkeley AI Research Blog",
        "https://bair.berkeley.edu/blog/",
        "blog",
        frozenset({"rl", "robotics", "ml", "ai", "safety",
                   "vision", "language", "offline rl"}),
        3, "UC Berkeley BAIR",
    ),
    AuthoritySource(
        "allenai", "Allen Institute for AI",
        "https://allenai.org/research",
        "blog",
        frozenset({"nlp", "science", "open source", "reasoning",
                   "commonsense", "olmo", "scibert", "semantic scholar"}),
        3, "Allen AI (AI2)",
    ),
    AuthoritySource(
        "mit_csail", "MIT CSAIL News",
        "https://www.csail.mit.edu/news",
        "blog",
        frozenset({"ai", "robotics", "systems", "security",
                   "vision", "ml", "hardware", "programming languages"}),
        3, "MIT CSAIL",
    ),

    # ── 顶级学术会议 ────────────────────────────────────────────────────────
    AuthoritySource(
        "neurips", "NeurIPS", "https://neurips.cc/",
        "conference",
        frozenset({"ml", "ai", "deep learning", "theory", "optimization",
                   "rl", "probabilistic", "neuroscience"}),
        5, "NeurIPS Foundation",
    ),
    AuthoritySource(
        "icml", "ICML", "https://icml.cc/",
        "conference",
        frozenset({"ml", "machine learning", "deep learning",
                   "optimization", "theory", "representation"}),
        5, "ICML",
    ),
    AuthoritySource(
        "iclr", "ICLR", "https://iclr.cc/",
        "conference",
        frozenset({"representation", "deep learning", "ml",
                   "llm", "generalization", "attention", "transformer"}),
        5, "ICLR",
    ),
    AuthoritySource(
        "acl", "ACL Anthology", "https://aclanthology.org/",
        "conference",
        frozenset({"nlp", "computational linguistics", "language",
                   "translation", "llm", "text", "generation", "emnlp", "naacl"}),
        5, "ACL Anthology",
    ),
    AuthoritySource(
        "cvpr", "CVPR / CVF", "https://cvpr.thecvf.com/",
        "conference",
        frozenset({"vision", "cv", "image", "video", "3d",
                   "detection", "multimodal", "generation"}),
        5, "CVPR / CVF",
    ),
    AuthoritySource(
        "aaai", "AAAI", "https://aaai.org/",
        "conference",
        frozenset({"ai", "planning", "reasoning", "nlp",
                   "vision", "rl", "knowledge representation"}),
        4, "AAAI",
    ),
    AuthoritySource(
        "ijcai", "IJCAI", "https://www.ijcai.org/",
        "conference",
        frozenset({"ai", "reasoning", "knowledge", "constraint",
                   "nlp", "planning", "multiagent"}),
        4, "IJCAI",
    ),

    # ── 权威聚合平台 ────────────────────────────────────────────────────────
    AuthoritySource(
        "pwc", "Papers With Code",
        "https://paperswithcode.com/latest",
        "aggregator",
        frozenset({"sota", "benchmark", "code", "reproducibility",
                   "ml", "ai", "leaderboard", "evaluation"}),
        4, "Papers With Code",
    ),
    AuthoritySource(
        "synced", "Synced Review",
        "https://syncedreview.com/",
        "aggregator",
        frozenset({"ai", "ml", "industry", "news", "research",
                   "llm", "startup", "product"}),
        3, "Synced Review",
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# SourceRegistry
# ─────────────────────────────────────────────────────────────────────────────

class SourceRegistry:
    """
    权威信源注册表。

    提供基于主题关键词 + 类别标签的信源选择，以及 arXiv API URL 构建能力。
    SOURCES 列表即为「信息管道地图」，在 select() 时按 priority × 3 + tag命中分 排序。
    """

    def __init__(self, sources: list[AuthoritySource] = SOURCES) -> None:
        self._sources = sources

    # ── 查询 ─────────────────────────────────────────────────────────────────

    def all_sources(self) -> list[AuthoritySource]:
        return list(self._sources)

    def get(self, source_id: str) -> AuthoritySource | None:
        return next((s for s in self._sources if s.id == source_id), None)

    # ── 选择 ─────────────────────────────────────────────────────────────────

    def _tag_score(self, source: AuthoritySource, keywords: list[str]) -> int:
        corpus = " ".join(source.tags).lower()
        return sum(1 for kw in keywords if kw in corpus)

    def select(
        self,
        topic: str,
        categories: list[str],
        max_arxiv: int = 3,
        max_blogs: int = 4,
        max_conferences: int = 2,
        max_aggregators: int = 1,
        min_priority: int = 3,
    ) -> list[AuthoritySource]:
        """
        按主题 + 类别从信源表中选取激活信源。

        每类信源独立排序（priority × 3 + tag命中数），各取前 N 名后合并返回。
        """
        keywords = topic.lower().split() + [c.lower() for c in categories]

        def rank(s: AuthoritySource) -> int:
            return s.priority * 3 + self._tag_score(s, keywords)

        result: list[AuthoritySource] = []
        limits: list[tuple[SourceKind, int]] = [
            ("arxiv",      max_arxiv),
            ("blog",       max_blogs),
            ("conference", max_conferences),
            ("aggregator", max_aggregators),
        ]
        for kind, limit in limits:
            pool = [s for s in self._sources if s.kind == kind and s.priority >= min_priority]
            pool.sort(key=rank, reverse=True)
            result.extend(pool[:limit])
        return result

    # ── URL 构建 ──────────────────────────────────────────────────────────────

    def build_fetch_url(
        self,
        source: AuthoritySource,
        topic: str,
        max_results: int = 15,
    ) -> str:
        """
        为 arxiv 信源拼接带主题过滤的 API URL；其余信源直接返回 url 字段。
        """
        if source.kind == "arxiv":
            params = {
                "search_query": f'cat:{source.url} AND all:"{topic}"',
                "sortBy":       "submittedDate",
                "sortOrder":    "descending",
                "max_results":  max_results,
            }
            return "https://export.arxiv.org/api/query?" + urlencode(params)
        return source.url

    # ── 渲染 ──────────────────────────────────────────────────────────────────

    def render_pipeline_map(self, selected: list[AuthoritySource]) -> str:
        """将已选信源渲染为 Markdown 表格（信息管道地图）。"""
        header = "| 信源 | 机构/平台 | 类型 | 权威等级 |\n|------|-----------|------|---------|"
        rows = [
            f"| {s.name} | {s.institution} | {_KIND_LABEL.get(s.kind, s.kind)}"
            f" | {_STARS.get(s.priority, '?')} |"
            for s in selected
        ]
        return header + "\n" + "\n".join(rows)
