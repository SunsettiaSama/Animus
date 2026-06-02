from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from infra.llm import BaseLLM

from .engine import SpeakLLMEngine


@dataclass
class DirectorDecision:
    action: str = "hold"
    lines: list[str] = field(default_factory=list)
    reason: str = ""

    def snapshot(self) -> dict[str, object]:
        return {
            "action": self.action,
            "lines": list(self.lines),
            "reason": self.reason,
        }


class SpeakDirectorLLMEngine:
    """会话导演小模型：节奏决策 JSON，不生成长文 turn。"""

    _SYSTEM = (
        "你是会话节奏导演。根据上下文判断此刻是否应极短插话、酝酿排队或保持沉默。\n"
        "只输出一行 JSON："
        '{"action":"push_now|enqueue_brew|hold","lines":["…"],"reason":"…"}\n'
        "规则：push_now 最多 1 条且每条≤40字；enqueue_brew 可多条≤40字；无必要则 hold。"
    )

    def __init__(self, llm: BaseLLM | None = None) -> None:
        self._engine = SpeakLLMEngine(llm=llm)

    @property
    def available(self) -> bool:
        return self._engine.llm is not None

    def decide(self, user_prompt: str) -> DirectorDecision:
        if not self.available:
            return DirectorDecision(action="hold", reason="director_llm_unconfigured")
        raw = self._engine.generate(user_prompt, system=self._SYSTEM).text.strip()
        return parse_director_json(raw)

    def decide_messages(self, messages: list) -> DirectorDecision:
        if not self.available:
            return DirectorDecision(action="hold", reason="director_llm_unconfigured")
        raw = self._engine.generate_messages(messages).text.strip()
        return parse_director_json(raw)


def parse_director_json(raw: str) -> DirectorDecision:
    text = raw.strip()
    if not text:
        return DirectorDecision(action="hold", reason="empty_director_output")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return DirectorDecision(action="hold", reason="no_json_in_director_output")
    payload = json.loads(match.group())
    action = str(payload.get("action", "hold")).strip().lower()
    if action not in ("push_now", "enqueue_brew", "hold"):
        action = "hold"
    lines_raw = payload.get("lines") or []
    lines: list[str] = []
    if isinstance(lines_raw, list):
        for item in lines_raw:
            line = str(item).strip()
            if line:
                lines.append(line[:40])
    reason = str(payload.get("reason", "")).strip()
    if action == "push_now" and len(lines) > 1:
        lines = lines[:1]
    return DirectorDecision(action=action, lines=lines, reason=reason)
