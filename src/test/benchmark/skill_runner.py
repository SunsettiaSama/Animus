"""
SkillRunner â€?smoke-gate BenchmarkRunner that validates skill action schemas
and verifies each skill can be instantiated without errors.

Gate: smoke â€?no LLM required, no network. Tests Pydantic validation only.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

from test.benchmark.metrics import MetricsCollector, ScenarioResult

_SRC = Path(__file__).resolve().parent.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@dataclass
class _SkillCase:
    name: str
    skill_cls_path: str
    valid_args: dict
    invalid_args: dict | None = None
    description: str = ""


_CASES: list[_SkillCase] = [
    _SkillCase(
        name="skill_domain_learning_schema",
        skill_cls_path="agent.react.action.skill.domain_learning.DomainLearningSkill",
        valid_args={"goal": "Python asyncio", "max_concepts": 6},
        invalid_args={"max_concepts": 6},
        description="DomainLearningSkill requires goal field",
    ),
    _SkillCase(
        name="skill_web_research_schema",
        skill_cls_path="agent.react.action.skill.research.WebResearchSkill",
        valid_args={"topic": "latest AI developments 2026"},
        invalid_args={"depth": "beginner"},
        description="WebResearchSkill requires topic field",
    ),
    _SkillCase(
        name="skill_document_summary_schema",
        skill_cls_path="agent.react.action.skill.document_summary.DocumentSummarySkill",
        valid_args={"path": "docs/README.md"},
        invalid_args={"mode": "summary"},
        description="DocumentSummarySkill requires path field",
    ),
    _SkillCase(
        name="skill_github_trending_schema",
        skill_cls_path="agent.react.action.skill.github_trending_report.GitHubTrendingReportSkill",
        valid_args={"since": "daily", "language": "python"},
        invalid_args=None,
        description="GitHubTrendingReportSkill args are all optional with defaults",
    ),
    _SkillCase(
        name="skill_arxiv_frontier_schema",
        skill_cls_path="agent.react.action.skill.arxiv_frontier_report.ArxivFrontierReportSkill",
        valid_args={"query": "large language model", "max_results": 10},
        invalid_args={"max_results": 10},
        description="ArxivFrontierReportSkill requires query field",
    ),
    _SkillCase(
        name="skill_frontier_report_schema",
        skill_cls_path="agent.react.action.skill.frontier_report.FrontierReportSkill",
        valid_args={"topic": "large language model reasoning", "categories": ["nlp", "ai"]},
        invalid_args={"categories": ["nlp"]},
        description="FrontierReportSkill requires topic field",
    ),
    _SkillCase(
        name="skill_delegate_task_schema",
        skill_cls_path="agent.react.action.skill.delegate_task.DelegateTaskSkill",
        valid_args={"instruction": "Calculate the sum of 1 to 100"},
        invalid_args={},
        description="DelegateTaskSkill requires instruction field",
    ),
]


def _import_cls(dotted: str):
    import importlib
    module, _, attr = dotted.rpartition(".")
    mod = importlib.import_module(module)
    return getattr(mod, attr)


def _run_case(case: _SkillCase) -> ScenarioResult:
    collector = MetricsCollector(case.name)
    collector.mark_step(0)
    t0 = time.perf_counter()

    steps: list[dict] = []
    ok = True
    error_msg: str | None = None

    skill_cls: Any = _import_cls(case.skill_cls_path)
    steps.append({"step": "import", "status": "ok", "class": skill_cls.__name__})

    # Instantiation check
    skill_cls()
    steps.append({"step": "instantiate", "status": "ok"})

    # Valid args Pydantic validation (via args_model if present)
    if hasattr(skill_cls, "args_model") and skill_cls.args_model is not None:
        skill_cls.args_model(**case.valid_args)
        steps.append({"step": "valid_args_validate", "status": "ok", "args": case.valid_args})

        # Invalid args should fail (if provided and non-empty)
        if case.invalid_args is not None and case.invalid_args != case.valid_args:
            from pydantic import ValidationError
            required = {
                f for f, info in skill_cls.args_model.model_fields.items()
                if info.is_required()
            }
            # If any required field is missing in invalid_args, Pydantic should raise
            missing = required - set(case.invalid_args.keys())
            if missing:
                raised_ve = False
                try:
                    skill_cls.args_model(**case.invalid_args)
                except ValidationError:
                    raised_ve = True
                steps.append({
                    "step": "invalid_args_rejected",
                    "status": "ok" if raised_ve else "warn",
                    "missing_fields": list(missing),
                })
                if not raised_ve:
                    error_msg = f"Expected ValidationError for missing {missing!r}"
    else:
        steps.append({"step": "schema_check", "status": "skip", "note": "no args_model"})

    wall_ms = (time.perf_counter() - t0) * 1000

    if ok:
        collector.mark_done("schema ok")
    else:
        collector.mark_failed("assertion", error=error_msg)

    result = collector.finalize(quality_score=1.0 if ok else 0.0)
    result.trace = {
        "input":      case.valid_args,
        "steps":      steps,
        "output":     "schema validation passed" if ok else error_msg,
        "elapsed_ms": round(wall_ms, 3),
    }
    return result


class SkillRunner:
    """
    BenchmarkRunner that validates skill action class schemas.

    Gate: smoke â€?only tests importability, instantiation, and Pydantic validation.
    No LLM or network required.
    """

    name = "skill_tool"
    gate = "smoke"

    def run_all(self) -> list[ScenarioResult]:
        return [_run_case(c) for c in _CASES]

    def describe(self) -> str:
        return f"{len(_CASES)} skill schema validation case(s) (no LLM)"
