#!/usr/bin/env python3
"""拟人度管线入口：多轮对话模拟 × 记忆基座 → 轨迹级拟人度评测。

设计要点：
- 单一固定人格档案（dialogue/persona.py），变量只在记忆基座；
- 用户侧 --user scripted（剧本预设）或 llm（另一个 LLM 扮演用户）；
- 逐轮：检索 → 人格+记忆 → 回复 → 本轮对话写回基座（encode 闭环）；
- 评委只看轨迹的拟人维度（情感承接/拟人度/记忆运用自然度/主动性），
  记忆对错不在评分范围——那是检索管线的职责；
- transcript 先保存再解析；开跑前打印 LLM 调用预算。

示例（cwd = 仓库根）::

    python scripts/memory_dialogue_bench.py --limit 1 --user scripted       # 冒烟 1 场景
    python scripts/memory_dialogue_bench.py --bases graph,stack,none --judge llm
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
        return f"[dialogue-bench +{time.perf_counter() - _T0:7.1f}s] {record.getMessage()}"


def _setup_logging(level: int) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ElapsedFormatter())
    root = logging.getLogger("evals.memory_humaneness")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


def _load_llm(args, *, temperature: float | None = None, tag: str = "LLM",
              max_tokens: int | None = None):
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
    log.info("加载%s：backend=%s model=%s max_tokens=%s", tag, cfg.backend, model,
             args.max_tokens if max_tokens is None else max_tokens)
    llm = LLM(LLMConfig(
        backend=cfg.backend, model=model, base_url=base_url or None, api_key=api_key,
        max_tokens=args.max_tokens if max_tokens is None else max_tokens,
        temperature=args.temperature if temperature is None else temperature,
        do_sample=cfg.do_sample, top_p=cfg.top_p,
    ))
    llm.resolved_model_name = model
    return llm


def _base_factories(names: list[str]):
    from evals.memory_humaneness.bases import (
        CompactMemoryBase, FullMemoryBase, GraphMemoryBase, NullMemoryBase, StackMemoryBase,
    )
    from evals.memory_humaneness.ablation import ablation_factory

    table = {
        "graph": lambda: GraphMemoryBase.build(),
        "stack": lambda: StackMemoryBase.build(),
        "compact": lambda: CompactMemoryBase(),
        "full": lambda: FullMemoryBase(),
        "none": lambda: NullMemoryBase(),
        "kg_semantic": ablation_factory("kg_semantic", use_bge=True),
        "kg_bm25": ablation_factory("kg_bm25"),
        "kg_spread": ablation_factory("kg_spread"),
        "kg_interfere": ablation_factory("kg_interfere", use_bge=True),
        "kg_drift": ablation_factory("kg_drift", use_bge=True),
    }
    out = []
    for name in names:
        name = name.strip().lower()
        if name not in table:
            raise SystemExit(
                f"unknown base kind: {name!r} "
                "(expect graph/stack/compact/full/none/kg_semantic/kg_bm25/kg_spread/kg_interfere)"
            )
        out.append((name, table[name]))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(SRC / "evals/memory_humaneness/dialogue/data/scenarios.jsonl"))
    parser.add_argument("--bases", default="graph,stack,compact,full,none")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--user", choices=["scripted", "llm"], default="scripted")
    parser.add_argument("--judge", choices=["llm", "heuristic"], default="llm")
    parser.add_argument("--turn-limit", type=int, default=0, help="截断每场景轮数（0=全部）")
    parser.add_argument("--recall-top-k", type=int, default=5)
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--judge-max-tokens", type=int, default=3072,
                        help="轨迹评委要分析整段对话，think 很长，1024 会截断（默认 3072）")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--llm-config", default="config/llm_core/config.yaml")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    _setup_logging(logging.DEBUG if args.progress else logging.INFO)

    from evals.memory_humaneness.dialogue.judge_dialogue import (
        ExpertDialogueJudge, HeuristicDialogueJudge,
    )
    from evals.memory_humaneness.dialogue.scenarios import (
        load_scenarios, validate_scenarios,
    )
    from evals.memory_humaneness.dialogue.simulator import (
        DialogueSimulator, LLMUser, ScriptedUser,
    )

    scenarios = load_scenarios(args.dataset)
    problems = validate_scenarios(scenarios)
    if problems:
        raise SystemExit("剧本校验失败：\n" + "\n".join(problems))
    if args.limit > 0:
        scenarios = scenarios[: args.limit]
    if args.turn_limit > 0:
        from dataclasses import replace as _dc_replace
        scenarios = [_dc_replace(s, turns=s.turns[: args.turn_limit]) for s in scenarios]

    base_names = [n for n in args.bases.split(",") if n.strip()]
    factories = _base_factories(base_names)
    n_turns = sum(len(s.turns) for s in scenarios)
    avg_turns = n_turns // max(1, len(scenarios))
    total_calls = len(scenarios) * len(factories) * (
        avg_turns
        + (avg_turns if args.user == "llm" else 0)
        + (1 if args.judge == "llm" else 0)
    )
    log.info(
        "拟人度管线：%d 场景 × %d 基座，用户侧=%s，评委=%s｜预算 ≈ %d 次 LLM 调用"
        "（回复 %d%s + 评判 %d）",
        len(scenarios), len(factories), args.user, args.judge, total_calls,
        n_turns if args.user == "scripted" else n_turns * 2,
        "（含用户 LLM）" if args.user == "llm" else "",
        len(scenarios) * len(factories) if args.judge == "llm" else 0,
    )

    agent_llm = _load_llm(args, tag="Agent LLM")
    user_llm_factory = (
        (lambda sc, n: LLMUser(_load_llm(args, tag="User LLM"), sc, max_turns=n))
        if args.user == "llm" else None
    )

    def _judge_raw_sink(scenario_id: str, base_kind: str):
        def _sink(raw: str) -> None:
            simulator._transcript.save("judge", scenario_id, base_kind, raw)
        return _sink

    judge = (
        ExpertDialogueJudge(
            _load_llm(args, tag="Judge LLM", max_tokens=args.judge_max_tokens),
            raw_sink=None,  # 逐场景绑定（见下）
        )
        if args.judge == "llm" else HeuristicDialogueJudge()
    )

    report_dir = args.report_dir or str(
        ROOT / "results" / "memory_dialogue" / time.strftime("%Y%m%d_%H%M%S")
    )
    transcript_path = str(Path(report_dir) / "raw_llm.jsonl")
    log.info("LLM 原始输出 transcript（先保存再解析）：%s", transcript_path)

    simulator = DialogueSimulator(
        agent_llm, recall_top_k=args.recall_top_k, transcript_path=transcript_path,
    )
    records = []
    for si, sc in enumerate(scenarios, 1):
        for name, factory in factories:
            base = factory()
            user = (
                user_llm_factory(sc, len(sc.turns)) if user_llm_factory
                else ScriptedUser(sc)
            )
            record = simulator.run_scenario(sc, base, user)
            if record.error:
                record.judge = {}
            else:
                # 评委：raw_sink 保证原文先落盘再解析
                if judge.name == "llm_expert":
                    judge._raw_sink = _judge_raw_sink(sc.scenario_id, record.base)
                verdict = judge.judge(sc, record)
                record.judge = {
                    "scores": verdict.scores, "evidence": verdict.evidence,
                    "rationale": verdict.rationale, "judge": verdict.judge,
                }
            dispose = getattr(base, "dispose", None)
            if callable(dispose):
                dispose()
            records.append(record)
            ov = record.judge.get("scores", {}).get("overall", 0.0)
            log.info(
                "场景 %s [%s] × %s → overall=%.1f，%d 轮（%.1fs）",
                sc.scenario_id, sc.theme, name, ov, len(record.turns), record.elapsed_sec,
            )
            if args.progress and not record.error and record.turns:
                last = record.turns[-1]
                log.debug("  末轮：%s → %s", last.user[:30], last.agent[:60])
            if si % max(1, min(5, len(scenarios))) == 0:
                ok = [r for r in records if not r.error]
                log.info(
                    "进度 %d/%d 场景（错误 %d）｜LLM 已用 %d 次",
                    si, len(scenarios), len(records) - len(ok), simulator.gen_calls,
                )

    # 报告
    from evals.memory_humaneness.dialogue.report_dialogue import write_dialogue_report

    meta = {
        "scenarios": len(scenarios),
        "bases": args.bases,
        "user_mode": args.user,
        "judge": judge.name,
        "judge_fallbacks": getattr(judge, "fallback_count", 0),
        "agent_llm": getattr(agent_llm, "resolved_model_name", "?"),
        "gen_calls": simulator.gen_calls,
    }
    report_path = write_dialogue_report(records, report_dir, meta)
    log.info("报告：%s", report_path)


if __name__ == "__main__":
    main()
