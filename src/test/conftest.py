"""
公共 pytest 配置与 stub 工具
=============================
所有子目录测试均可通过 pytest 自动注入机制使用此文件中定义的 fixture。
stub 工具函数在需要时直接 import 使用。
"""
from __future__ import annotations

import importlib.machinery
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "network: marks tests requiring real network access (deselect with -m 'not network')",
    )


def pytest_collection_modifyitems(config, items):
    """默认跳过 network 标记的测试（可用 --run-network 开启）。"""
    if not config.getoption("--run-network", default=False):
        skip_network = pytest.mark.skip(reason="需要网络访问，请用 --run-network 运行")
        for item in items:
            if "network" in item.keywords:
                item.add_marker(skip_network)


def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="包含需要网络访问的测试（如 DDG 搜索）",
    )

# src/ 目录（conftest 位于 src/test/，故 parent 即 src/）
SRC = Path(__file__).resolve().parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ── Stub helpers ──────────────────────────────────────────────────────────────

def pkg_stub(dotted_name: str, path: Path | None = None) -> types.ModuleType:
    """注册一个带 __path__ 的空壳包，让 Python 跳过其 __init__.py 但仍可寻址子模块。"""
    m = types.ModuleType(dotted_name)
    m.__package__ = dotted_name
    m.__spec__ = importlib.machinery.ModuleSpec(
        dotted_name, loader=None, is_package=True
    )
    if path is not None:
        m.__path__ = [str(path)]
        m.__spec__.submodule_search_locations = m.__path__
    sys.modules[dotted_name] = m
    return m


def mod_stub(dotted_name: str) -> types.ModuleType:
    """注册一个普通空壳模块（无子包）。"""
    m = types.ModuleType(dotted_name)
    m.__spec__ = importlib.machinery.ModuleSpec(dotted_name, loader=None)
    sys.modules[dotted_name] = m
    return m


def stub_react_and_langchain() -> None:
    """
    桩住 react 包（跳过 __init__.py）以及 langchain_community 的重型依赖。
    在任何需要导入 react.action.tools.impl.* 的测试文件顶部调用一次。
    """
    REACT_DIR = SRC / "agent" / "react"

    pkg_stub("agent.react", REACT_DIR)

    lc_comm = pkg_stub("langchain_community")
    lc_emb  = mod_stub("langchain_community.embeddings")
    lc_vs   = mod_stub("langchain_community.vectorstores")
    lc_emb.HuggingFaceBgeEmbeddings = MagicMock(name="HuggingFaceBgeEmbeddings")
    lc_vs.FAISS = MagicMock(name="FAISS")
    lc_comm.embeddings  = lc_emb
    lc_comm.vectorstores = lc_vs
