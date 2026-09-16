from __future__ import annotations

import re

from infra.llm import BaseLLM
from infra.llm.llm import HumanMessage, SystemMessage

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK = re.compile(r"<think>", re.IGNORECASE)


def strip_think(text: str) -> str:
    """剥掉推理模型（如 MiniMax-M3）混在 content 里的 <think> 块。

    若只有未闭合的 <think>（生成被 max_tokens 截断），取最后一个 </think>
    之后的部分；整体没闭合则视为无有效输出。
    """
    cleaned = _THINK_BLOCK.sub("", text).strip()
    if not _OPEN_THINK.search(cleaned):
        return cleaned
    parts = _OPEN_THINK.split(cleaned)
    tail = cleaned.rsplit("</think>", 1)
    if len(tail) == 2 and tail[1].strip():
        return tail[1].strip()
    # 未闭合：保留最后一段中可能跟在换行后的正文，否则放弃
    last = parts[-1] if parts else ""
    lines = [line for line in last.splitlines() if line.strip() and not line.strip().startswith("</think>")]
    if len(lines) >= 2:
        return "\n".join(lines[1:]).strip()
    return ""


class StripsThinkLLM(BaseLLM):
    """包装器：压思考 + 剥 <think>。只包模拟器/评委等评测侧 LLM，
    不包 speak 引擎（服务内部对思考内容的处理自成一体）。

    - 调用前往 system 末尾追加"直接输出结果"指令，压住推理模型的思考倾向；
    - 若输出被 <think> 吃干净（剥完为空），原样重试至多 2 次。
    """

    def __init__(self, inner: BaseLLM, *, max_attempts: int = 3) -> None:
        self._inner = inner
        self._max_attempts = max(1, max_attempts)

    def generate(self, prompt: str) -> str:
        return strip_think(self._inner.generate(prompt))

    def stream_generate(self, prompt: str):
        for chunk in self._inner.stream_generate(prompt):
            yield chunk

    def generate_messages(self, messages: list) -> str:
        cleaned = ""
        for _ in range(self._max_attempts):
            raw = self._inner.generate_messages(_no_think(messages))
            cleaned = strip_think(raw)
            if cleaned.strip():
                return cleaned
        return cleaned

    def stream_generate_messages(self, messages: list):
        yield from self._inner.stream_generate_messages(messages)


def _no_think(messages: list) -> list:
    if not messages:
        return messages
    head = messages[0]
    content = str(getattr(head, "content", "") or "")
    if "不要输出思考过程" in content:
        return messages
    suffix = "\n不要输出思考过程，不要解释，直接给出要求的最终结果本身。"
    rebuilt = SystemMessage(content=content.rstrip() + suffix)
    return [rebuilt, *messages[1:]]


def system_human(system: str, user: str) -> list:
    return [SystemMessage(content=system), HumanMessage(content=user)]
