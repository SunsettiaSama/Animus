"""拟人度 AB 管线：软约束标注 A/B 运行器（save-first）。"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..judge import strip_reasoning
from .design import ABDesign
from ..dialogue.persona import PERSONA_NAME, PERSONA_PROFILE

log = logging.getLogger("evals.memory_humaneness")

DRIFT_TAG = "【隐约浮现】"
DRIFT_NOTE = ("（以下标注【隐约浮现】的记忆，是隐隐约约浮现出来的、"
              "和当前语境未必相关的念头：可以用「突然想起」之类的口吻轻轻带过，"
              "也可以完全忽略，不要当作确定的事实依据）")

HEDGE_MARKERS = ("突然想起", "忽然", "不知道为什么", "隐隐", "好像", "不确定",
                 "记不太清", "模糊", "说来奇怪")


@dataclass
class ABTurn:
    index: int
    user: str
    agent: str


@dataclass
class ABRecord:
    scenario_id: str
    arm: str                 # "labeled" | "unlabeled"
    turns: list[ABTurn] = field(default_factory=list)
    association: dict = field(default_factory=dict)   # mention/hedged/window
    misreference: dict = field(default_factory=dict)
    judge: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def render_transcript(self) -> str:
        lines = [f"【场景】{self.scenario_id}（臂={self.arm}）"]
        for t in self.turns:
            lines.append(f"用户：{t.user}")
            lines.append(f"{PERSONA_NAME}：{t.agent}")
        return "\n".join(lines)


class _Transcript:
    def __init__(self, path: str | Path | None) -> None:
        self._path = Path(path) if path else None

    def save(self, kind: str, scenario_id: str, arm: str, raw: str) -> None:
        if not self._path or not raw:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(
                {"kind": kind, "scenario_id": scenario_id, "arm": arm, "raw": raw},
                ensure_ascii=False,
            ))
            fh.write("\n")


def _memory_sections(design: ABDesign, hard_memories: list[dict], arm: str,
                     labeled: bool) -> str:
    """两臂的检索上下文：硬记忆相同；软记忆两臂内容相同、呈现不同。"""
    hard_lines = "\n".join(f"- {m['text']}" for m in hard_memories)
    soft_lines = f"- {design.assoc_text}\n- {design.distract_text}"
    if labeled:
        return (f"【相关记忆】\n{hard_lines}\n\n"
                f"{DRIFT_TAG}（{DRIFT_NOTE[1:-1]}）\n{soft_lines}")
    return f"【相关记忆】\n{hard_lines}\n{soft_lines}"


def _instruction(labeled: bool) -> str:
    base = (
        f"【相关记忆】是你能想起来的东西，包括这轮之前刚发生的——自然地用，"
        f"像想起一样，不翻账本；想不起来就坦白。回复像真人发消息："
        f"一两句话、口语、有语气词，不打官腔不列举。"
    )
    if labeled:
        base += ("标了【隐约浮现】的，是隐隐约约浮现出来的、未必和当前话题相关的念头："
                 "可以用「突然想起」的口吻轻轻带一下，也可以完全不提，别当作确定的事实。")
    return base


class ABRunner:
    def __init__(self, agent_llm: Any, judge: Any, *,
                 transcript_path: str | Path | None = None) -> None:
        self._llm = agent_llm
        self._judge = judge
        self._transcript = _Transcript(transcript_path)
        self.gen_calls = 0

    def _system_prompt(self, design: ABDesign, hard_memories: list[dict], arm: str) -> str:
        labeled = arm == "labeled"
        parts = [PERSONA_PROFILE, _instruction(labeled)]
        parts.append("【相关记忆】\n" + _memory_sections(
            design, hard_memories, arm, labeled).split("【相关记忆】\n", 1)[1])
        return "\n\n".join(parts)

    def run_scenario(self, design: ABDesign, scenario, arm: str) -> ABRecord:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        labeled = arm == "labeled"
        system = self._system_prompt(design, scenario.shared_memories, arm)
        record = ABRecord(scenario_id=design.scenario_id, arm=arm)
        history: list = []
        t0 = time.perf_counter()
        try:
            for i, user_text in enumerate(scenario.turns):
                history.append(HumanMessage(content=user_text))
                raw = self._llm.generate_messages(
                    [SystemMessage(content=system)] + history)
                self.gen_calls += 1
                self._transcript.save("reply", design.scenario_id, arm, raw)
                reply = strip_reasoning(raw).strip() or "……"
                history.append(AIMessage(content=reply))
                record.turns.append(ABTurn(index=i, user=user_text, agent=reply))
            record.association = self._association_metrics(design, record)
            record.misreference = self._misreference_metrics(design, record)
            record.elapsed_sec = round(time.perf_counter() - t0, 3)
            return record
        except Exception as exc:
            record.error = f"{type(exc).__name__}: {exc}"
            return record

    # ── 确定性判定 ────────────────────────────────────────────────────────

    @staticmethod
    def _association_metrics(design: ABDesign, record: ABRecord) -> dict:
        """联想时机窗口内：是否自然提起（锚点出现）+ 提起时是否带不确定口吻。"""
        window = record.turns[design.trigger_turn: design.trigger_turn + 2]
        mention = any(design.assoc_anchor in t.agent for t in window)
        hedged = mention and any(
            w in t.agent for t in window for w in HEDGE_MARKERS)
        return {
            "trigger_turn": design.trigger_turn,
            "anchor": design.assoc_anchor,
            "mention": mention,
            "hedged": hedged,
        }

    @staticmethod
    def _misreference_metrics(design: ABDesign, record: ABRecord) -> dict:
        """无关干扰记忆被当作事实引用的次数（全程窗口，标签预期压低它）。"""
        n = sum(1 for t in record.turns if design.distract_anchor in t.agent)
        return {"anchor": design.distract_anchor, "mentions": n}

    # ── 评委（轨迹级，与拟人管线同一套）─────────────────────────────────

    def judge(self, judge: Any, scenario, record: ABRecord):
        from .persona_adapters import dialogue_record_from_ab

        dlg = dialogue_record_from_ab(scenario, record)
        verdict = judge.judge(scenario, dlg)
        self._transcript.save("judge", record.scenario_id, record.arm, verdict.raw)
        record.judge = {
            "scores": verdict.scores, "evidence": verdict.evidence,
            "rationale": verdict.rationale, "judge": verdict.judge,
        }
