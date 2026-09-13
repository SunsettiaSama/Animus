#!/usr/bin/env python3
"""L2 检索质量基准入口（确定性、无 LLM）。

用 cases.jsonl 的 (查询, 应命中记忆, 锚点) 三元组直接评测记忆基座的检索：
Hit@k / MRR / seed 级覆盖率 / 负样本假阳性率。改完检索代码后可秒级回归。

示例（cwd = 仓库根）::

    python scripts/memory_retrieval_bench.py                          # graph/stack/compact
    python scripts/memory_retrieval_bench.py --bases graph,stack --verbose
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

_T0 = time.perf_counter()
log = logging.getLogger("evals.memory_humaneness")


class _ElapsedFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return f"[retrieval-bench +{time.perf_counter() - _T0:7.1f}s] {record.getMessage()}"


def _setup_logging(level: int) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ElapsedFormatter())
    root = logging.getLogger("evals.memory_humaneness")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


def _base_factories(names: list[str]):
    from evals.memory_humaneness.bases import (
        CompactMemoryBase,
        FullMemoryBase,
        GraphMemoryBase,
        NullMemoryBase,
        StackMemoryBase,
    )

    table = {
        "graph": lambda: GraphMemoryBase.build(),
        "stack": lambda: StackMemoryBase.build(),
        "compact": lambda: CompactMemoryBase(),
        "full": lambda: FullMemoryBase(),
        "none": lambda: NullMemoryBase(),
    }
    factories = []
    for name in names:
        name = name.strip().lower()
        if name not in table:
            raise SystemExit(f"unknown base kind: {name!r} (expect graph/stack/compact/full/none)")
        factories.append((name, table[name]))
    return factories


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bases", default="graph,stack,compact",
                        help="逗号分隔：graph / stack / compact / full / none")
    parser.add_argument("--dataset", default=str(SRC / "evals/memory_humaneness/data/cases.jsonl"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0 = 全部）")
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--verbose", action="store_true", help="打印每条用例的命中明细")
    args = parser.parse_args()

    _setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    from evals.memory_humaneness import load_cases, validate_dataset
    from evals.memory_humaneness.retrieval_bench import evaluate_base, format_table

    cases = load_cases(args.dataset)
    problems = validate_dataset(cases)
    if problems:
        raise SystemExit("dataset invalid:\n" + "\n".join(problems))
    if args.limit > 0:
        cases = cases[: args.limit]
    log.info(
        "检索基准开始：%d 条用例，top_k=%d，基座=%s（确定性，无 LLM）",
        len(cases), args.top_k, args.bases,
    )

    results: dict[str, dict] = {}
    for name, factory in _base_factories(args.bases.split(",")):
        t0 = time.perf_counter()
        result = evaluate_base(factory, cases, top_k=args.top_k)
        results[name] = result
        m = result["metrics"]
        log.info(
            "%s 基座评测完成：Hit@k=%.3f MRR=%.3f SeedR=%.3f 噪声FP=%.3f（%.2fs）",
            name, m["hit_at_k"], m["mrr"], m["seed_recall"],
            m["false_positive_rate"], time.perf_counter() - t0,
        )
        for miss in result["misses"][:5]:
            log.info("  未命中 %s [%s]：%s", miss["case_id"], miss["category"],
                     " | ".join(line[:40] for line in miss["lines"]) or "（空）")

    print(format_table(results))

    report_dir = Path(args.report_dir) if args.report_dir else (
        ROOT / "results" / "memory_retrieval" / time.strftime("%Y%m%d_%H%M%S")
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "metrics.json").write_text(
        json.dumps({k: v["metrics"] for k, v in results.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (report_dir / "details.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for name, result in results.items():
            for case_eval in result["cases"]:
                fh.write(json.dumps(
                    {"base": name, **case_eval.__dict__}, ensure_ascii=False,
                ))
                fh.write("\n")
    log.info("明细已写出：%s", report_dir)


if __name__ == "__main__":
    main()
