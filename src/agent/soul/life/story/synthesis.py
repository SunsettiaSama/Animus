from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM
from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.status.life_bridge import LifeContextInput
from ..factual.event import EventType, LifeEvent
from ..factual.event_log import LifeEventLog

_SYSTEM = """\
你是一个AI助手，正在进行今天的日终回顾。

规则：
- 以第一人称视角，整理今天客观发生的事
- 只输出事实性的内容，不要加入情绪描写或主观判断
- scheduler_action 中决定 delivery 模式：
  push = 完成后通知用户（适合给用户准备的东西）
  store_only = 结果沉淀进记忆（适合自我性质的任务）
- thought_records 记录今天浮现但未付诸行动的念头（客观描述想到了什么，不描述感受）
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
  "thought_records": ["今天浮现但未付诸行动的念头（事实性描述）"],
  "virtual_content": "自由表达的内容片段（100字以内，无则空字符串）"
}"""


@dataclass
class DailySynthesisResult:
    """日终回顾结果——只包含事实性内容，不含情感判断。"""
    scheduler_actions: list[dict] = field(default_factory=list)
    thought_records: list[str] = field(default_factory=list)
    virtual_content: str = ""


class DailySynthesizer:
    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def run(
        self,
        static_profile: PersonaProfile,
        today_medium_term: str,
        today_scheduler_tasks: str,
        event_log: LifeEventLog,
        story_phase: str = "",
    ) -> tuple[DailySynthesisResult, LifeContextInput]:
        """执行日终回顾。

        Returns
        -------
        (result, life_ctx)
          result   : scheduler_actions / thought_records / virtual_content
          life_ctx : 供 status 层使用的 LifeContextInput（事实性上下文）
        """
        prompt = (
            f"你的基本性格：\n{static_profile.render()}\n\n"
            f"你今天和用户的对话摘要：\n{today_medium_term or '（今天暂无对话）'}\n\n"
            f"你今天完成的任务：\n{today_scheduler_tasks or '（今天暂无任务）'}\n\n"
            f"基于以上内容，以第一人称进行今天的日终事实整理，输出 JSON：\n{_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        )
        result = self._parse(raw)

        now = datetime.now(timezone.utc)
        date_str = now.date().isoformat()

        self._write_to_event_log(result, event_log, now)

        life_ctx = self._build_life_context(
            event_log=event_log,
            date_str=date_str,
            story_phase=story_phase,
            thought_records=result.thought_records,
        )
        return result, life_ctx

    def _write_to_event_log(
        self,
        result: DailySynthesisResult,
        event_log: LifeEventLog,
        now: datetime,
    ) -> None:
        for thought in result.thought_records:
            if thought.strip():
                event_log.append(LifeEvent.now(
                    event_type=EventType.THOUGHT,
                    description=thought.strip(),
                    source="daily_synthesis",
                ))
        if result.virtual_content:
            event_log.append(LifeEvent.now(
                event_type=EventType.CREATIVE,
                description=result.virtual_content,
                source="daily_synthesis",
            ))

    def _build_life_context(
        self,
        event_log: LifeEventLog,
        date_str: str,
        story_phase: str,
        thought_records: list[str],
    ) -> LifeContextInput:
        today_start = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        events = event_log.since(today_start)

        ctx = LifeContextInput.from_life_events(
            events=events,
            date=date_str,
            story_phase=story_phase,
        )
        if thought_records:
            ctx.notable_flags.extend(
                f"[thought] {t}" for t in thought_records if t.strip()
            )
        return ctx

    def _parse(self, raw: str) -> DailySynthesisResult:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        text = m.group(1).strip() if m else raw.strip()
        m2 = re.search(r"\{[\s\S]*\}", text)
        if not m2:
            return DailySynthesisResult()
        d = json.loads(m2.group(0))
        return DailySynthesisResult(
            scheduler_actions=d.get("scheduler_actions", []),
            thought_records=[t for t in d.get("thought_records", []) if t],
            virtual_content=d.get("virtual_content", "").strip(),
        )
