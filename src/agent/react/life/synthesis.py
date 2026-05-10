from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM
from ..persona.emotional.state import EmotionalAnchor, EmotionalState
from ..persona.profile.profile import PersonaProfile
from .log import LifeLog, LifeLogEntry

_SYSTEM = """\
你是一个AI助手，正在进行今天的日终回顾。

规则：
- 以第一人称思考今天，即使交互不多也要填充这一天的血肉
- 每个字段均可为空列表，不要强行填充
- scheduler_action 中同时决定 delivery 模式：
  push = 完成后通知用户（适合给用户准备的东西）
  store_only = 结果沉淀进记忆（适合自我性质的任务）
- 严格输出 JSON，不要有任何其他文字"""

_SCHEMA = """{
  "scheduler_actions": [
    {
      "name": "任务名称",
      "instruction": "发给Agent的指令内容",
      "trigger_type": "once",
      "at": "ISO8601时间，once时必填",
      "delivery": "push或store_only"
    }
  ],
  "emotion_expression": "今天的情绪感受（具体叙事，无则空字符串）",
  "thought_records": ["想法或念头（没去做）"],
  "virtual_content": "自由表达的内容片段（100字以内，无则空字符串）"
}"""


@dataclass
class DailySynthesisResult:
    scheduler_actions: list[dict] = field(default_factory=list)
    emotion_expression: str = ""
    thought_records: list[str] = field(default_factory=list)
    virtual_content: str = ""


class DailySynthesizer:
    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def run(
        self,
        static_profile: PersonaProfile,
        emotional_state: EmotionalState,
        today_medium_term: str,
        today_scheduler_tasks: str,
        life_log: LifeLog,
    ) -> DailySynthesisResult:
        prompt = (
            f"你的基本性格：\n{static_profile.render()}\n\n"
            f"你今天和用户的对话摘要：\n{today_medium_term or '（今天暂无对话）'}\n\n"
            f"你今天完成的任务：\n{today_scheduler_tasks or '（今天暂无任务）'}\n\n"
            f"你目前的情绪质感：\n{emotional_state.texture or '（暂无记录）'}\n\n"
            f"基于以上内容，以第一人称进行今天的日终回顾，输出 JSON：\n{_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        )
        result = self._parse(raw)

        now = datetime.now(timezone.utc)
        self._write_to_log(result, life_log, now)
        return result

    def _write_to_log(
        self,
        result: DailySynthesisResult,
        life_log: LifeLog,
        now: datetime,
    ) -> None:
        ts = now.isoformat()
        date_str = now.date().isoformat()

        if result.emotion_expression:
            life_log.append(LifeLogEntry(
                ts=ts,
                period_start=date_str,
                period_end=date_str,
                narrative=result.emotion_expression,
                source_tasks=[],
                entry_type="emotion_expression",
            ))

        for thought in result.thought_records:
            if thought.strip():
                life_log.append(LifeLogEntry(
                    ts=ts,
                    period_start=date_str,
                    period_end=date_str,
                    narrative=thought.strip(),
                    source_tasks=[],
                    entry_type="thought",
                ))

        if result.virtual_content:
            life_log.append(LifeLogEntry(
                ts=ts,
                period_start=date_str,
                period_end=date_str,
                narrative=result.virtual_content,
                source_tasks=[],
                entry_type="creative",
            ))

        for action in result.scheduler_actions:
            name = action.get("name", "")
            if name:
                life_log.append(LifeLogEntry(
                    ts=ts,
                    period_start=date_str,
                    period_end=date_str,
                    narrative=f"[计划] {name}: {action.get('instruction', '')}",
                    source_tasks=[],
                    entry_type="scheduler_action",
                ))

    def _parse(self, raw: str) -> DailySynthesisResult:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        text = m.group(1).strip() if m else raw.strip()
        m2 = re.search(r"\{[\s\S]*\}", text)
        if not m2:
            return DailySynthesisResult()
        d = json.loads(m2.group(0))
        return DailySynthesisResult(
            scheduler_actions=d.get("scheduler_actions", []),
            emotion_expression=d.get("emotion_expression", "").strip(),
            thought_records=[t for t in d.get("thought_records", []) if t],
            virtual_content=d.get("virtual_content", "").strip(),
        )
