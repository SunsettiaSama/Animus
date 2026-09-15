#!/usr/bin/env python3
"""软约束标注 A/B 管线入口：唯一变量 = 边缘记忆的呈现方式。

- A 臂 ``labeled``：软记忆带【隐约浮现】标注 + 解释（软约束）；
- B 臂 ``unlabeled``：同样两条记忆以普通记忆行裸露。

检索上下文两臂逐字相同；10 场景各埋 1 个"联想恰当时机" +
1 条无关干扰。核心指标全部确定性判定：联想提及率 / 犹豫口吻率 /
干扰误引用率；轨迹评委仅作主观参照。

示例（cwd = 仓库根）::

    python scripts/memory_abtest_bench.py --limit 2 --judge heuristic   # 冒烟
    python scripts/memory_abtest_bench.py --judge llm                   # 正式 A/B
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
    def format(self, record: logging.LogRecord) -> str:
        return f"[abtest +{time.perf_counter() - _T0:7.1f}s] {record.getMessage()}"


def _setup_logging(level: int) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ElapsedFormatter())
    root = logging.getLogger("evals.memory_humaneness")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


def _load_llm(args, *, tag: str = "LLM"):
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
    log.info("加载%s：backend=%s model=%s max_tokens=%s", tag, cfg.backend, model, args.max_tokens)
    llm = LLM(LLMConfig(
        backend=cfg.backend, model=model, base_url=base_url or None, api_key=api_key,
        max_tokens=args.max_tokens, temperature=args.temperature,
        do_sample=cfg.do_sample, top_p=cfg.top_p,
    ))
    llm.resolved_model_name = model
    return llm


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", default=str(SRC / "evals/memory_humaneness/dialogue/data/scenarios.jsonl"))
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 个场景（0=全部 10）")
    parser.add_argument("--judge", choices=["llm", "heuristic"], default="llm")
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--llm-config", default="config/llm_core/config.yaml")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    _setup_logging(logging.DEBUG if args.progress else logging.INFO)

    from evals.memory_humaneness.abtest.design import (
        build_ab_designs, save_designs, validate_ab_designs,
    )
    from evals.memory_humaneness.abtest.runner import ABRunner
    from evals.memory_humaneness.dialogue.judge_dialogue import (
        ExpertDialogueJudge, HeuristicDialogueJudge,
    )
    from evals.memory_humaneness.dialogue.scenarios import (
        build_scenarios, load_scenarios, validate_scenarios,
    )
    from evals.memory_humaneness.abtest.report_ab import aggregate_ab, write_ab_report

    # 设计与剧本必须对齐（锚点不撞台词/硬记忆）
    designs = build_ab_designs()
    scenarios = load_scenarios(args.scenarios)
    problems = validate_ab_designs(designs, {s.scenario_id: s for s in scenarios})
    if problems:
        raise SystemExit("AB 设计校验失败：\n" + "\n".join(problems))
    sc_map = {s.scenario_id: s for s in scenarios}
    if args.limit > 0:
        designs = designs[: args.limit]
    log.info("AB 设计就绪：%d 场景 × 2 臂（labeled / unlabeled）", len(designs))

    agent_llm = _load_llm(args, tag="Agent LLM")
    judge = (
        ExpertDialogueJudge(_load_llm(args, tag="Judge LLM", max_tokens=3072))
        if args.judge == "llm" else HeuristicDialogueJudge()
    )

    report_dir = args.report_dir or str(
        ROOT / "results" / "memory_abtest" / time.strftime("%Y%m%d_%H%M%S")
    )
    transcript_path = str(Path(report_dir) / "raw_llm.jsonl")
    log.info("LLM 原始输出 transcript（先保存再解析）：%s", transcript_path)

    runner = ABRunner(agent_llm, judge, transcript_path=transcript_path)
    records = []
    for di, design in enumerate(designs, 1):
        sc = sc_map[design.scenario_id]
        for arm in ("labeled", "unlabeled"):
            record = runner.run_scenario(design, sc, arm)
            if not record.error:
                runner.judge(judge, sc, record)
            records.append(record)
            ov = record.judge.get("scores", {}).get("overall", 0.0)
            log.info(
                "%s × %-9s → overall=%.1f  提及=%s 口吻=%s 误引=%s（%.1fs）",
                design.scenario_id, arm, ov,
                record.association.get("mention"), record.association.get("hedged"),
                record.misreference.get("mentions"), record.elapsed_sec,
            )
        if di % max(1, min(5, len(designs))) == 0:
            log.info("进度 %d/%d 场景｜Agent LLM 已用 %d 次", di, len(designs), runner.gen_calls)

    meta = {
        "scenarios": len(designs),
        "arms": "labeled,unlabeled",
        "judge": judge.name,
        "judge_fallbacks": getattr(judge, "fallback_count", 0),
        "agent_llm": getattr(agent_llm, "resolved_model_name", "?"),
        "gen_calls": runner.gen_calls,
    }
    report = write_ab_report(records, report_dir, meta)
    log.info("报告：%s", report)
    print(json.dumps(aggregate_ab(records), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
