from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from agent.soul.speak.responders.request_driven.layers import CARD_FAMILY_FILTER_ENV

from .persona_target import DEFAULT_PERSONA_DIR, PersonaGroundTruth
from .report import DEFAULT_OUTPUT_DIR, load_jsonl, write_report
from .runner import run_eval
from .runner_types import CaseRecord
from .runtime import (
    ARM_ALIASES,
    RESPONDER_DIRECT,
    RESPONDER_REQUEST_DRIVEN,
    LiveSpeakHumanenessRuntime,
    SUPPORTED_RUN_LABELS,
)
from .simulation_compat import load_cases

_T0 = time.perf_counter()
log = logging.getLogger("evals.speak_humaneness")


class _ElapsedFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return f"[bench +{time.perf_counter() - _T0:7.1f}s] {record.getMessage()}"


def _setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ElapsedFormatter())
    log.handlers[:] = [handler]
    log.setLevel(logging.INFO)
    log.propagate = False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.speak_humaneness",
        description="speak 拟人度三维评测：画像匹配 × 图灵盲测 × 行为统计",
    )
    parser.add_argument("--cases", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--llm-config", default="config/llm_core/config.yaml")
    parser.add_argument("--judge-llm-config", default="")
    parser.add_argument(
        "--responders",
        default=f"{RESPONDER_REQUEST_DRIVEN},{RESPONDER_DIRECT}",
        help="逗号分隔，可选 " + "/".join(SUPPORTED_RUN_LABELS),
    )
    parser.add_argument(
        "--card-family",
        dest="card_family",
        default="",
        choices=[
            "",
            "director",
            "writer",
            "dynsched",
            "dynsched_llm",
            "softplot",
            "charsilence",
        ],
        help="消融/设计臂过滤：director=只留导演卡，writer=只留剧情卡，"
        "dynsched=阈值版调度(对照)，dynsched_llm=导演LLM语境判定，"
        "softplot=剧情软约束+用户位置，charsilence=角色沉默权+自预约",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--case-ids", default="", help="逗号分隔的 case_id 子集")
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--session-prefix", default="speak-humaneness")
    parser.add_argument("--persona-dir", default=str(DEFAULT_PERSONA_DIR))
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--inactivity-timeout-sec",
        type=float,
        default=900.0,
        help="超过该秒数没有任何 case 完成则硬退出（可用 --resume 续跑）",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    _setup_logging()
    args = _build_parser().parse_args(argv)

    from test.workbench.speak_turing.dataset import DEFAULT_CASES_PATH
    from test.workbench.speak_turing.deadline import (
        InactivityDeadline,
        hard_exit_on_timeout,
    )

    cases_path = Path(args.cases) if args.cases else DEFAULT_CASES_PATH
    cases = load_cases(cases_path)
    responders = tuple(
        item.strip()
        for item in str(args.responders).split(",")
        if item.strip()
    )
    unknown = [item for item in responders if item not in SUPPORTED_RUN_LABELS]
    if unknown:
        raise SystemExit(f"unsupported responders: {unknown}")
    if args.card_family:
        non_matching = [
            item
            for item in responders
            if ARM_ALIASES.get(item, (item, ""))[1] != args.card_family
        ]
        if non_matching:
            raise SystemExit(
                f"--card-family {args.card_family} 只能配合同族消融臂使用，"
                f"不匹配: {non_matching}（过滤是进程级的，会污染普通臂）"
            )
        os.environ[CARD_FAMILY_FILTER_ENV] = args.card_family
        log.info("card family filter: %s", args.card_family)
    case_ids = tuple(
        item.strip() for item in str(args.case_ids).split(",") if item.strip()
    )
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else DEFAULT_OUTPUT_DIR.parent / f"live-{stamp}"
    )

    deadline = InactivityDeadline(
        args.inactivity_timeout_sec,
        on_timeout=lambda: hard_exit_on_timeout(output_dir, args.inactivity_timeout_sec),
    )
    deadline.start()

    ground_truth = PersonaGroundTruth.load(Path(args.persona_dir))
    log.info(
        "ground truth: %s (revision=%s), responders=%s, cases=%d",
        ground_truth.name,
        ground_truth.source_revision,
        ",".join(responders),
        len(cases),
    )

    live = LiveSpeakHumanenessRuntime(
        llm_config_path=args.llm_config,
        responders=responders,
        judge_llm_config_path=args.judge_llm_config or None,
        judge_repeats=3,
        seed=args.seed,
        persona_dir=Path(args.persona_dir),
    )
    atexit.register(live.close)
    summary = run_eval(
        cases,
        live.eval_runtime,
        ground_truth,
        responders=responders,
        output_dir=output_dir,
        limit=args.limit,
        case_ids=case_ids,
        resume=args.resume,
        session_prefix=args.session_prefix,
        on_progress=deadline.reset,
    )
    report_path = write_report(
        summary,
        [
            CaseRecord.from_dict(row)
            for row in load_jsonl(output_dir / "records.jsonl")
        ],
        output_dir,
    )
    deadline.stop()
    live.close()
    atexit.unregister(live.close)
    log.info("report written: %s", report_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
