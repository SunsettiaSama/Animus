#!/usr/bin/env python3
"""离线重评历史 run：解析修复后重放评委原文（0 成本）或补调评委（仅缺的部分）。

场景：跑分完成后发现解析/评判逻辑有 bug——不必重烧回复 LLM。
- run 目录里已有评委原文（raw_llm.jsonl，新版 run 自动保存）→ 全部离线重放；
- 旧版 run 没存评委原文 → 只补调评委 LLM（回复复用已保存的，成本约一半），
  且逐条追加落盘，中断可续。

示例（cwd = 仓库根）::

    python scripts/memory_humaneness_rejudge.py --run-dir results/memory_humaneness/20260904_164514
"""

from __future__ import annotations

import argparse
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
    def format(self, record: logging.LogRecord) -> str:
        return f"[rejudge +{time.perf_counter() - _T0:7.1f}s] {record.getMessage()}"


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
    log.info("加载评委 LLM：backend=%s model=%s", cfg.backend, model)
    return LLM(LLMConfig(
        backend=cfg.backend,
        model=model,
        base_url=base_url or None,
        api_key=api_key,
        max_tokens=args.max_tokens,
        temperature=0.2,
        do_sample=cfg.do_sample,
        top_p=cfg.top_p,
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="历史 run 目录（含 records.jsonl）")
    parser.add_argument("--dataset", default=str(SRC / "evals/memory_humaneness/data/cases.jsonl"))
    parser.add_argument("--out-dir", default="", help="默认 <run-dir>-rejudged")
    parser.add_argument("--judge", choices=["llm", "heuristic"], default="llm",
                        help="llm=重放/补调 LLM 评委；heuristic=全部用规则评委（0 成本）")
    parser.add_argument("--refix-judge", action="store_true",
                        help="原 run 中被降级为 heuristic 的记录视为缺失并补调评委"
                             "（救援 max_tokens 截断导致的批量降级）")
    parser.add_argument("--max-tokens", type=int, default=2048,
                        help="评委 think 较长，1024 仍可能截断（默认 2048）")
    parser.add_argument("--llm-config", default="config/llm_core/config.yaml")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    _setup_logging(logging.DEBUG if args.progress else logging.INFO)

    from evals.memory_humaneness.judge import ExpertJudge, HeuristicJudge
    from evals.memory_humaneness.rejudge import rejudge_run

    if args.judge == "llm":
        judge = ExpertJudge(_load_llm(args))
    else:
        judge = HeuristicJudge()
        log.info("--judge heuristic：纯离线规则重评，0 次 LLM 调用")

    meta = {"judge": judge.name}
    report = rejudge_run(
        judge,
        args.run_dir,
        dataset=args.dataset,
        out_dir=args.out_dir or None,
        meta=meta,
        progress=args.progress,
        refix_fallback=args.refix_judge,
    )
    log.info("重评报告：%s", report)


if __name__ == "__main__":
    main()
