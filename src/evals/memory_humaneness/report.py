"""聚合与对比报告：不同记忆基座下回复行为的差异（3.3 的产出物）。"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from .runner import CaseRecord
from .schema import CATEGORIES

DIMENSIONS = ("memory_coherence", "human_likeness", "emotional_attunement",
              "non_hallucination", "overall")


def aggregate(records: list[CaseRecord]) -> dict:
    ok = [r for r in records if not r.error]
    by_base: dict[str, list[CaseRecord]] = defaultdict(list)
    for r in ok:
        by_base[r.base].append(r)

    summary: dict[str, dict] = {}
    for base, recs in by_base.items():
        per_dim = {}
        for dim in DIMENSIONS:
            vals = [r.judge.get("scores", {}).get(dim, 0.0) for r in recs]
            per_dim[dim] = round(sum(vals) / len(vals), 3) if vals else 0.0
        per_cat = {}
        for cat in CATEGORIES:
            sub = [r for r in recs if r.category == cat]
            if not sub:
                continue
            vals = [r.judge.get("scores", {}).get("overall", 0.0) for r in sub]
            per_cat[cat] = round(sum(vals) / len(vals), 3)
        summary[base] = {
            "n": len(recs),
            "error_n": sum(1 for r in records if r.error and r.base == base),
            "dimensions": per_dim,
            "overall_by_category": per_cat,
        }
    return summary


def build_markdown(summary: dict, records: list[CaseRecord], meta: dict) -> str:
    bases = sorted(summary.keys())
    lines: list[str] = []
    lines.append("# 记忆基座拟人化对比报告")
    lines.append("")
    lines.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    for k, v in meta.items():
        lines.append(f"- {k}: {v}")
    lines.append("")

    lines.append("## 总览（专家评判均分，1~5）")
    lines.append("")
    header = "| 基座 | n | " + " | ".join(DIMENSIONS) + " |"
    sep = "|---|---|" + "---|" * len(DIMENSIONS)
    lines += [header, sep]
    for base in bases:
        d = summary[base]["dimensions"]
        rows = [base, str(summary[base]["n"])] + [f"{d[dim]:.2f}" for dim in DIMENSIONS]
        lines.append("| " + " | ".join(rows) + " |")
    lines.append("")

    lines.append("## 分场景 overall（行为差异定位）")
    lines.append("")
    cats = list(CATEGORIES.keys())
    lines.append("| 场景 | " + " | ".join(bases) + " | Δ(max-min) |")
    lines.append("|---|" + "---|" * (len(bases) + 1))
    for cat in cats:
        vals = [summary[b].get("overall_by_category", {}).get(cat) for b in bases]
        present = [v for v in vals if v is not None]
        delta = f"{max(present) - min(present):.2f}" if len(present) >= 2 else "-"
        cells = [f"{v:.2f}" if v is not None else "-" for v in vals]
        lines.append(f"| {CATEGORIES[cat]} ({cat}) | " + " | ".join(cells) + f" | {delta} |")
    lines.append("")

    lines.append("## 基座间行为差异（逐维 delta，第一列为参照）")
    lines.append("")
    if len(bases) >= 2:
        ref, others = bases[0], bases[1:]
        header = "| 维度 | " + " | ".join(f"{o} vs {ref}" for o in others) + " |"
        lines += [header, "|---|" + "---|" * len(others)]
        for dim in DIMENSIONS:
            cells = [
                f"{summary[o]['dimensions'][dim] - summary[ref]['dimensions'][dim]:+.2f}"
                for o in others
            ]
            lines.append(f"| {dim} | " + " | ".join(cells) + " |")
        lines.append("")

    lines.append("## 典型样本（每基座每场景第一条回复摘录）")
    lines.append("")
    shown: set[tuple[str, str]] = set()
    for r in records:
        if r.error or (r.base, r.category) in shown:
            continue
        shown.add((r.base, r.category))
        reply = r.reply.replace("\n", " ")[:180]
        lines.append(f"- **{r.base} / {CATEGORIES.get(r.category, r.category)}** [{r.case_id}]：{reply}")
    return "\n".join(lines) + "\n"


def write_report(records: list[CaseRecord], out_dir: str | Path, meta: dict | None = None) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = aggregate(records)
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (out / "records.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r.to_dict(), ensure_ascii=False))
            fh.write("\n")
    md = build_markdown(summary, records, meta or {})
    report_path = out / "report.md"
    report_path.write_text(md, encoding="utf-8")
    return report_path
