"""Shared pytest config and stub helpers for src/test/."""
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
    if not config.getoption("--run-network", default=False):
        skip_network = pytest.mark.skip(reason="needs network; run with --run-network")
        for item in items:
            if "network" in item.keywords:
                item.add_marker(skip_network)


def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="include tests that require network access",
    )


SRC = Path(__file__).resolve().parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pkg_stub(dotted_name: str, path: Path | None = None) -> types.ModuleType:
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
    m = types.ModuleType(dotted_name)
    m.__spec__ = importlib.machinery.ModuleSpec(dotted_name, loader=None)
    sys.modules[dotted_name] = m
    return m


def stub_react_and_langchain() -> None:
    REACT_DIR = SRC / "agent" / "react"

    pkg_stub("agent.react", REACT_DIR)

    lc_comm = pkg_stub("langchain_community")
    lc_emb = mod_stub("langchain_community.embeddings")
    lc_vs = mod_stub("langchain_community.vectorstores")
    lc_vs.FAISS = MagicMock(name="FAISS")
    lc_comm.embeddings = lc_emb
    lc_comm.vectorstores = lc_vs

    lc_hf = pkg_stub("langchain_huggingface")
    lc_hf.HuggingFaceEmbeddings = MagicMock(name="HuggingFaceEmbeddings")
