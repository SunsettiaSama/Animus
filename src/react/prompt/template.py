from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromptTemplate:
    system: str
    long_term_header: str
    medium_term_header: str
    question_prefix: str
    suffix: str
    step_format: str
    separator: str


EN = PromptTemplate(
    system=(
        "You are a ReAct (Reasoning + Acting) agent. "
        "Solve the given question step by step using the available tools.\n\n"
        "Available tools:\n{tool_list}\n\n"
        "Format your response STRICTLY as:\n"
        "Thought: <your reasoning>\n"
        "Action: <tool name>\n"
        "Action Input: <JSON object with arguments>\n\n"
        "When you have the final answer, use:\n"
        "Thought: I now know the final answer.\n"
        "Action: finish\n"
        'Action Input: {{"answer": "<your answer>"}}\n\n'
        "Do NOT skip any field. Always output Thought, Action, and Action Input."
    ),
    long_term_header="Background Knowledge (retrieved from long-term memory):",
    medium_term_header="Summary of previous steps:",
    question_prefix="Question:",
    suffix="Thought:",
    step_format=(
        "Thought: {thought}\n"
        "Action: {action}\n"
        "Action Input: {action_input}\n"
        "Observation: {observation}"
    ),
    separator="---",
)

CN = PromptTemplate(
    system=(
        "你是一个 ReAct（推理 + 行动）智能体，请使用可用工具逐步解决用户的问题。\n\n"
        "可用工具：\n{tool_list}\n\n"
        "请严格按照以下格式输出：\n"
        "Thought: <你的推理过程>\n"
        "Action: <工具名称>\n"
        "Action Input: <JSON 格式的参数>\n\n"
        "当你得出最终答案时，使用：\n"
        "Thought: 我现在知道最终答案了。\n"
        "Action: finish\n"
        'Action Input: {{"answer": "<你的答案>"}}\n\n'
        "不要省略任何字段，每次必须输出 Thought、Action 和 Action Input。"
    ),
    long_term_header="背景知识（来自长期记忆检索）：",
    medium_term_header="历史步骤摘要：",
    question_prefix="问题：",
    suffix="Thought:",
    step_format=(
        "Thought: {thought}\n"
        "Action: {action}\n"
        "Action Input: {action_input}\n"
        "Observation: {observation}"
    ),
    separator="---",
)

_REGISTRY: dict[str, PromptTemplate] = {
    "en": EN,
    "cn": CN,
}


def get_template(lang: str) -> PromptTemplate:
    key = lang.lower().strip()
    if key not in _REGISTRY:
        raise ValueError(f"unknown prompt language: {lang!r}, choices: {list(_REGISTRY)}")
    return _REGISTRY[key]
