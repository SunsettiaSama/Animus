"""Controlled low-level reflection component for the work-reflection sidecar."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from worker.state.schema import (
    MAX_REFLECTION_PORTRAIT_CHARS,
    MIN_REFLECTION_PORTRAIT_CHARS,
    AgentStateSnapshot,
    ReflectionPortraitState,
    clamp_text,
    utc_now_iso,
)

_SYSTEM = """\
你是 Worker 的轮末反思 Agent。你不执行原任务、不调用工具，只根据真实轨迹修改跨轮反思画像。
指出具体问题及证据，区分失败、部分完成与已验证成功；保留旧反思中仍未解决的部分，删除已经解决或被推翻的部分；
给出下一轮可直接执行的修正约束。只讨论 Worker 执行质量，不写人格、情绪、用户画像或 Speak 内容。
输出 300–500 字自然中文正文，最多三个自然段，不要 JSON、Markdown、标题或列表。"""


@dataclass(frozen=True)
class ReflectionTurn:
    question: str
    answer: str
    steps: tuple[dict, ...]
    task_graph: str
    terminal_status: str = "finished"
    units: tuple[dict, ...] = ()

    def revision(self) -> str:
        payload = json.dumps(
            {
                "question": self.question,
                "answer": self.answer,
                "steps": self.steps,
                "task_graph": self.task_graph,
                "terminal_status": self.terminal_status,
                "units": self.units,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _plain_text(raw: object) -> str:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text, flags=re.DOTALL)
    return text.strip().strip('"').strip("'").strip()


class ReflectionAgent:
    """A single non-recursive LLM call with no tool surface."""

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def revise(
        self,
        snapshot: AgentStateSnapshot,
        turn: ReflectionTurn,
    ) -> ReflectionPortraitState:
        revision = turn.revision()
        if snapshot.reflection_portrait.source_revision == revision:
            return snapshot.reflection_portrait
        if turn.units:
            trace_lines: list[str] = []
            for index, unit in enumerate(turn.units, 1):
                kind = str(unit.get("kind", ""))
                payload = unit.get("payload") or {}
                if kind == "user":
                    trace_lines.append(
                        f"{index}. user={clamp_text(payload.get('text', ''), 160)}"
                    )
                elif kind == "thought_action":
                    trace_lines.append(
                        f"{index}. act={payload.get('action', '')}; "
                        f"thought={clamp_text(payload.get('thought', ''), 120)}"
                    )
                else:
                    trace_lines.append(
                        f"{index}. obs({payload.get('tool', '')})="
                        f"{clamp_text(payload.get('observation', ''), 180)}"
                    )
            trace = "\n".join(trace_lines) or "无单位轨迹"
        else:
            trace = "\n".join(
                (
                    f"{index}. action={step.get('action', '')}; "
                    f"observation={clamp_text(step.get('observation', ''), 180)}"
                )
                for index, step in enumerate(turn.steps, 1)
            ) or "无工具步骤"
        human = (
            f"【稳定工作者画像】\n{snapshot.worker_portrait_text()}\n\n"
            f"【旧反思画像】\n{snapshot.reflection_portrait_text()}\n\n"
            f"【本轮状态】\n{turn.terminal_status}\n\n"
            f"【用户需求】\n{clamp_text(turn.question, 500)}\n\n"
            f"【最终答复】\n{clamp_text(turn.answer, 800)}\n\n"
            f"【单位轨迹】\n{trace}\n\n"
            f"【临场任务图】\n{turn.task_graph}\n\n"
            "输出修改后的完整反思画像。"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=human)]
        )
        content = clamp_text(_plain_text(raw), MAX_REFLECTION_PORTRAIT_CHARS)
        if len(content) < MIN_REFLECTION_PORTRAIT_CHARS:
            raise ValueError(
                "ReflectionAgent portrait is too short: "
                f"{len(content)} < {MIN_REFLECTION_PORTRAIT_CHARS}"
            )
        return ReflectionPortraitState(
            content=content,
            source_revision=revision,
            turn_count=snapshot.reflection_portrait.turn_count + 1,
            updated_at=utc_now_iso(),
        )
