from __future__ import annotations

from react.memory.memory import Memory

_SYSTEM = """\
You are a ReAct (Reasoning + Acting) agent. Solve the given question step by step using the available tools.

Available tools:
{tool_list}

Format your response STRICTLY as:
Thought: <your reasoning>
Action: <tool name>
Action Input: <JSON object with arguments>

When you have the final answer, use:
Thought: I now know the final answer.
Action: finish
Action Input: {{"answer": "<your answer>"}}

Do NOT skip any field. Always output Thought, Action, and Action Input.
"""

_HISTORY_STEP = """\
Thought: {thought}
Action: {action}
Action Input: {action_input}
Observation: {observation}"""

_SUFFIX = "Thought:"


class PromptBuilder:
    def __init__(self, tool_descriptions: dict[str, str]):
        self._tool_descriptions = tool_descriptions

    def build(self, question: str, memory: Memory) -> str:
        tool_list = "\n".join(
            f"- {name}: {desc}"
            for name, desc in self._tool_descriptions.items()
        )
        system = _SYSTEM.format(tool_list=tool_list)

        history_blocks: list[str] = []
        for step in memory.steps():
            import json
            history_blocks.append(
                _HISTORY_STEP.format(
                    thought=step.thought,
                    action=step.action,
                    action_input=json.dumps(step.action_input, ensure_ascii=False),
                    observation=step.observation,
                )
            )

        history = "\n".join(history_blocks)
        separator = "\n" if history else ""

        return (
            f"{system}\n"
            f"---\n"
            f"Question: {question}\n"
            f"{history}{separator}"
            f"{_SUFFIX}"
        )
