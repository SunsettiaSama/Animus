from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_addoption(parser: pytest.Parser) -> None:
    # Guard: pytest_addoption can only be called once per option name;
    # skip registration if the option was already added by a parent conftest.
    existing = {o.dest for o in parser._anonymous.options}

    def _add(name: str, **kwargs):
        dest = name.lstrip("-").replace("-", "_")
        if dest not in existing:
            parser.addoption(name, **kwargs)

    _add("--run-e2e",  action="store_true", default=False,
         help="真实 LLM E2E 测试（需�?--base-url / --api-key / --model�?)
    _add("--model",    default="gpt-3.5-turbo", help="LLM 模型名称（E2E 模式�?)
    _add("--base-url", default=None,            help="API 基础 URL（E2E 模式�?)
    _add("--api-key",  default="EMPTY",         help="API Key（E2E 模式�?)
    _add("--throughput-json",
         default=str(Path(".react/benchmark/throughput.json")),
         help="吞吐�?JSON 报告输出路径")
    _add("--n-requests",   type=int,   default=30,  help="每场景请求数（默�?30�?)
    _add("--mock-delay-ms", type=float, default=5.0, help="Mock LLM 模拟延迟 ms（默�?5ms�?)
