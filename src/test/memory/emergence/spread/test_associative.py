"""联想检索（associative）单元测试（真实导入链）。"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parents[4]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.memory.emergence.spread.associative import (
    merge_hybrid_results,
    perturb_vector,
)
from agent.soul.memory.graph.scored import ScoredUnit


@dataclass
class _Unit:
    id: str


def test_merge_hybrid_results_precise_first():
    precise = [ScoredUnit(_Unit("a")), ScoredUnit(_Unit("b"))]
    associative = [ScoredUnit(_Unit("b")), ScoredUnit(_Unit("c"))]
    p, a = merge_hybrid_results(precise, associative)
    assert [s.unit.id for s in p] == ["a", "b"]
    assert [s.unit.id for s in a] == ["c"]


def test_perturb_vector_zero_intensity():
    v = [1.0, 2.0]
    assert perturb_vector(v, 0.0, sigma=0.5) == v
