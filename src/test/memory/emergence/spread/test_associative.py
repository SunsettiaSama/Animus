from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parents[4]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@dataclass
class ScoredUnit:
    unit: object
    relevance: float = 0.0
    activation: float = 0.0
    final_score: float = 0.0


_scored = types.ModuleType("agent.soul.memory.graph.scored")
_scored.ScoredUnit = ScoredUnit
sys.modules["agent.soul.memory.graph.scored"] = _scored

_path = SRC / "agent/soul/memory/emergence/spread/associative.py"
_spec = importlib.util.spec_from_file_location(
    "agent.soul.memory.emergence.spread.associative",
    _path,
)
_assoc = importlib.util.module_from_spec(_spec)
sys.modules["agent.soul.memory.emergence.spread.associative"] = _assoc
_spec.loader.exec_module(_assoc)

merge_hybrid_results = _assoc.merge_hybrid_results
perturb_vector = _assoc.perturb_vector


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
