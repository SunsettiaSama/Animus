"""L2 检索质量基准（确定性，无 LLM）：query → 应命中记忆 的 Hit@k / MRR / 噪声控制。

与 L3 行为基准共用 cases.jsonl：每条用例天然是
``(查询 = 历史+当前输入, 应命中 = 预载记忆, 锚点 = must_remember)`` 三元组。

- 命中判定：检索行中包含任一 must_remember 锚点；
- ``graceful_absence`` 用例作为负样本：期望检索为空，非空记为假阳性（噪声控制）；
- 只取返回的前 ``top_k`` 行参与评测（对 full 这类"全量"基座一视同仁地截断）。

对 compact 这类查询无关基座，该基准度量的是“信息经压缩后的存活率”，
同样有意义；对 none 恒为 0，仅作对照。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .bases import preload
from .schema import HumanenessCase

log = logging.getLogger("evals.memory_humaneness")


@dataclass
class CaseEval:
    case_id: str
    category: str
    expected_empty: bool
    lines: list[str] = field(default_factory=list)
    hit_at_k: bool = False
    first_hit_rank: int = 0  # 0 = 无命中
    seed_recall: float = 0.0
    false_positive: bool = False
    # query rewriter 元数据（query_rewriter=None 时为空）
    rewrite_template: str = ""
    rewrite_entities: list[str] = field(default_factory=list)
    rewrite_query: str = ""


def _entry_hit(line: str, anchors: list[str]) -> bool:
    return any(a and a in line for a in anchors)


def _strip_hint_lines(lines: list[str]) -> list[str]:
    """graceful_absence 的"无记忆提示"行不算检索结果（与 L3 行为评测同语义），
    否则 hint 行会把负样本全部记成假阳性。"""
    from .hint import is_hint_line

    return [l for l in lines if not is_hint_line(l)]


def evaluate_case(base, case: HumanenessCase, *, top_k: int = 5, query_rewriter=None) -> CaseEval:
    query = " ".join(
        [t.text for t in case.history] + [case.current_user]
    ).strip()
    rewrite_template, rewrite_entities, rewrite_query = "", [], ""
    if query_rewriter is not None:
        rr = query_rewriter.rewrite(query)
        query = rr.query
        rewrite_template = rr.template_id
        rewrite_entities = list(rr.entities)
        rewrite_query = rr.query

    accepts_rewrite = getattr(base, "accepts_rewrite", False)
    if accepts_rewrite and query_rewriter is not None:
        block = base.recall(query, top_k=top_k, rewrite=rr)
    else:
        block = base.recall(query, top_k=top_k)
    lines = _strip_hint_lines(list(block.entries or [])[:top_k])

    def _meta() -> dict:
        return dict(
            rewrite_template=rewrite_template,
            rewrite_entities=rewrite_entities,
            rewrite_query=rewrite_query,
        )

    if not case.memories:  # graceful_absence：负样本，期望空
        return CaseEval(
            case_id=case.case_id,
            category=case.category,
            expected_empty=True,
            lines=lines,
            false_positive=bool(lines),
            **_meta(),
        )

    first_hit_rank = 0
    for i, line in enumerate(lines, 1):
        if _entry_hit(line, case.must_remember):
            first_hit_rank = i
            break

    # seed 级覆盖：锚点归属到包含它的 seed（多记忆拼接用例自然拆分）
    covered = 0
    for seed in case.memories:
        seed_anchors = [a for a in case.must_remember if a in seed.text] or list(case.must_remember)
        if any(_entry_hit(line, seed_anchors) for line in lines):
            covered += 1
    seed_recall = covered / len(case.memories) if case.memories else 0.0

    return CaseEval(
        case_id=case.case_id,
        category=case.category,
        expected_empty=False,
        lines=lines,
        hit_at_k=first_hit_rank > 0,
        first_hit_rank=first_hit_rank,
        seed_recall=seed_recall,
        **_meta(),
    )


def evaluate_base(
    base_or_factory, cases: list[HumanenessCase], *, top_k: int = 5, query_rewriter=None
) -> dict:
    """``base_or_factory``：基座实例（复用）或工厂（每条用例全新实例，防止用例间污染）。

    工厂模式下每条用例先实例化 → 预载记忆 → 检索 → 销毁，与 L3 行为基准同协议。
    ``query_rewriter``：可选 QueryRewriter，插在 query 构造与 recall 之间（默认
    None = 原始拼接 query，行为与历史版本一致）。
    """
    per_case_fresh = callable(base_or_factory)
    evals: list[CaseEval] = []
    for case in cases:
        base = base_or_factory() if per_case_fresh else base_or_factory
        preload(base, case.memories)
        evals.append(
            evaluate_case(base, case, top_k=top_k, query_rewriter=query_rewriter)
        )
        if per_case_fresh:
            dispose = getattr(base, "dispose", None)
            if callable(dispose):
                dispose()

    positive = [e for e in evals if not e.expected_empty]
    negative = [e for e in evals if e.expected_empty]
    hit_n = sum(1 for e in positive if e.hit_at_k)
    mrrs = [1.0 / e.first_hit_rank for e in positive if e.first_hit_rank > 0]
    metrics = {
        "base": getattr(base, "kind", "?"),
        "n_positive": len(positive),
        "n_negative": len(negative),
        "hit_at_k": round(hit_n / len(positive), 4) if positive else 0.0,
        "mrr": round(sum(mrrs) / len(positive), 4) if positive else 0.0,
        "seed_recall": round(sum(e.seed_recall for e in positive) / len(positive), 4)
        if positive else 0.0,
        "false_positive_rate": round(
            sum(1 for e in negative if e.false_positive) / len(negative), 4
        ) if negative else 0.0,
    }
    misses = [
        {"case_id": e.case_id, "category": e.category, "lines": e.lines[:top_k]}
        for e in positive if not e.hit_at_k
    ]
    noise = [
        {"case_id": e.case_id, "lines": e.lines[:top_k]}
        for e in negative if e.false_positive
    ]
    return {"metrics": metrics, "misses": misses, "noise_hits": noise, "cases": evals}


def format_table(results: dict[str, dict]) -> str:
    header = f"{'基座':<8} {'Hit@k':>7} {'MRR':>7} {'SeedR':>7} {'噪声FP':>7} {'n':>5}"
    rows = [header, "-" * len(header)]
    for base, r in results.items():
        m = r["metrics"]
        rows.append(
            f"{base:<8} {m['hit_at_k']:>7.3f} {m['mrr']:>7.3f} "
            f"{m['seed_recall']:>7.3f} {m['false_positive_rate']:>7.3f} {m['n_positive']:>5}"
        )
    return "\n".join(rows)
