from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Generator, Union

from config.react.tao_config import TaoConfig
from llm_core.llm import LLM
from react.action.executor import ActionExecutor
from react.memory.memory import Step
from react.memory.processor import MemoryProcessor
from react.parser import parse_llm_output
from react.prompt.manager import PromptManager


@dataclass
class StepStartEvent:
    index: int


@dataclass
class ChunkEvent:
    index: int
    chunk: str


@dataclass
class StepEvent:
    index: int
    thought: str
    action: str
    action_input: dict
    observation: str


@dataclass
class FinishEvent:
    answer: str


TaoEvent = Union[StepStartEvent, ChunkEvent, StepEvent, FinishEvent]


class TaoLoop:
    def __init__(
        self,
        llm: LLM,
        executor: ActionExecutor,
        tool_descriptions: dict[str, str],
        cfg: TaoConfig,
    ):
        self._llm = llm
        self._executor = executor
        self._cfg = cfg
        self._manager = PromptManager(tool_descriptions, cfg.prompt)

    def stream(self, question: str) -> Generator[TaoEvent, None, None]:
        processor = MemoryProcessor(self._cfg.memory, self._llm)

        for i in range(self._cfg.max_steps):
            result = processor.recall(question)
            messages = self._manager.build_messages(question, result)

            yield StepStartEvent(index=i)

            raw_output = ""
            for chunk in self._llm.stream_generate_messages(messages):
                raw_output += chunk
                yield ChunkEvent(index=i, chunk=chunk)

            thought, action, action_input = parse_llm_output(raw_output)

            if action.lower() == self._cfg.finish_action:
                answer = action_input.get("answer", raw_output)
                processor.commit(question, answer)
                self._manager.add_turn(question, answer)
                yield FinishEvent(answer=answer)
                return

            observation = self._executor.run(
                json.dumps({"action": action, "args": action_input}, ensure_ascii=False)
            )

            step = Step(
                thought=thought,
                action=action,
                action_input=action_input,
                observation=observation,
            )
            processor.add(step)

            yield StepEvent(
                index=i,
                thought=thought,
                action=action,
                action_input=action_input,
                observation=observation,
            )

        raise RuntimeError(f"TaoLoop exceeded max_steps={self._cfg.max_steps} without finishing")

    def reset(self) -> None:
        self._manager.clear_history()

    def run(self, question: str) -> str:
        for event in self.stream(question):
            if isinstance(event, FinishEvent):
                return event.answer
        raise RuntimeError(f"TaoLoop exceeded max_steps={self._cfg.max_steps} without finishing")
