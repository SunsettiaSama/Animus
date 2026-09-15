"""AB 报告：软约束标注 A/B 的聚合与呈现。"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from .runner import ABRecord


def aggregate_ab(records: list[ABRecord]) -> dict:
    by_arm: dict[str, list[ABRecord]] = defaultdict(list)
    for r in records:
        if not r.error:
            by_arm[r.arm].append(r)
    out: dict[str, dict] = {}
    for arm, recs in by_arm.items():
        assoc = [r.association for r in recs]
        mis = [r.misreference for r in recs]
        n = len(recs)
        mentions = sum(1 for a in assoc if a.get("mention"))
        hedged = sum(1 for a in assoc if a.get("hedged"))
        misrefs = sum(m.get("mentions", 0) for m in mis)
        dims: dict[str, list[float]] = defaultdict(list)
        judge_src: dict[str, int] = defaultdict(int)
        for r in recs:
            for k, v in (r.judge.get("scores") or {}).items():
                dims[k].append(float(v))
            judge_src[r.judge.get("judge", "?")] += 1
        dim_mean = {k: round(sum(vs) / len(vs), 3) for k, vs in dims.items()}
        out[arm] = {
            "n": n,
            "mention_rate": round(mentions / n, 3) if n else 0.0,
            "hedged_of_mentioned": round(hedged / mentions, 3) if mentions else 0.0,
            "misreference_total": misrefs,
            "misreference_rate": round(
                sum(1 for m in mis if m.get("mentions", 0) > 0) / n, 3) if n else 0.0,
            "judge_dims": dim_mean,
            "overall": dim_mean.get("overall", 0.0),
            "judge_source": dict(judge_src),
        }
    return out


def write_ab_report(records: list[ABRecord], out_dir: str | Path,
                    meta: dict) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = aggregate_ab(records)
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "records.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r.to_dict(), ensure_ascii=False))
            fh.write("\n")

    arms = sorted(summary.keys())
    lines = ["# 软约束标注 A/B 报告（唯一变量：边缘记忆的呈现方式）", ""]
    lines.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    for k, v in meta.items():
        lines.append(f"- {k}: {v}")
    lines.append("")

    lines.append("## 联想行为（确定性判定，核心指标）")
    lines.append("")
    lines.append("| 臂 | n | 联想提及率 | 提起时犹豫口吻 | 干扰误引用率 | 干扰误引用次数 |")
    lines.append("|---|---|---|---|---|---|")
    for arm in arms:
        s = summary[arm]
        lines.append(
            f"| {arm} | {s['n']} | {s['mention_rate']:.2f} | "
            f"{s['hedged_of_mentioned']:.2f} | {s['misreference_rate']:.2f} | "
            f"{s['misreference_total']} |")
    lines.append("")

    lines.append("## 轨迹评委维度")
    lines.append("")
    dim_keys = ("emotional_attunement", "human_likeness",
                "memory_naturalness", "initiative_rhythm", "overall")
    lines.append("| 臂 | " + " | ".join(dim_keys) + " |")
    lines.append("|---|" + "---|" * len(dim_keys))
    for arm in arms:
        d = summary[arm]["judge_dims"]
        cells = [f"{d.get(k, 0):.2f}" for k in dim_keys]
        lines.append(f"| {arm} | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## 联想时机样本（各臂 trigger 轮前后）")
    lines.append("")
    for r in records:
        if r.error or not r.turns:
            continue
        t0 = r.association.get("trigger_turn", 0)
        for t in r.turns[max(0, t0 - 1): t0 + 2]:
            lines.append(f"- **{r.arm}/{r.scenario_id}** 用户：{t.user[:56]}")
            lines.append(f"  小澄：{t.agent[:110]}")
    report = out / "report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
