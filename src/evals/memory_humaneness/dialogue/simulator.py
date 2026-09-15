"""拟人度管线：多轮对话模拟器。

对每个 (scenario, base)：
预载共同过去 → 逐轮（用户输入 → 检索 → 人格+记忆组装 → LLM 回复
→ 对话写回基座〔encode 侧〕）→ 产出一个 DialogueRecord（完整轨迹）。

用户侧两种模式：``ScriptedUser``（剧本预设输入）/ ``LLMUser``（另一个 LLM
扮演用户，只见历史与用户侧简笔，不见 Agent 的记忆块）。

transcript-first：所有 LLM 原始输出（user/reply/judge）在解析前逐条落盘。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..bases import preload
from ..judge import strip_reasoning
from ..schema import MemorySeed
from .persona import PERSONA_NAME, PERSONA_PROFILE, USER_SIDE_BRIEF
from .scenarios import Scenario

log = logging.getLogger("evals.memory_humaneness")


@dataclass
class DialogueTurn:
    index: int
    user: str
    agent: str
    memory_lines: list[str] = field(default_factory=list)

@dataclass
class DialogueRecord:
    scenario_id: str
    theme: str
    base: str
    turns: list[DialogueTurn] = field(default_factory=list)
    judge: dict = field(default_factory=dict)
    elapsed_sec: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def render_transcript(self) -> str:
        lines = [f"【场景】{self.theme}（{self.scenario_id}，基座={self.base}）"]
        for t in self.turns:
            lines.append(f"用户：{t.user}")
            lines.append(f"{PERSONA_NAME}：{t.agent}")
        return "\n".join(lines)


class _Transcript:
    def __init__(self, path: str | Path | None) -> None:
        self._path = Path(path) if path else None

    def save(self, kind: str, scenario_id: str, base: str, raw: str) -> None:
        if not self._path or not raw:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(
                {"kind": kind, "scenario_id": scenario_id, "base": base, "raw": raw},
                ensure_ascii=False,
            ))
            fh.write("\n")


class ScriptedUser:
    """预设输入：按剧本逐轮给出用户侧发言。"""

    mode = "scripted"

    def __init__(self, scenario: Scenario) -> None:
        self._turns = list(scenario.turns)
        self._i = 0

    def next_utterance(self, history: list[DialogueTurn]) -> str:
        _ = history
        if self._i >= len(self._turns):
            return ""
        text = self._turns[self._i]
        self._i += 1
        return text


class LLMUser:
    """LLM 扮演用户：只见用户简笔 + 对话历史，不见 Agent 的记忆块。

    ``raw_sink``：用户侧 LLM 原文回调，在剥离/解析之前调用（save-first）。
    """

    mode = "llm"

    def __init__(self, llm: Any, scenario: Scenario, *, max_turns: int,
                 raw_sink=None) -> None:
        self._llm = llm
        self._brief = USER_SIDE_BRIEF + ("\n场景：" + scenario.user_brief_extra
                                         if scenario.user_brief_extra else "")
        self._remaining = max_turns
        self._raw_sink = raw_sink

    def next_utterance(self, history: list[DialogueTurn]) -> str:
        if self._remaining <= 0:
            return ""
        self._remaining -= 1
        from langchain_core.messages import HumanMessage, SystemMessage

        convo = "\n".join(
            f"用户：{t.user}\n{PERSONA_NAME}：{t.agent}" for t in history
        ) or "（对话刚开始）"
        raw = self._llm.generate_messages([
            SystemMessage(content=self._brief + "\n只输出你这轮要说的话本身。"),
            HumanMessage(content=f"对话历史：\n{convo}\n\n轮到你了，只输出这一句。"),
        ])
        if self._raw_sink is not None:
            self._raw_sink(raw)  # 先保存，再解析
        return strip_reasoning(raw).strip() or "（沉默）"


class DialogueSimulator:
    """逐轮：检索(滚动窗口 query) → 人格+记忆 → 回复 → 写回基座。"""

    def __init__(
        self,
        agent_llm: Any,
        *,
        recall_top_k: int = 5,
        transcript_path: str | Path | None = None,
        rolling_window: int = 2,
    ) -> None:
        self._llm = agent_llm
        self._top_k = recall_top_k
        self._transcript = _Transcript(transcript_path)
        self._rolling = rolling_window
        self.gen_calls = 0

    def _system_prompt(self, memory_block: str) -> str:
        instr = (
            "【相关记忆】是你能想起来的东西，包括这轮对话之前刚发生的——"
            "自然地用，像想起一样，不翻账本；无关的忽略；想不起来就坦白。"
            "标了【隐约浮现】的，是隐隐约约浮现出来的、未必和当前话题相关的念头："
            "可以用'突然想起'的口吻轻轻带一下，也可以不提，别当作确定的事实。"
            "回复像真人发消息：一两句话、口语、有语气词，不打官腔不列举。"
        )
        parts = [PERSONA_PROFILE, instr]
        if memory_block.strip():
            parts.append("【相关记忆】\n" + memory_block.strip())
        return "\n\n".join(parts)

    def run_scenario(self, scenario: Scenario, base, user) -> DialogueRecord:
        t0 = time.perf_counter()
        kind = getattr(base, "kind", "?")
        record = DialogueRecord(scenario_id=scenario.scenario_id,
                                theme=scenario.theme, base=kind)
        try:
            preload(base, [
                MemorySeed(
                    text=m["text"], focus=m.get("focus", ""), emotion=m.get("emotion", ""),
                    valence=m.get("valence", "neutral"),
                    days_ago=float(m.get("days_ago", 5.0)),
                )
                for m in scenario.shared_memories
            ])
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

            history_msgs: list = []
            turns: list[DialogueTurn] = []
            while True:
                user_text = user.next_utterance(turns)
                if not user_text.strip():
                    break
                # 滚动窗口检索：近几轮 + 当前输入（含指代线索）
                if turns:
                    recent = " ".join(
                        [t.user for t in turns[-self._rolling:]] + [turns[-1].agent]
                    )
                else:
                    recent = ""
                query = (recent + " " + user_text).strip()
                block = base.recall(query, top_k=self._top_k)
                memory_lines = list(block.entries or [])

                history_msgs.append(HumanMessage(content=user_text))
                raw = self._llm.generate_messages(
                    [SystemMessage(content=self._system_prompt(block.render()))]
                    + history_msgs
                )
                self.gen_calls += 1
                self._transcript.save("reply", scenario.scenario_id, kind, raw)
                reply = strip_reasoning(raw).strip()
                if not reply:
                    reply = "……"  # 单轮空回复降级为沉默，不中断轨迹
                history_msgs.append(AIMessage(content=reply))
                turns.append(DialogueTurn(
                    index=len(turns), user=user_text, agent=reply,
                    memory_lines=memory_lines,
                ))
                # encode 侧：本轮对话写回基座（下一轮可被检索）
                base.ingest(
                    f"对话：用户说「{user_text}」，{PERSONA_NAME}回答「{reply}」",
                    focus=f"对话第{len(turns)}轮",
                    days_ago=0.0,
                )
            record.turns = turns
            record.elapsed_sec = round(time.perf_counter() - t0, 3)
            return record
        except Exception as exc:
            record.elapsed_sec = round(time.perf_counter() - t0, 3)
            record.error = f"{type(exc).__name__}: {exc}"
            log.warning("场景 %s × %s 失败：%s", scenario.scenario_id, kind, record.error)
            return record
