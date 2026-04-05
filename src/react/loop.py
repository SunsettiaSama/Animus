from __future__ import annotations

import json

from llm_core.llm import LLM
from react.action.executor import ActionExecutor
from react.memory.memory import Memory, Step
from react.parser import parse_llm_output
from react.prompt.builder import PromptBuilder

_FINISH_ACTION = "finish"


class ReActLoop:
    def __init__(
        self,
        llm: LLM,
        executor: ActionExecutor,
        tool_descriptions: dict[str, str],
        max_steps: int = 10,
    ):
        self._llm = llm
        self._executor = executor
        self._max_steps = max_steps
        self._prompt_builder = PromptBuilder(tool_descriptions)

    def run(self, question: str) -> str:
        memory = Memory()

        for step_idx in range(self._max_steps):
            prompt = self._prompt_builder.build(question, memory)
            raw_output = self._llm.generate(prompt)

            thought, action, action_input = parse_llm_output(raw_output)

            if action.lower() == _FINISH_ACTION:
                return action_input.get("answer", raw_output)

            observation = self._executor.run(
                json.dumps({"action": action, "args": action_input}, ensure_ascii=False)
            )

            memory.add(Step(
                thought=thought,
                action=action,
                action_input=action_input,
                observation=observation,
            ))

        raise RuntimeError(f"ReAct loop exceeded max_steps={self._max_steps} without finishing")
