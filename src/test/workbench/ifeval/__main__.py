"""CLI for the opt-in IFEval Worker workbench."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from test.workbench.ifeval.dataset import (
    DEFAULT_CASES_PATH,
    DEFAULT_MANIFEST_PATH,
    SAMPLE_SIZE,
    download_and_sample,
    load_cases,
)
from test.workbench.ifeval.report import (
    DEFAULT_OUTPUT_DIR,
    load_response_records,
    score_and_write,
)
from test.workbench.ifeval.resources import download_nltk_resources
from test.workbench.ifeval.runner import (
    FlowCaseExecutor,
    WorkerCaseExecutor,
    run_workbench,
)
from test.workbench.ifeval.sync_official import sync_official_sources


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _cmd_download(args: argparse.Namespace) -> int:
    manifest = download_and_sample(
        cases_path=Path(args.cases),
        manifest_path=Path(args.manifest),
        sample_size=args.sample_size,
    )
    synced = sync_official_sources()
    nltk_dir = download_nltk_resources()
    manifest["official_verifier_files"] = [str(path) for path in synced]
    manifest["nltk_data_dir"] = str(nltk_dir)
    _print_json(manifest)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    cases = load_cases(Path(args.cases))
    if args.mode == "react":
        executor = WorkerCaseExecutor(
            llm_cfg_path=args.llm_config,
            max_steps=args.max_steps,
        )
    else:
        executor = FlowCaseExecutor(
            llm_cfg_path=args.llm_config,
            plan_dir=Path(args.output_dir) / "plans",
            max_steps=args.max_steps,
        )
    summary = run_workbench(
        cases,
        executor,
        output_dir=Path(args.output_dir),
        limit=args.limit,
        resume=args.resume,
        workers=args.workers,
    )
    _print_json(summary)
    return 0


def _cmd_score(args: argparse.Namespace) -> int:
    cases = load_cases(Path(args.cases))
    if args.limit is not None:
        cases = cases[: args.limit]
    records = load_response_records(Path(args.responses))
    summary = score_and_write(
        cases,
        records,
        output_dir=Path(args.output_dir),
    )
    _print_json(summary)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m test.workbench.ifeval",
        description="IFEval Worker text-task workbench",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    download = sub.add_parser(
        "download",
        help="Download pinned IFEval and build deterministic local sample",
    )
    download.add_argument("--cases", default=str(DEFAULT_CASES_PATH))
    download.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    download.add_argument("--sample-size", type=int, default=SAMPLE_SIZE)
    download.set_defaults(handler=_cmd_download)

    run = sub.add_parser(
        "run",
        help="Run local cases through SubAgentRunner and score responses",
    )
    run.add_argument("--cases", default=str(DEFAULT_CASES_PATH))
    run.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        dest="output_dir",
    )
    run.add_argument(
        "--llm-config",
        default="config/llm_core/config.yaml",
        dest="llm_config",
    )
    run.add_argument(
        "--mode",
        choices=("react", "flow"),
        default="react",
        help="Worker execution path (default: react)",
    )
    run.add_argument("--limit", type=int)
    run.add_argument("--max-steps", type=int, default=6, dest="max_steps")
    run.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of cases to execute concurrently (default: 1)",
    )
    run.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    run.set_defaults(handler=_cmd_run)

    score = sub.add_parser(
        "score",
        help="Offline-rescore an existing responses JSONL",
    )
    score.add_argument("--cases", default=str(DEFAULT_CASES_PATH))
    score.add_argument(
        "--responses",
        default=str(DEFAULT_OUTPUT_DIR / "responses.jsonl"),
    )
    score.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        dest="output_dir",
    )
    score.add_argument("--limit", type=int)
    score.set_defaults(handler=_cmd_score)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    sys.exit(args.handler(args))


if __name__ == "__main__":
    main()
