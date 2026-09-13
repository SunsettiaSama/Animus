#!/usr/bin/env python3
"""记忆基座拟人化对比 benchmark 入口。

同一批 100 条用例 × 多个记忆基座（graph / stack / none），LLM 生成回复，
专家评判（LLM rubric 或确定性启发式）打分，产出对比报告。

日志：默认 INFO——阶段耗时、逐用例结果行、每 10 组滚动均值与 ETA；
``--verbose`` 追加检索命中行/回复全文/评审理由；``--quiet`` 只留 WARNING。

示例（cwd = 仓库根）::

    python scripts/memory_humaneness_bench.py --fake-llm --limit 6          # 离线冒烟
    python scripts/memory_humaneness_bench.py --judge heuristic --limit 10  # 真回复+启发式评判
    python scripts/memory_humaneness_bench.py --bases graph,stack,none --judge llm --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import os
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
    """``[bench +  12.3s] 消息``，与 scripts/ 下 smoke 的耗时前缀同风格。"""

    def format(self, record: logging.LogRecord) -> str:
        return f"[bench +{time.perf_counter() - _T0:7.1f}s] {record.getMessage()}"


def _setup_logging(level: int) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ElapsedFormatter())
    root = logging.getLogger("evals.memory_humaneness")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


def _load_llm(args: argparse.Namespace):
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
    log.info("加载回复 LLM：backend=%s model=%s base_url=%s", cfg.backend, model, base_url or "(default)")
    llm = LLM(LLMConfig(
        backend=cfg.backend,
        model=model,
        base_url=base_url or None,
        api_key=api_key,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        do_sample=cfg.do_sample,
        top_p=cfg.top_p,
    ))
    llm.resolved_model_name = model  # 供报告元数据记录
    return llm


def _base_factories(names: list[str]):
    from evals.memory_humaneness.bases import (
        CompactMemoryBase,
        FullMemoryBase,
        GraphMemoryBase,
        NullMemoryBase,
        StackMemoryBase,
    )

    factories = []
    for name in names:
        name = name.strip().lower()
        if name == "graph":
            factories.append(lambda: GraphMemoryBase.build())
        elif name == "stack":
            factories.append(lambda: StackMemoryBase.build())
        elif name == "compact":
            log.info("compact 基座就绪（全量进上下文+压缩，仅留近期原文）")
            factories.append(lambda: CompactMemoryBase())
        elif name == "full":
            log.info("full 基座就绪（全量裸注入，不检索）")
            factories.append(lambda: FullMemoryBase())
        elif name == "none":
            log.info("none 基座就绪（裸 LLM 对照组）")
            factories.append(lambda: NullMemoryBase())
        else:
            raise SystemExit(
                f"unknown base kind: {name!r} (expect graph/stack/compact/full/none)"
            )
    return factories


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bases", default="graph,stack,compact,full,none",
                        help="逗号分隔：graph / stack / compact / full / none")
    parser.add_argument("--dataset", default=str(SRC / "evals/memory_humaneness/data/cases.jsonl"))
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0 = 全部）")
    parser.add_argument("--judge", choices=["llm", "heuristic"], default="llm")
    parser.add_argument("--recall-top-k", type=int, default=5)
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--max-tokens", type=int, default=1024,
                        help="推理模型 think 占用大，256 会在正文前耗尽预算（默认 1024）")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--llm-config", default="config/llm_core/config.yaml")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--fake-llm", action="store_true",
                        help="用离线确定性回复器跑通全链路（不消耗 API，验证管线用）")
    parser.add_argument("--verbose", action="store_true", help="DEBUG：检索命中行/回复全文/评审理由")
    parser.add_argument("--quiet", action="store_true", help="只输出 WARNING 及以上")
    args = parser.parse_args()

    if args.quiet:
        _setup_logging(logging.WARNING)
    elif args.verbose:
        _setup_logging(logging.DEBUG)
    else:
        _setup_logging(logging.INFO)

    from evals.memory_humaneness import load_cases, validate_dataset
    from evals.memory_humaneness.judge import ExpertJudge, HeuristicJudge
    from evals.memory_humaneness.report import aggregate, write_report
    from evals.memory_humaneness.runner import HumanenessHarness

    log.info("数据集加载：%s", args.dataset)
    cases = load_cases(args.dataset)
    problems = validate_dataset(cases)
    if problems:
        raise SystemExit("dataset invalid:\n" + "\n".join(problems))
    if args.limit > 0:
        cases = cases[: args.limit]
    log.info(
        "数据集校验通过：%d 条用例（截取 %d），基座=%s，judge=%s",
        len(cases), len(cases), args.bases, args.judge,
    )

    if args.fake_llm:
        from evals.memory_humaneness.fakes import FakeReplyLLM

        reply_llm = FakeReplyLLM()
        log.info("--fake-llm：使用离线确定性回复器（管线冒烟，结果无评测意义）")
        if args.judge == "llm":
            log.warning(
                "--fake-llm 下 ExpertJudge 无意义（会把离线回复器当评委），"
                "已强制改为启发式评判；真实评分请去掉 --fake-llm"
            )
            args.judge = "heuristic"
    else:
        reply_llm = _load_llm(args)
    judge = ExpertJudge(reply_llm) if args.judge == "llm" else HeuristicJudge()
    log.info("评判器：%s", judge.name)

    harness = HumanenessHarness(reply_llm, judge, recall_top_k=args.recall_top_k)
    factories = _base_factories(args.bases.split(","))

    # LLM 原始输出先落盘再解析：解析 bug 修复后可离线重放，无需重烧 API
    report_dir = args.report_dir or str(
        ROOT / "results" / "memory_humaneness" / time.strftime("%Y%m%d_%H%M%S")
    )
    transcript_path = str(Path(report_dir) / "raw_llm.jsonl")
    log.info("LLM 原始输出 transcript：%s", transcript_path)
    records = harness.run(cases, factories, progress_every=max(1, min(10, len(cases))))

    meta = {
        "cases": len(cases),
        "bases": args.bases,
        "judge": judge.name,
        "judge_fallbacks": getattr(judge, "fallback_count", 0),
        "recall_top_k": args.recall_top_k,
        "reply_llm": "fake (offline)" if args.fake_llm else getattr(
            reply_llm, "resolved_model_name", "config-default"
        ),
    }
    report_path = write_report(records, report_dir, meta)
    log.info("报告已写出：%s", report_path)

    summary = aggregate(records)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
