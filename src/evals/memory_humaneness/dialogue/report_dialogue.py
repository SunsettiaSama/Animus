"""拟人度管线：聚合与报告。"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from .judge_dialogue import DIALOGUE_DIMENSIONS
from .simulator import DialogueRecord

DIMS = tuple(DIALOGUE_DIMENSIONS.keys())


def aggregate_dialogue(records: list[DialogueRecord]) -> dict:
    ok = [r for r in records if not r.error and r.judge]
    by_base: dict[str, list[DialogueRecord]] = defaultdict(list)
    for r in ok:
        by_base[r.base].append(r)
    summary: dict[str, dict] = {}
    for base, recs in by_base.items():
        dims = {}
        for d in DIMS:
            vals = [r.judge["scores"].get(d, 0.0) for r in recs]
            dims[d] = round(sum(vals) / len(vals), 3) if vals else 0.0
        summary[base] = {
            "n": len(recs),
            "error_n": sum(1 for r in records if r.error and r.base == base),
            "avg_turns": round(sum(len(r.turns) for r in recs) / len(recs), 1),
            "avg_reply_len": round(sum(
                len(t.agent) for r in recs for t in r.turns
            ) / max(1, sum(len(r.turns) for r in recs)), 1),
            "judge_source": {
                src: sum(1 for r in recs if r.judge.get("judge") == src)
                for src in {r.judge.get("judge") for r in recs}
            },
            "dimensions": dims,
        }
    return summary


def write_dialogue_report(
    records: list[DialogueRecord], out_dir: str | Path, meta: dict,
) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = aggregate_dialogue(records)
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    with (out / "records.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r.to_dict(), ensure_ascii=False))
            fh.write("\n")

    bases = sorted(summary.keys())
    lines = ["# 拟人度管线：多轮对话 × 记忆基座 对比报告", ""]
    lines.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    for k, v in meta.items():
        lines.append(f"- {k}: {v}")
    lines.append("")

    lines.append("## 总览（轨迹级评分，1~5）")
    lines.append("")
    header = "| 基座 | n | 均轮数 | 回复均长 | " + " | ".join(DIMS) + " |"
    lines += [header, "|---|---|---|---|" + "---|" * len(DIMS)]
    for b in bases:
        s = summary[b]
        row = [b, str(s["n"]), str(s["avg_turns"]), str(s["avg_reply_len"])]
        row += [f"{s['dimensions'][d]:.2f}" for d in DIMS]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## 分场景 overall")
    lines.append("")
    themes = []
    for r in records:
        if not r.error and (r.theme, r.scenario_id) not in themes:
            themes.append((r.theme, r.scenario_id))
    lines.append("| 场景 | " + " | ".join(bases) + " |")
    lines.append("|---|" + "---|" * len(bases))
    by_key: dict[tuple, dict[str, float]] = defaultdict(dict)
    for r in records:
        if r.error or not r.judge:
            continue
        by_key[(r.theme, r.scenario_id)][r.base] = r.judge["scores"].get("overall", 0.0)
    for (theme, sid), vals in by_key.items():
        cells = [f"{vals.get(b, float('nan')):.2f}" if b in vals else "-" for b in bases]
        lines.append(f"| {theme} ({sid}) | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## 评委来源（llm_expert 占比 = 数据可信度）")
    lines.append("")
    lines.append("| 基座 | llm_expert | heuristic |")
    lines.append("|---|---|---|")
    for b in bases:
        js = summary[b]["judge_source"]
        lines.append(f"| {b} | {js.get('llm_expert', 0)} | {js.get('heuristic', 0)} |")
    lines.append("")

    lines.append("## 样本摘录（每基座首个场景的末两轮）")
    lines.append("")
    seen: set[str] = set()
    for r in records:
        if r.error or r.base in seen or not r.turns:
            continue
        seen.add(r.base)
        for t in r.turns[-2:]:
            lines.append(f"- **{r.base}** [{r.scenario_id}] 用户：{t.user[:60]}")
            lines.append(f"  {t.agent[:120]}")
    report = out / "report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
