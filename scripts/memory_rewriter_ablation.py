#!/usr/bin/env python3
"""检索 query rewriter 消融入口：底座 × 改写 矩阵 + kg_walk（语义束搜索）臂。

验证两个架构论点：
1. 结构化改写的收益主要落在**图路**（kg_spread / kg_walk——种子变准 →
   traversal 命中升），纯语义/纯文本臂收益有限（纯文本清洗 ≈ 面向
   stack 形态的退化）；
2. 束搜索遍历（kg_walk：语义方向流动 + 节点预算）对比盲 BFS（kg_spread）
   的检索质量差异。

全程确定性（无 LLM）：rewriter 是 L0 模板改写；kg_walk 用 TF-IDF 代理向量。
目标指标对齐幻觉兜底：Hit@k / MRR / SeedRecall / 噪声 FP（graceful_absence
负样本——检索不该出东西却出 = 幻觉原料）。

示例（cwd = 仓库根）::

    python scripts/memory_rewriter_ablation.py --limit 20
    python scripts/memory_rewriter_ablation.py --bases kg_spread,kg_semantic,kg_bm25
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from evals.memory_humaneness.ablation import KGStore, ablation_factory
from evals.memory_humaneness.retrieval_bench import evaluate_base
from evals.memory_humaneness.schema import load_cases
from infra.retrieval import SemanticBeamWalker, TemplateRewriter

_T0 = time.perf_counter()
log = logging.getLogger("evals.memory_humaneness")


def _setup_logging(level: int) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[rewrite-bench] %(message)s"))
    root = logging.getLogger("evals.memory_humaneness")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


# ── kg_walk 臂：BM25/实体种子 → 语义束搜索遍历 ─────────────────────────────


class KGWalkBase:
    """kg_walk 消融臂：种子（BM25 + 实体加成）→ SemanticBeamWalker。

    ``accepts_rewrite = True``：evaluate_case 会把完整 RewriteResult 传入
    recall(rewrite=...)，实体用于种子加成（图路精确种子）。向量用 TF-IDF
    代理（确定性、离线）；接真实 BGE 时换 embedder 即可，接口同构。
    """

    kind = "kg_walk"
    accepts_rewrite = True

    def __init__(self, *, beam_width: int = 3, max_nodes: int = 10, seed_top_k: int = 3):
        self._store = KGStore()
        self._beam_width = beam_width
        self._max_nodes = max_nodes
        self._seed_top_k = seed_top_k
        self._vocab: list[str] = []
        self._walker = SemanticBeamWalker(
            self._out_edges,
            self._node_vector,
            beam_width=beam_width,
            max_nodes=max_nodes,
        )

    # ── MemoryBasePort 协议 ────────────────────────────────────────────────

    def ingest(self, text: str, *, focus: str = "", emotion: str = "",
               valence: str = "neutral", interactor_id: str = "",
               tags: list[str] | None = None, meta: dict | None = None,
               days_ago: float | None = None) -> str:
        return self._store.ingest(
            text, focus=focus, emotion=emotion, valence=valence, days_ago=days_ago
        )

    def recall(self, query: str, top_k: int = 5, emotional_context: str = "",
               rewrite=None):
        from evals.memory_humaneness.ablation import tfidf_vector, tokenize
        from evals.memory_humaneness.hint import with_no_memory_hint

        nodes = self._store.nodes
        if not nodes:
            from agent.soul.memory.graph.networks.block import MemoryBlock

            return MemoryBlock(label=self.kind, entries=[])
        vocab = sorted({t for n in nodes for t in n.tokens})
        self._vocab = vocab

        bm = self._store.bm25_scores(query)
        seeds: dict[str, float] = {}
        if bm:
            max_s = max(bm.values()) or 1.0
            for i, s in sorted(bm.items(), key=lambda x: x[1], reverse=True)[: self._seed_top_k]:
                seeds[nodes[i].id] = s / max_s
        # 实体加成：rewriter 捕获的实体直接命中节点文本 → 高置信种子
        entities = list(getattr(rewrite, "entities", None) or [])
        if entities:
            for i, n in enumerate(nodes):
                if any(e and e in n.text for e in entities):
                    seeds[n.id] = max(seeds.get(n.id, 0.0), 0.95)

        qv = [tfidf_vector(tokenize(query), self._store._idf).get(t, 0.0) for t in vocab]
        hits = self._walker.walk(qv, seeds)
        idx_of = {n.id: i for i, n in enumerate(nodes)}
        entries = [
            f"[{self.kind}] {nodes[idx_of[h.node_id]].focus}："
            f"{nodes[idx_of[h.node_id]].text[:160]}"
            for h in hits
            if h.node_id in idx_of
        ][:top_k]
        entries = with_no_memory_hint(entries)
        from agent.soul.memory.graph.networks.block import MemoryBlock

        return MemoryBlock(label=self.kind, entries=entries)

    def search(self, mode: str, **kwargs):
        return [{"id": n.id, "content": n.text, "final_score": 1.0} for n in self._store.nodes]

    def dispose(self) -> None:
        pass

    # ── walker 端口适配 ────────────────────────────────────────────────────

    def _out_edges(self, node_id: str) -> list[tuple[str, float]]:
        idx_of = {n.id: i for i, n in enumerate(self._store.nodes)}
        i = idx_of.get(node_id)
        if i is None:
            return []
        return [(self._store.nodes[j].id, w) for j, w in self._store.neighbors(i)]

    def _node_vector(self, node_id: str) -> list[float] | None:
        for n in self._store.nodes:
            if n.id == node_id:
                return [n.vector.get(t, 0.0) for t in self._vocab]
        return None


def _walk_factory():
    def _make() -> KGWalkBase:
        return KGWalkBase()

    return _make


# ── 报告 ────────────────────────────────────────────────────────────────────

_METRIC_KEYS = ("hit_at_k", "mrr", "seed_recall", "false_positive_rate")


def _delta_table(results: dict[str, dict]) -> str:
    rows = []
    bases = sorted({arm.rsplit("|", 1)[0] for arm in results if "|" in arm})
    header = f"{'底座':<12} {'Hit@k':>12} {'MRR':>12} {'SeedR':>12} {'噪声FP':>12}"
    rows += [header, "-" * len(header)]
    for base in bases:
        off = results.get(f"{base}|off", {}).get("metrics", {})
        on = results.get(f"{base}|l0", {}).get("metrics", {})
        if not off or not on:
            continue
        cells = []
        for key in _METRIC_KEYS:
            d = on.get(key, 0.0) - off.get(key, 0.0)
            arrow = "↑" if d > 0 else ("↓" if d < 0 else "=")
            cells.append(f"{on.get(key, 0):.3f}{arrow}{abs(d):.3f}")
        rows.append(f"{base:<12} {cells[0]:>12} {cells[1]:>12} {cells[2]:>12} {cells[3]:>12}")
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", default=str(SRC / "evals/memory_humaneness/data/cases.jsonl")
    )
    parser.add_argument("--bases", default="kg_spread,kg_semantic,kg_bm25",
                        help="逗号分隔：kg_spread / kg_semantic / kg_bm25")
    parser.add_argument("--no-walk", action="store_true", help="去掉 kg_walk 臂")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--report-dir", default="results/memory_rewriter")
    args = parser.parse_args()

    _setup_logging(logging.INFO)
    cases = load_cases(args.dataset)
    if args.limit:
        cases = cases[: args.limit]
    log.info("数据集 %s：%d 条用例", args.dataset, len(cases))

    rewriter = TemplateRewriter()  # 纯内存模板（评测不落盘、不触发 growth）
    results: dict[str, dict] = {}

    bases = [b.strip() for b in args.bases.split(",") if b.strip()]
    if not args.no_walk:
        bases.append("kg_walk")

    for base in bases:
        factory = _walk_factory() if base == "kg_walk" else ablation_factory(base)
        for tag, rw in (("off", None), ("l0", rewriter)):
            arm = f"{base}|{tag}"
            t0 = time.perf_counter()
            results[arm] = evaluate_base(factory, cases, top_k=args.top_k, query_rewriter=rw)
            m = results[arm]["metrics"]
            log.info(
                "%-24s Hit@k=%.3f MRR=%.3f SeedR=%.3f FP=%.3f (%.1fs)",
                arm, m["hit_at_k"], m["mrr"], m["seed_recall"],
                m["false_positive_rate"], time.perf_counter() - t0,
            )

    print("\n" + _delta_table(results))

    out_dir = Path(args.report_dir) / time.strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(
            {
                arm: {
                    "metrics": r["metrics"],
                    "misses": r.get("misses", []),
                    "noise_hits": r.get("noise_hits", []),
                }
                for arm, r in results.items()
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    (out_dir / "report.md").write_text(
        "# 检索 rewriter 消融（底座 × 改写）\n\n"
        f"数据集：`{args.dataset}`（{len(cases)} 条，top_k={args.top_k}）\n\n"
        "```\n" + _delta_table(results) + "\n```\n",
        encoding="utf-8",
    )
    log.info("报告写入 %s", out_dir)


if __name__ == "__main__":
    main()
