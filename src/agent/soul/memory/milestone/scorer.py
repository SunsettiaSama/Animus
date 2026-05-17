from __future__ import annotations

import json
from typing import TYPE_CHECKING

from config.agent.memory.milestone_config import MilestoneConfig
from agent.react.context.memory import Step
from ...context.milestone.entry import MilestoneEntry

if TYPE_CHECKING:
    from infra.llm import BaseLLM

_SCORE_PROMPT = """\
你是一个对话重要性评估器。请判断以下对话是否值得作为长期里程碑记录下来。

对话内容：
Q: {question}
A: {answer}

评估标准（以下任意一条符合即可视为重要）：
- 用户分享了重要个人事件（情感转折、重大决策、关键承诺）
- 双方达成了重要共识或约定
- 用户提出了重大需求或解决了关键难题
- 包含值得长久记忆的重要信息

请给出重要性评分（0.0-1.0）。若评分 >= {threshold}，同时提供：
- summary：一句话概括（不超过50字）
- keywords：关键词列表（最多{max_keywords}个）
- emotion：情感标签（positive/negative/neutral）

仅输出 JSON，格式如下（重要时）：
{{"importance": 0.8, "summary": "用户决定...", "keywords": ["决定", "..."], "emotion": "positive"}}

或（不重要时）：
{{"importance": 0.2}}"""


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("no JSON object found")
    return json.loads(raw[start:end])


class ImportanceScorer:
    def __init__(self, llm: BaseLLM, cfg: MilestoneConfig) -> None:
        self._llm = llm
        self._cfg = cfg

    def score(
        self,
        question: str,
        answer: str,
        steps: list[Step],
    ) -> MilestoneEntry | None:
        prompt = _SCORE_PROMPT.format(
            question=question[:500],
            answer=answer[:500],
            threshold=self._cfg.importance_threshold,
            max_keywords=self._cfg.max_keywords,
        )

        raw = self._llm.generate(prompt)

        data = _parse_json(raw)

        importance = float(data.get("importance", 0))
        if importance < self._cfg.importance_threshold:
            return None

        summary = str(data.get("summary", question[:50]))[: self._cfg.max_summary_chars]
        keywords = list(data.get("keywords", []))[: self._cfg.max_keywords]
        emotion = str(data.get("emotion", "neutral"))
        if emotion not in ("positive", "negative", "neutral"):
            emotion = "neutral"

        detail = f"Q: {question}\nA: {answer}"[: self._cfg.max_detail_chars]

        return MilestoneEntry.new(
            summary=summary,
            detail=detail,
            keywords=keywords,
            emotion=emotion,
            importance=importance,
        )
