#!/usr/bin/env python3
"""L4 多跳记忆基准入口：预载 10 条 × 多跳问句 × 五基座。

两种模式：
- 默认（--retrieval-only 可省略 LLM）：确定性检索评测——逐跳命中 / 联合命中 /
  跳 MRR / 干扰占位。零 API 成本，改完检索代码秒级回归。
- 全链模式：五基座生成回复 + 专家评判（与 L3 同 harness、同 transcript
  "先保存再解析"保障）。

示例（cwd = 仓库根）::

    python scripts/memory_multihop_bench.py                       # L4 检索评测
    python scripts/memory_multihop_bench.py --retrieval-only      # 同上（显式）
    python scripts/memory_multihop_bench.py --limit 20            # 截取
    python scripts/memory_multihop_bench.py --full --judge heuristic --limit 10
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
        return f"[multihop-bench +{time.perf_counter() - _T0:7.1f}s] {record.getMessage()}"


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


def run_retrieval(args, cases) -> None:
    from evals.memory_humaneness.multihop import evaluate_multihop_base

    log.info(
        "L4 检索评测：%d 条 × %d 跳/条，top_k=%d，基座=%s（确定性，无 LLM）",
        len(cases), 2, args.top_k, args.bases,
    )
    results: dict[str, dict] = {}
    for name, factory in _base_factories(args.bases.split(",")):
        t0 = time.perf_counter()
        result = evaluate_multihop_base(factory, cases, top_k=args.top_k)
        results[name] = result
        m = result["metrics"]
        log.info(
            "%-8s 逐跳命中=%.3f 联合命中=%.3f 跳MRR=%.3f 干扰占位=%.2f/%d（%.2fs）",
            name, m["hop_hit_rate"], m["joint_hit_rate"], m["hop_mrr"],
            m["distractor_slots_avg"], args.top_k, time.perf_counter() - t0,
        )
        for p, pm in m["by_pattern"].items():
            log.info("    %-12s 联合命中=%.3f", p, pm["joint_hit_rate"])
        misses = [
            e for e in result["cases"] if not e["joint_hit"]
        ][:3]
        for e in misses:
            log.info(
                "    未全中 %s [%s] hop_ranks=%s：%s",
                e["case_id"], e["pattern"], e["hop_ranks"],
                " | ".join(line[:36] for line in e["lines"]) or "（空）",
            )

    out_dir = Path(args.report_dir) if args.report_dir else (
        ROOT / "results" / "memory_multihop" / time.strftime("%Y%m%d_%H%M%S")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(
        json.dumps({k: v["metrics"] for k, v in results.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (out_dir / "details.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for name, result in results.items():
            for e in result["cases"]:
                fh.write(json.dumps({"base": name, **e}, ensure_ascii=False))
                fh.write("\n")
    log.info("明细已写出：%s", out_dir)


def _load_llm(args: argparse.Namespace):
    """与 memory_humaneness_bench 相同的加载约定：CLI 参数 > 环境变量 > 配置文件。"""
    import os

    from config.llm_core.config import LLMConfig
    from infra.llm import LLM

    model = args.model or os.environ.get("REACT_TEST_LLM_MODEL", "").strip()
    base_url = args.base_url or os.environ.get("REACT_TEST_LLM_BASE_URL", "").strip()
    api_key = args.api_key or os.environ.get("REACT_TEST_LLM_API_KEY", "").strip()
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "").strip()

    cfg_path = (ROOT / args.llm_config) if not os.path.isabs(args.llm_config) else Path(args.llm_config)
    cfg = LLMConfig.from_yaml(str(cfg_path)) if cfg_path.is_file() else LLMConfig()
    model = model or cfg.model.strip()
    base_url = base_url or (cfg.base_url or "").strip()
    api_key = api_key or cfg.api_key.strip()
    if not model:
        raise RuntimeError("missing LLM model: provide --model or config/llm_core/config.yaml")
    if cfg.backend != "transformers" and not api_key:
        raise RuntimeError("missing LLM api key: provide --api-key or config/llm_core/config.yaml")
    log.info("加载 LLM：backend=%s model=%s", cfg.backend, model)
    llm = LLM(LLMConfig(
        backend=cfg.backend, model=model, base_url=base_url or None, api_key=api_key,
        max_tokens=args.max_tokens, temperature=args.temperature,
        do_sample=cfg.do_sample, top_p=cfg.top_p,
    ))
    llm.resolved_model_name = model
    return llm


def run_full(args, cases) -> None:
    from evals.memory_humaneness.judge import ExpertJudge, HeuristicJudge
    from evals.memory_humaneness.multihop import to_humaneness_cases
    from evals.memory_humaneness.report import aggregate, write_report
    from evals.memory_humaneness.runner import HumanenessHarness

    h_cases = to_humaneness_cases(cases)
    if args.judge == "llm":
        reply_llm = _load_llm(args)
        judge = ExpertJudge(reply_llm)
    else:
        class _NoLLM:
            def generate_messages(self, messages):
                return "（离线模式：未配置回复 LLM）"

        reply_llm = _NoLLM()
        judge = HeuristicJudge()
        log.warning("--judge heuristic 且未接回复 LLM：回复为占位文本，仅验证管线")

    report_dir = args.report_dir or str(
        ROOT / "results" / "memory_multihop" / time.strftime("%Y%m%d_%H%M%S")
    )
    transcript = str(Path(report_dir) / "raw_llm.jsonl")
    log.info("LLM 原始输出 transcript（先保存再解析）：%s", transcript)
    harness = HumanenessHarness(reply_llm, judge, recall_top_k=args.top_k,
                                transcript_path=transcript)
    factories = [f for _, f in _base_factories(args.bases.split(","))]
    records = harness.run(h_cases, factories, progress_every=max(1, min(10, len(h_cases))))
    meta = {
        "cases": len(h_cases),
        "bases": args.bases,
        "judge": judge.name,
        "judge_fallbacks": getattr(judge, "fallback_count", 0),
        "recall_top_k": args.top_k,
        "dataset": "multihop_cases.jsonl",
        "reply_llm": getattr(reply_llm, "resolved_model_name", "offline-placeholder"),
    }
    write_report(records, report_dir, meta)
    log.info("报告：%s", Path(report_dir) / "report.md")
    print(json.dumps(aggregate(records), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(SRC / "evals/memory_humaneness/data/multihop_cases.jsonl"))
    parser.add_argument("--build", action="store_true", help="重新生成数据集（确定性种子）")
    parser.add_argument("--bases", default="graph,stack,compact,full,none")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--full", action="store_true", help="全链模式（LLM 回复+评判）")
    parser.add_argument("--retrieval-only", action="store_true", help="仅确定性检索评测（默认）")
    parser.add_argument("--judge", choices=["llm", "heuristic"], default="heuristic")
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--max-tokens", type=int, default=1024,
                        help="推理模型 think 占用大，256 会在正文前耗尽预算（默认 1024）")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--llm-config", default="config/llm_core/config.yaml")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    _setup_logging(logging.DEBUG if args.progress else logging.INFO)

    from evals.memory_humaneness.multihop import (
        build_multihop_cases,
        load_multihop,
        validate_multihop,
    )

    if args.build:
        cases = build_multihop_cases()
        problems = validate_multihop(cases)
        if problems:
            raise SystemExit("生成数据集校验失败：\n" + "\n".join(problems[:20]))
        out = Path(args.dataset)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="\n") as fh:
            for c in cases:
                fh.write(json.dumps(c.to_dict(), ensure_ascii=False))
                fh.write("\n")
        log.info("数据集已生成：%d 条 -> %s", len(cases), out)
    else:
        cases = load_multihop(args.dataset)

    problems = validate_multihop(cases)
    if problems:
        raise SystemExit("数据集校验失败：\n" + "\n".join(problems[:20]))
    if args.limit > 0:
        cases = cases[: args.limit]
    log.info("数据集就绪：%d 条（%s）", len(cases), args.dataset)

    if args.full:
        run_full(args, cases)
    else:
        run_retrieval(args, cases)


if __name__ == "__main__":
    main()
