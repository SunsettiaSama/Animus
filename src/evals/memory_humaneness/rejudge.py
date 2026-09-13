"""离线重评 / 重放：从已保存的 transcript 重建评分，解析 bug 修复后零 LLM 成本。

原则：LLM 原始输出是花钱买的数据。harness 运行时已把它们逐条落盘在
``raw_llm.jsonl``；本模块对历史 run 做：

1. transcript 里已有的评委原文 → 用**当前解析器**离线重放（0 次 LLM 调用）；
2. 缺失的（旧版 run 只存了解析结果）→ 只补调评委 LLM，原文仍逐条落盘，
   中断可续（已完成的不再重调）；
3. 重建 records + 汇总 + 报告，写入新目录，原 run 不动。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .judge import ExpertJudge, HeuristicJudge
from .report import write_report
from .runner import CaseRecord
from .schema import HumanenessCase, load_cases

log = logging.getLogger("evals.memory_humaneness")


def _load_transcript(path: Path) -> dict[tuple[str, str], str]:
    raws: dict[tuple[str, str], str] = {}
    if not path.is_file():
        return raws
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("kind") == "judge" and item.get("raw"):
                raws[(item.get("case_id", ""), item.get("base", ""))] = item["raw"]
    return raws


def _append_judge_raw(path: Path, case_id: str, base: str, raw: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(
            {"kind": "judge", "case_id": case_id, "base": base, "raw": raw},
            ensure_ascii=False,
        ))
        fh.write("\n")


def rejudge_run(
    judge: ExpertJudge,
    run_dir: str | Path,
    *,
    dataset: str | Path,
    out_dir: str | Path | None = None,
    meta: dict | None = None,
    progress: bool = False,
    refix_fallback: bool = False,
) -> Path:
    """对历史 run 离线重评，返回新报告路径。

    - ``run_dir``：原 run（读取 records.jsonl 与 raw_llm.jsonl，只读）；
    - transcript 已有的评委原文直接重放；缺失的补调评委 LLM（可中断续跑）；
    - ``refix_fallback``：历史 run 里被降级为 heuristic 的记录，其原文通常是
      截断不可解析的（如 max_tokens 耗尽）——视为缺失并补调评委覆盖；
    - 结果写入 ``<run_dir>-rejudged/``（或指定 ``out_dir``）。
    """
    run_dir = Path(run_dir)
    out = Path(out_dir) if out_dir else Path(f"{run_dir}-rejudged")
    out.mkdir(parents=True, exist_ok=True)
    transcript = out / "raw_llm.jsonl"

    cases = {c.case_id: c for c in load_cases(dataset)}
    records = [json.loads(line) for line in
               (run_dir / "records.jsonl").open("r", encoding="utf-8")]
    orig_raws = _load_transcript(run_dir / "raw_llm.jsonl")
    # 续跑：本输出目录已补调过的原文优先（区分"原run的陈旧降级"与"本次已补调"）
    fresh_raws = _load_transcript(out / "raw_llm.jsonl")

    need_llm = 0
    replayed = 0
    refixed = 0
    rebuilt: list[CaseRecord] = []
    replayable = isinstance(judge, ExpertJudge)
    for item in records:
        case: HumanenessCase = cases.get(item["case_id"], HumanenessCase(
            case_id=item["case_id"], category=item["category"],
            memories=[], current_user=""))
        record = CaseRecord(
            case_id=item["case_id"], category=item["category"], base=item["base"],
            reply=item["reply"], memory_lines=list(item.get("memory_lines") or []),
        )
        if item.get("error"):
            record.error = item["error"]
            rebuilt.append(record)
            continue

        if not replayable:
            # 规则评委：无 LLM、无原文可重放，直接重算
            record.judge = judge.judge(case, record.memory_lines, record.reply).to_dict()
            rebuilt.append(record)
            continue

        key = (record.case_id, record.base)
        fresh = fresh_raws.get(key)
        raw = fresh if fresh is not None else orig_raws.get(key)
        verdict = None
        if raw is not None:
            verdict = judge.parse_verdict(case, record.memory_lines, record.reply, raw)
            if verdict.judge == "llm_expert":
                replayed += 1
        # 补调条件：
        #  a) 无任何原文（旧版 run 未保存评委输出）→ rejudge 核心语义；
        #  b) refix 开启 + 原文解析仍失败 + 本次输出目录还没补调过（fresh 为空）
        #     → 覆盖重调；已补调过的不再无限重试
        need_recall = raw is None or (
            refix_fallback and verdict is not None and verdict.judge != "llm_expert" and fresh is None
        )
        if need_recall:
            need_llm += 1
            if raw is not None:
                refixed += 1  # 原文在但重放解析失败，才覆盖补调
            verdict = judge.judge(case, record.memory_lines, record.reply)
            _append_judge_raw(transcript, record.case_id, record.base, verdict.raw)
        record.judge = verdict.to_dict()
        rebuilt.append(record)
        if progress:
            log.info(
                "重评 %s × %s → overall=%.1f",
                record.case_id, record.base,
                record.judge.get("scores", {}).get("overall", 0.0),
            )

    resolved_meta = {
        "cases": len({r.case_id for r in rebuilt}),
        "rejudged_from": run_dir.name,
        "judge_replays": replayed,
        "judge_new_calls": need_llm,
        "judge_refixed": refixed,
        "judge_fallbacks": getattr(judge, "fallback_count", 0),
    }
    resolved_meta.update(meta or {})
    log.info(
        "重评完成：重放 %d 条（0 成本），补调评委 %d 次（含覆盖截断 %d）；输出 %s",
        replayed, need_llm, refixed, out,
    )
    return write_report(rebuilt, out, resolved_meta)
