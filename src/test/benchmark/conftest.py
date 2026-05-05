from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.storage import StorageConfig as _StorageConfig

_DEFAULT_REPORT = str(Path(_StorageConfig().benchmark_dir) / "report.json")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run E2E benchmark tests against a real LLM (requires API key)",
    )
    parser.addoption(
        "--model",
        default="gpt-3.5-turbo",
        help="Real LLM model name for E2E benchmark tests",
    )
    parser.addoption(
        "--encoding",
        default="cl100k_base",
        help="tiktoken encoding for token counting in benchmark tests",
    )
    parser.addoption(
        "--benchmark-json",
        default=_DEFAULT_REPORT,
        help="Output path for the benchmark JSON report",
    )


@pytest.fixture(scope="session")
def benchmark_encoding(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("--encoding")


@pytest.fixture(scope="session")
def benchmark_model(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("--model")


@pytest.fixture(scope="session")
def run_e2e(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--run-e2e"))


@pytest.fixture(scope="session")
def benchmark_results() -> list:
    return []


@pytest.fixture(scope="session", autouse=True)
def _write_benchmark_report(
    request: pytest.FixtureRequest,
    benchmark_results: list,
) -> None:
    yield

    if not benchmark_results:
        return

    from test.benchmark.reporter import save_report, to_markdown

    output = Path(request.config.getoption("--benchmark-json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    save_report(benchmark_results, output)

    history_path = output.parent / "history.json"
    from test.benchmark.drift import append_history
    from dataclasses import asdict
    append_history(history_path, [asdict(r) for r in benchmark_results])

    md = to_markdown(benchmark_results)
    github_summary = Path(str(output).replace(".json", "-summary.md"))
    github_summary.write_text(md, encoding="utf-8")

    step_summary = Path(
        __import__("os").environ.get("GITHUB_STEP_SUMMARY", "/dev/null")
    )
    if step_summary.name != "null":
        with step_summary.open("a", encoding="utf-8") as f:
            f.write(md + "\n")
