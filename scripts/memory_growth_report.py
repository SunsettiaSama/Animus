#!/usr/bin/env python3
"""记忆成长报表 CLI（R2.3）：从事件流水 + 快照重建成长曲线与判定报告。

输入默认取 ``.react/telemetry/``（可 ``--telemetry-dir`` 覆盖），输出
``results/memory_growth/<run>/report.md`` + ``metrics.json``（含 F1–F7 漏斗、
G1–G5 五维、H1/H2/H4 命中与 Q1–Q8 判定，口径见 PRD 第二节）。

示例（cwd = 仓库根）::

    python scripts/memory_growth_report.py
    python scripts/memory_growth_report.py --telemetry-dir .react/telemetry --tag run42
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agent.soul.memory.telemetry.report import (  # noqa: E402
    build_growth_report,
    load_events,
    load_growth_stats,
    load_snapshots,
    write_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="记忆成长报表")
    parser.add_argument("--telemetry-dir", default=".react/telemetry", help="telemetry 根目录")
    parser.add_argument(
        "--growth-stats",
        default=".react/retrieval/growth_stats.json",
        help="growth 模板统计（H4）；不存在则跳过",
    )
    parser.add_argument("--out-root", default="results/memory_growth", help="报告输出根目录")
    parser.add_argument("--tag", default="", help="run 标签（默认时间戳）")
    parser.add_argument("--events", default="", help="显式指定事件文件（调试用，默认 <dir>/memory_events.jsonl）")
    parser.add_argument("--snapshots", default="", help="显式指定快照目录（默认 <dir>/snapshots）")
    args = parser.parse_args()

    telemetry_dir = Path(args.telemetry_dir)
    events_path = Path(args.events) if args.events else telemetry_dir / "memory_events.jsonl"
    snapshot_dir = Path(args.snapshots) if args.snapshots else telemetry_dir / "snapshots"

    events = load_events(events_path)
    snapshots = load_snapshots(snapshot_dir)
    if not events and not snapshots:
        print(f"[growth-report] 无数据：{events_path} 与 {snapshot_dir} 均为空", file=sys.stderr)
        return 1

    growth_stats = load_growth_stats(args.growth_stats)
    metrics = build_growth_report(events, snapshots, growth_stats=growth_stats)

    tag = args.tag.strip() or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_root) / tag
    report_path = write_report(out_dir, metrics)

    print(f"[growth-report] 事件 {len(events)} 条 / 快照 {len(snapshots)} 份")
    funnel = metrics["funnel"]
    print(
        f"[growth-report] 漏斗 F1={funnel['F1_units_created']} "
        f"F2={funnel['F2_annotated_promote']} F3={funnel['F3_submitted']} "
        f"F4={funnel['F4_nodes_created_from_units']} "
        f"(入图率 {funnel['conversions'].get('F4/F1 入图率')})"
    )
    q = metrics["questions"]
    print(
        f"[growth-report] Q2 网络变密={q['Q2_network_densifying']['answer']} "
        f"Q3 用进废退={q['Q3_use_it_or_lose_it']['answer']} "
        f"Q4 跨会话想起={q['Q4_cross_session_recall']['answer']}"
    )
    print(f"[growth-report] 报告：{report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
