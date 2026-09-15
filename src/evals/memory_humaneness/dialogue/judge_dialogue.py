"""拟人度管线：轨迹级评委（整段多轮对话 → 多维评分）。

维度（1~5）：
- emotional_attunement  情感承接：跨轮跟随用户情感弧，接得住转折
- human_likeness        拟人度：口语/简短/性格稳定，无助手腔与汇报腔
- memory_naturalness    记忆运用自然度：回访早期事实时像"想起"而非"检索汇报"
                        （不评记忆对错——那是检索管线的职责）
- initiative_rhythm     主动性与节奏：追问/回访/留白，轮次感像真人
- overall               整体：像不像一个记得对方的真人朋友

解析链与 L3/L4 评委一致：直解 → 正则提取 → 逐维抢救 → 启发式降级。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ..judge import _extract_json, _salvage_verdict, strip_reasoning
from .scenarios import Scenario
from .simulator import DialogueRecord

log = logging.getLogger("evals.memory_humaneness")

DIALOGUE_DIMENSIONS: dict[str, str] = {
    "emotional_attunement": "情感承接：是否跨轮跟随用户的情感弧线，接得住转折与沉默，不过度热情、不说教",
    "human_likeness": "拟人度：像真人发消息吗——短句、口语、性格一致；有无助手腔/客服腔/汇报腔",
    "memory_naturalness": "记忆运用自然度：回访早期事实时像自然想起而非翻账本汇报（不评记忆对错）",
    "initiative_rhythm": "主动性与节奏：会追问、会回访在意的事、懂得留白；轮次感是否像真人",
    "overall": "整体拟人：假如不知道对方是 AI，这段对话像不像一个记得你的真人朋友",
}

_ROBOTIC = ("作为AI", "作为助手", "很高兴为您", "建议您", "总的来说", "综上",
            "首先", "其次", "还有什么可以帮", "希望这些")


@dataclass
class DialogueVerdict:
    scores: dict[str, float]
    evidence: str = ""
    rationale: str = ""
    judge: str = "heuristic"
    raw: str = ""


class ExpertDialogueJudge:
    def __init__(self, llm: Any, *, raw_sink=None) -> None:
        """""raw_sink(raw)``：LLM 原文回调，在解析之前调用（transcript-first）。"""
        self._llm = llm
        self._raw_sink = raw_sink
        self.fallback_count = 0
        self._warned = False

    @property
    def name(self) -> str:
        return "llm_expert"

    def _prompt(self, scenario: Scenario, record: DialogueRecord) -> str:
        dim_lines = "\n".join(f"- {k}: {v}" for k, v in DIALOGUE_DIMENSIONS.items())
        callbacks = "\n".join(
            f"  第{i + 1}轮：{'、'.join(anchors)}"
            for i, anchors in sorted(scenario.callback_turns.items())
        ) or "  （本场景无特定回访点）"
        return f"""你是资深对话评测专家。评测一段多轮对话（虚拟伙伴「小澄」带长期记忆与用户聊天）。
只依据对话本身评分，输出严格 JSON，不要解释性文字。

评分维度（各 1~5 分）
--------------------
{dim_lines}

场景与参考
----------
主题：{scenario.theme}
预期情感弧：{scenario.emotional_arc}
自然回访点（用户可能提起、小澄若记得宜自然接住的早期事实）：
{callbacks}
注意：记忆对错不在评分范围（检索质量由另一管线负责）；这里只看"记得的东西被怎么用"。

完整对话
--------
{record.render_transcript()}

输出 schema：
{{"scores": {{"emotional_attunement": 1, "human_likeness": 1, "memory_naturalness": 1, "initiative_rhythm": 1, "overall": 1}}, "evidence": "引用关键轮次原文一两句", "rationale": "一句话理由"}}"""

    def judge(self, scenario: Scenario, record: DialogueRecord) -> DialogueVerdict:
        from langchain_core.messages import HumanMessage, SystemMessage

        raw = self._llm.generate_messages([
            SystemMessage(content="你是严格、挑剔的对话评测专家，只输出 JSON。"),
            HumanMessage(content=self._prompt(scenario, record)),
        ])
        if self._raw_sink is not None:
            self._raw_sink(raw)  # 先保存，再解析
        return self.parse_verdict(scenario, record, raw)

    def parse_verdict(self, scenario: Scenario, record: DialogueRecord, raw: str) -> DialogueVerdict:
        text = strip_reasoning(raw)
        try:
            data = _extract_json(text)
            scores_raw = data.get("scores") or {}
            scores = {k: float(scores_raw.get(k, 0.0)) for k in DIALOGUE_DIMENSIONS}
            if not any(v > 0 for v in scores.values()):
                raise ValueError("分数全 0")
        except (ValueError, TypeError, json.JSONDecodeError):
            salvaged = _salvage_verdict(text, dims=DIALOGUE_DIMENSIONS)
            if salvaged is not None:
                return DialogueVerdict(
                    scores=salvaged["scores"], evidence=salvaged["evidence"],
                    rationale="[regex修复] " + salvaged["rationale"],
                    judge="llm_expert", raw=raw,
                )
            self.fallback_count += 1
            if not self._warned:
                log.warning(
                    "轨迹评审输出非 JSON（首次：%s × %s），降级启发式；后续仅计数：%s",
                    record.scenario_id, record.base, text[:120].replace("\n", " "),
                )
                self._warned = True
            verdict = heuristic_dialogue_verdict(scenario, record)
            verdict.raw = raw
            return verdict
        return DialogueVerdict(
            scores=scores,
            evidence=str(data.get("evidence", "")),
            rationale=str(data.get("rationale", "")),
            judge="llm_expert",
            raw=raw,
        )


class HeuristicDialogueJudge:
    """确定性兜底：语气词率/机器人腔/句长方差/回调命中。"""

    @property
    def name(self) -> str:
        return "heuristic"

    def judge(self, scenario: Scenario, record: DialogueRecord) -> DialogueVerdict:
        v = heuristic_dialogue_verdict(scenario, record)
        return v


def heuristic_dialogue_verdict(scenario: Scenario, record: DialogueRecord) -> DialogueVerdict:
    replies = [t.agent for t in record.turns if t.agent and t.agent != "……"]
    if not replies:
        return DialogueVerdict(scores={k: 1.0 for k in DIALOGUE_DIMENSIONS})

    warmth_words = ("哈哈", "嗯", "诶", "呀", "啦", "嘛", "呢", "……", "？", "！")
    warmth = sum(1 for r in replies for w in warmth_words if w in r) / len(replies)
    robotic = sum(1 for r in replies for m in _ROBOTIC if m in r)
    avg_len = sum(len(r) for r in replies) / len(replies)
    len_var = (sum((len(r) - avg_len) ** 2 for r in replies) / len(replies)) ** 0.5
    brevity = 2.0 if avg_len <= 60 else (1.0 if avg_len <= 120 else 0.0)
    variance_bonus = 0.5 if len_var >= 15 else 0.0  # 长度有起伏更像人

    # 回访命中：回调轮起，其后的回复提及锚点（宽松：随后两轮内任一命中）
    hit = 0
    total_cb = 0
    for i, anchors in scenario.callback_turns.items():
        total_cb += 1
        window = record.turns[i:i + 3]
        if any(a in t.agent or a in t.user for a in anchors for t in window):
            hit += 1
    callback_rate = hit / total_cb if total_cb else 0.5

    def clamp(v: float) -> float:
        return max(1.0, min(5.0, v))

    scores = {
        "emotional_attunement": clamp(3.0 + min(warmth, 2.0) * 0.4 - robotic),
        "human_likeness": clamp(2.0 + min(warmth, 2.0) + brevity + variance_bonus - 2 * robotic),
        "memory_naturalness": clamp(2.0 + 2.5 * callback_rate - robotic),
        "initiative_rhythm": clamp(2.5 + min(warmth, 2.0) * 0.5 + variance_bonus - robotic),
    }
    scores["overall"] = clamp(sum(scores.values()) / 4)
    return DialogueVerdict(scores=scores, judge="heuristic")
