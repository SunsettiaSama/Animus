from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ...persona.preference.entry import PreferenceEntry
from ...persona.preference.recent import RecentPreference

if TYPE_CHECKING:
    from llm_core.llm import BaseLLM

_UPDATE_PROMPT = """\
请根据以下对话，分析 Agent 当前对话轮次的偏好状态。

当前近期偏好摘要：
{current_summary}

最新对话：
Q: {question}
A: {answer}

请输出本次对话对应的偏好快照（仅输出 JSON，不要任何解释）：
{{
  "mood": "<一个词，如 curious/happy/stressed/analytical/empathetic/playful/neutral>",
  "topic_interests": ["最多5个当前话题兴趣关键词"],
  "style_shifts": {{"幽默感": 0.1, "正式度": -0.1}}
}}

规则：
- mood 只能是一个简短词语
- topic_interests 不超过 5 条，直接从对话内容提取
- style_shifts 表示本次对话风格倾向，值域 [-0.5, 0.5]，无特殊偏移时可为空对象 {{}}"""


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("no JSON object found")
    return json.loads(raw[start:end])


class PreferenceUpdater:
    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def update(
        self,
        recent: RecentPreference,
        question: str,
        answer: str,
    ) -> RecentPreference:
        """分析 Q&A，生成新的 PreferenceEntry 并追加到 recent 窗口中。"""
        current_summary = recent.render() or "（尚无近期记录）"
        prompt = _UPDATE_PROMPT.format(
            current_summary=current_summary,
            question=question[:400],
            answer=answer[:400],
        )

        raw = self._llm.generate(prompt)
        data = _parse_json(raw)

        entry = PreferenceEntry.new(
            mood=str(data.get("mood", "neutral"))[:30],
            topic_interests=list(data.get("topic_interests", []))[:5],
            style_shifts={
                str(k): float(v)
                for k, v in data.get("style_shifts", {}).items()
            },
        )
        recent.add(entry)
        return recent
