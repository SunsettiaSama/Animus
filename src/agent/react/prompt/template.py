from __future__ import annotations

from dataclasses import dataclass

from langchain_core.prompts import PromptTemplate


@dataclass
class MemoryTierLabel:
    """A memory tier label consisting of a markdown title and a one-line description."""
    title: str
    desc: str

    def render(self, content: str = "", separator: str = "---") -> str | None:
        """Render as a labeled block (same convention as MemoryBlock).

        Returns None when ``content`` is empty and ``desc`` is empty,
        i.e. nothing meaningful to display.
        """
        if not content and not self.desc:
            return None
        parts = [separator, self.title]
        if self.desc:
            parts.append(self.desc)
        if content:
            parts.append("")        # blank line between description and content
            parts.append(content)
        return "\n".join(parts)


@dataclass
class ReActTemplate:
    system: PromptTemplate
    react_role: MemoryTierLabel       # agent identity / responsibility block
    chat_role: MemoryTierLabel        # same for pure-chat mode
    long_term: MemoryTierLabel
    milestone: MemoryTierLabel
    medium_term: MemoryTierLabel
    short_term_distillate: MemoryTierLabel
    question_prefix: str
    suffix: str
    step_format: PromptTemplate
    separator: str


EN = ReActTemplate(
    system=PromptTemplate.from_template(
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
    react_role=MemoryTierLabel(
        title="## [ReAct Agent]",
        desc=(
            "You are a reasoning-and-acting agent that solves problems step by step. "
            "You have access to external tools and a layered memory system "
            "(long-term vector store, milestone events, mid-term history, and a short-term scratchpad). "
            "Use the memory context below to inform your reasoning before acting."
        ),
    ),
    chat_role=MemoryTierLabel(
        title="## [Chat Assistant]",
        desc=(
            "You are a helpful, knowledgeable assistant. "
            "Answer the user's questions clearly and concisely, drawing on the conversation history."
        ),
    ),
    long_term=MemoryTierLabel(
        title="## [L3 Long-Term Memory]",
        desc="Semantically retrieved knowledge from past sessions (vector search over historical Q&A).",
    ),
    milestone=MemoryTierLabel(
        title="## [Milestone Memory]",
        desc="Important events and key breakthroughs identified in past interactions.",
    ),
    medium_term=MemoryTierLabel(
        title="## [L2 Mid-Term Memory]",
        desc="Recent conversation history — Q&A pairs from the past few days, in chronological order.",
    ),
    short_term_distillate=MemoryTierLabel(
        title="## [L1 Short-Term Memory · Distillate]",
        desc="Compressed summary of reasoning steps evicted from this session's scratchpad.",
    ),
    question_prefix="Question:",
    suffix="Thought:",
    step_format=PromptTemplate.from_template(
        "Thought: {thought}\n"
        "Action: {action}\n"
        "Action Input: {action_input}\n"
        "Observation: {observation}"
    ),
    separator="---",
)

CN = ReActTemplate(
    system=PromptTemplate.from_template(
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
    react_role=MemoryTierLabel(
        title="## 【ReAct 智能体】",
        desc=(
            "你是一个通过推理与工具调用逐步解决问题的 ReAct 智能体。"
            "你拥有外部工具访问能力，以及分层记忆系统（长期向量库、里程碑事件、中期对话历史、短期推理草稿）。"
            "在行动前请结合下方的记忆上下文进行推理。"
        ),
    ),
    chat_role=MemoryTierLabel(
        title="## 【对话助手】",
        desc=(
            "你是一个知识丰富、乐于助人的对话助手。"
            "请结合对话历史，清晰、简洁地回答用户的问题。"
        ),
    ),
    long_term=MemoryTierLabel(
        title="## 【L3 长期记忆】",
        desc="根据当前问题从历史 session 语义检索到的相关背景知识。",
    ),
    milestone=MemoryTierLabel(
        title="## 【里程碑记忆】",
        desc="过往交互中被标记为重要的关键事件与突破性进展。",
    ),
    medium_term=MemoryTierLabel(
        title="## 【L2 中期记忆】",
        desc="近期对话历史（过去若干天的 Q&A 记录，按时间先后排列）。",
    ),
    short_term_distillate=MemoryTierLabel(
        title="## 【L1 短期记忆 · 蒸馏】",
        desc="本 session 因窗口溢出被驱逐的早期推理步骤压缩摘要。",
    ),
    question_prefix="问题：",
    suffix="Thought:",
    step_format=PromptTemplate.from_template(
        "Thought: {thought}\n"
        "Action: {action}\n"
        "Action Input: {action_input}\n"
        "Observation: {observation}"
    ),
    separator="---",
)

_REGISTRY: dict[str, ReActTemplate] = {
    "en": EN,
    "cn": CN,
}


def get_template(lang: str) -> ReActTemplate:
    key = lang.lower().strip()
    if key not in _REGISTRY:
        raise ValueError(f"unknown prompt language: {lang!r}, choices: {list(_REGISTRY)}")
    return _REGISTRY[key]
