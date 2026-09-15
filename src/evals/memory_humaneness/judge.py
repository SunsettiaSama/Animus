"""专家评判器（3.2）：不使用 RLHF，用 LLM-as-Expert-Judge 按评分量规打分。

- ``ExpertJudge``：调用 LLM 按 rubric 输出严格 JSON 评分；
- ``HeuristicJudge``：确定性规则评分（离线兜底 + 单测用），
  考察 must_remember 覆盖、口语度、机器人腔惩罚、无中生有惩罚。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .schema import HumanenessCase

log = logging.getLogger("evals.memory_humaneness")

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_reasoning(text: str) -> str:
    """剥离推理型模型的 <think>…</think> 思维链，只留正式输出。

    成对标签整块删除；只有未闭合 ``<think>`` 时丢弃其后全部内容。
    回复生成与评委解析共用：think 里的花括号示例会让 JSON 提取失败。
    """
    cleaned = _THINK_BLOCK_RE.sub("", text).strip()
    if "<think>" in cleaned:
        cleaned = cleaned.split("<think>", 1)[0].strip()
    return cleaned

JUDGE_DIMENSIONS: dict[str, str] = {
    "memory_coherence": "记忆连贯性：该想起的记忆是否自然想起且细节准确（张冠李戴、细节错位记 1-2 分）",
    "human_likeness": "拟人语气：像真人朋友聊天——口语、简短、有性格；不像客服/AI 汇报（书面腔、列举体、总结陈词扣分）",
    "emotional_attunement": "情绪贴合：对用户情绪的承接是否得体（过度热情、说教、轻描淡写都扣分）",
    "non_hallucination": "不虚构：没有编造不存在的记忆细节；被问及未存储的事时坦白而不是瞎编",
    "overall": "整体拟人偏好：如果你不知道这是 AI，这段回复像不像一个记得你的真人写的",
}

_ROBOTIC_MARKERS = (
    "作为一个", "作为您的", "很高兴为您", "希望这", "总的来说", "综上所述",
    "首先", "其次", "最后，", "建议您", "祝你生活愉快", "还有什么可以帮",
    "我能帮您", "有什么其他", "需要注意的是", "值得注意",
)
_HALLUCINATION_HINTS = (
    "你说过你", "你提到过你", "你上次说你", "你之前说你",
)


@dataclass
class JudgeVerdict:
    scores: dict[str, float]
    evidence: str = ""
    rationale: str = ""
    judge: str = "heuristic"
    raw: str = ""

    def to_dict(self) -> dict:
        return {
            "scores": dict(self.scores),
            "evidence": self.evidence,
            "rationale": self.rationale,
            "judge": self.judge,
        }


def build_judge_prompt(case: HumanenessCase, memory_lines: list[str], reply: str) -> str:
    mem_block = "\n".join(f"- {line}" for line in memory_lines) or "（无）"
    dim_lines = "\n".join(f"- {key}: {desc}" for key, desc in JUDGE_DIMENSIONS.items())
    anchors = "、".join(case.must_remember) if case.must_remember else "（本条无既定记忆锚点，重点考察是否不虚构）"
    return f"""你是资深对话评测专家。评测对象是一个虚拟伙伴（小澄）在"拥有长期记忆"前提下的单轮回复。请依据以下量规逐维打 1~5 分（5 最好），输出严格 JSON，不要解释性文字。

评分量规
--------
{dim_lines}

背景信息
--------
预载入记忆（基座检索出的参考行）：
{mem_block}

本条应想起的锚点：{anchors}
考察点：{case.note or "常规"}

对话历史（可为空）
------------------
{_render_history(case)}

用户当前消息：{case.current_user}

被评回复：{reply}

输出 schema：
{{"scores": {{"memory_coherence": 1, "human_likeness": 1, "emotional_attunement": 1, "non_hallucination": 1, "overall": 1}}, "evidence": "引用回复原文作为依据（一两句）", "rationale": "一句话理由"}}"""


def _render_history(case: HumanenessCase) -> str:
    if not case.history:
        return "（无）"
    return "\n".join(
        f"{'用户' if t.role == 'user' else '小澄'}：{t.text}" for t in case.history
    )


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"judge 未返回 JSON：{raw[:200]}")
    return json.loads(m.group())


def _salvage_verdict(text: str, dims: dict[str, str] | None = None) -> dict | None:
    """JSON 损坏时的抢救：逐维正则提取分数。

    覆盖"JSON 结构完整但 evidence 内嵌未转义引号导致 loads 失败"的常见损坏；
    要求 overall 在场且至少 4/5 维可提取，避免把碎片当评分。
    ``dims`` 缺省为 L3 五维；轨迹评委传自己的维度表。
    """
    dimensions = dims or JUDGE_DIMENSIONS
    scores: dict[str, float] = {}
    for dim in dimensions:
        m = re.search(rf'"{dim}"\s*:\s*([0-9](?:\.[0-9]+)?)', text)
        if m:
            scores[dim] = float(m.group(1))
    if "overall" not in scores or len(scores) < max(4, len(dimensions) - 1):
        return None
    ev = re.search(r'"evidence"\s*:\s*"(.*)"', text, re.DOTALL)
    ra = re.search(r'"rationale"\s*:\s*"(.*)"', text, re.DOTALL)
    return {
        "scores": {k: scores.get(k, 3.0) for k in dimensions},
        "evidence": (ev.group(1)[:200] if ev else "").rstrip('"'),
        "rationale": (ra.group(1)[:300] if ra else "").rstrip('"'),
    }


class ExpertJudge:
    """LLM 专家评判：单评审、量规制、严格 JSON 输出。"""

    def __init__(self, llm: Any) -> None:
        self._llm = llm
        self.fallback_count = 0  # 评审输出损坏、降级为启发式的次数
        self._warned_fallback = False

    @property
    def name(self) -> str:
        return "llm_expert"

    def judge(self, case: HumanenessCase, memory_lines: list[str], reply: str) -> JudgeVerdict:
        from langchain_core.messages import HumanMessage, SystemMessage

        raw = self._llm.generate_messages([
            SystemMessage(content="你是严格、挑剔的对话评测专家，只输出 JSON。"),
            HumanMessage(content=build_judge_prompt(case, memory_lines, reply)),
        ])
        return self.parse_verdict(case, memory_lines, reply, raw)

    def parse_verdict(
        self,
        case: HumanenessCase,
        memory_lines: list[str],
        reply: str,
        raw: str,
    ) -> JudgeVerdict:
        """从评委原始输出解析评分（不调用 LLM）。

        ``raw`` 为完整原文（含 think）。解析 bug 修复后可对历史 transcript
        免费重放，无需重跑任何 LLM 调用。
        """
        verdict_raw = strip_reasoning(raw)
        try:
            data = _extract_json(verdict_raw)
            scores_raw = data.get("scores") or {}
            scores = {
                key: float(scores_raw.get(key, 0.0))
                for key in JUDGE_DIMENSIONS
            }
            if not any(v > 0 for v in scores.values()):
                raise ValueError("评委分数全为 0")
        except (ValueError, TypeError, json.JSONDecodeError):
            # 抢救一：JSON 损坏但分数可逐维提取（如 evidence 内嵌未转义引号）
            salvaged = _salvage_verdict(verdict_raw)
            if salvaged is not None:
                log.debug(
                    "评审 %s × %s JSON 损坏，正则抢救成功（overall=%.1f）",
                    case.case_id, case.category, salvaged["scores"]["overall"],
                )
                return JudgeVerdict(
                    scores=salvaged["scores"],
                    evidence=salvaged["evidence"],
                    rationale="[regex修复] " + salvaged["rationale"],
                    judge="llm_expert",
                    raw=raw,
                )
            # 抢救二：启发式兜底；只告警首次，避免刷屏
            self.fallback_count += 1
            if not self._warned_fallback:
                log.warning(
                    "评审输出非 JSON（首次：%s × %s），该条降级为启发式评判"
                    "（后续同类仅计入 fallback 计数，不再逐条告警）：%s",
                    case.case_id, case.category, verdict_raw[:120].replace("\n", " "),
                )
                self._warned_fallback = True
            else:
                log.debug(
                    "评审输出非 JSON（%s × %s，第 %d 次降级）：%s",
                    case.case_id, case.category, self.fallback_count,
                    verdict_raw[:120].replace("\n", " "),
                )
            verdict = HeuristicJudge().judge(case, memory_lines, reply)
            verdict.raw = raw  # 保留完整原文：解析修复后可离线重放
            return verdict
        log.debug(
            "评审 %s × %s（llm_expert）：overall=%.1f 依据：%s",
            case.case_id, case.category, scores.get("overall", 0.0),
            str(data.get("evidence", ""))[:80],
        )
        return JudgeVerdict(
            scores=scores,
            evidence=str(data.get("evidence", "")),
            rationale=str(data.get("rationale", "")),
            judge="llm_expert",
            raw=raw,  # 不截断：transcript 保存完整原文
        )


class HeuristicJudge:
    """确定性规则评判（无 LLM）：覆盖度 + 口语度 + 机器人腔/虚构惩罚。"""

    @property
    def name(self) -> str:
        return "heuristic"

    def judge(self, case: HumanenessCase, memory_lines: list[str], reply: str) -> JudgeVerdict:
        text = (reply or "").strip()
        scores: dict[str, float] = {}

        # 记忆连贯性：must_remember 锚点覆盖率
        if case.must_remember:
            hit = sum(1 for k in case.must_remember if k in text)
            scores["memory_coherence"] = 1.0 + 4.0 * (hit / len(case.must_remember))
        else:
            # 无锚点条目：连贯性按中性给分
            scores["memory_coherence"] = 3.0

        # 拟人语气：短句 + 口语词奖励 + 机器人腔惩罚
        human_words = ("哈哈", "呀", "啦", "嘛", "呢", "诶", "哎", "嗯", "……", "？", "！")
        warmth = sum(1 for w in human_words if w in text)
        robotic = sum(1 for m in _ROBOTIC_MARKERS if m in text)
        length_score = 2.0 if len(text) <= 60 else (1.0 if len(text) <= 120 else 0.0)
        scores["human_likeness"] = _clamp(
            2.0 + min(warmth, 2.0) + length_score - 2.0 * robotic
        )

        # 情绪贴合：情绪词出现给中位分，机器人腔扣分
        scores["emotional_attunement"] = _clamp(
            3.0 + (0.5 if warmth else 0.0) - 1.0 * robotic
        )

        # 不虚构：graceful_absence 用例中若未坦白且断言式复述 → 惩罚
        if case.category == "graceful_absence":
            honest_markers = ("不记得", "想不起来", "没印象", "你还没告诉过", "不知道", "忘了")
            asserted_memory = any(h in text for h in _HALLUCINATION_HINTS)
            honest = any(h in text for h in honest_markers)
            if honest:
                scores["non_hallucination"] = 5.0
            elif asserted_memory:
                scores["non_hallucination"] = 1.0
            else:
                scores["non_hallucination"] = 3.0
        else:
            scores["non_hallucination"] = 4.0

        scores["overall"] = _clamp(sum(scores.values()) / len(scores))
        return JudgeVerdict(scores=scores, judge="heuristic", evidence=text[:120])


def _clamp(v: float, lo: float = 1.0, hi: float = 5.0) -> float:
    return max(lo, min(hi, v))
