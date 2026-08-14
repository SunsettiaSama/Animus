from __future__ import annotations

import argparse
import atexit
import json
from pathlib import Path

from .dataset import DEFAULT_CASES_PATH, load_cases
from .deadline import InactivityDeadline, hard_exit_on_timeout
from .live import LiveSpeakTuringRuntime
from .report import DEFAULT_OUTPUT_DIR
from .runner import run_workbench


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m test.workbench.speak_turing",
        description="Dynamic HUMAN/AI comparison workbench for Soul Speak",
    )
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--llm-config",
        default="config/llm_core/config.yaml",
        dest="llm_config",
    )
    parser.add_argument(
        "--judge-llm-config",
        default="",
        dest="judge_llm_config",
        help="Optional independent LLM config for the categorical judge",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--seed", type=int, default=20260802)
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--session-prefix", default="speak-turing")
    parser.add_argument(
        "--inactivity-timeout-sec",
        type=float,
        default=600.0,
        dest="inactivity_timeout_sec",
        help="Hard-exit if no case completes within this many seconds",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    cases = load_cases(Path(args.cases))
    output_dir = Path(args.output_dir)
    deadline = InactivityDeadline(
        args.inactivity_timeout_sec,
        on_timeout=lambda: hard_exit_on_timeout(
            output_dir,
            args.inactivity_timeout_sec,
        ),
    )
    deadline.start()
    runtime = LiveSpeakTuringRuntime(
        llm_config_path=args.llm_config,
        judge_llm_config_path=args.judge_llm_config or None,
        judge_repeats=3,
        seed=args.seed,
    )
    atexit.register(runtime.close)
    summary = run_workbench(
        cases,
        runtime.simulator,
        runtime.judge,
        output_dir=output_dir,
        limit=args.limit,
        resume=args.resume,
        session_prefix=args.session_prefix,
        on_progress=deadline.reset,
    )
    deadline.stop()
    runtime.close()
    atexit.unregister(runtime.close)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
