"""Typed wrapper around the pinned official IFEval strict/loose verifier."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from test.workbench.ifeval.dataset import IFEvalCase
from test.workbench.ifeval.resources import configure_nltk_data


@dataclass(frozen=True)
class CaseEvaluation:
    key: int
    prompt: str
    response: str
    instruction_ids: tuple[str, ...]
    strict_checks: tuple[bool, ...]
    loose_checks: tuple[bool, ...]

    @property
    def strict_pass(self) -> bool:
        return all(self.strict_checks)

    @property
    def loose_pass(self) -> bool:
        return all(self.loose_checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "prompt": self.prompt,
            "response": self.response,
            "instruction_ids": list(self.instruction_ids),
            "strict_checks": list(self.strict_checks),
            "loose_checks": list(self.loose_checks),
            "strict_pass": self.strict_pass,
            "loose_pass": self.loose_pass,
        }


def evaluate_case(case: IFEvalCase, response: str) -> CaseEvaluation:
    configure_nltk_data()
    from test.workbench.ifeval.official import evaluation_lib

    official_input = evaluation_lib.InputExample(
        key=case.key,
        instruction_id_list=list(case.instruction_id_list),
        prompt=case.prompt,
        kwargs=[dict(item) for item in case.kwargs],
    )
    prompt_to_response = {case.prompt: response}
    strict = evaluation_lib.test_instruction_following_strict(
        official_input,
        prompt_to_response,
    )
    loose = evaluation_lib.test_instruction_following_loose(
        official_input,
        prompt_to_response,
    )
    return CaseEvaluation(
        key=case.key,
        prompt=case.prompt,
        response=response,
        instruction_ids=case.instruction_id_list,
        strict_checks=tuple(bool(x) for x in strict.follow_instruction_list),
        loose_checks=tuple(bool(x) for x in loose.follow_instruction_list),
    )


def evaluate_responses(
    cases: Iterable[IFEvalCase],
    responses_by_key: dict[int, str],
) -> list[CaseEvaluation]:
    results: list[CaseEvaluation] = []
    for case in cases:
        if case.key in responses_by_key:
            results.append(evaluate_case(case, responses_by_key[case.key]))
    return results
