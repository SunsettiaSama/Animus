from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any

from .simulation_compat import DialogueTranscript

# 与 evals/memory_humaneness/judge.py 的启发式词表同源，拷贝而非 import 以免耦合私有常量。
_ROBOTIC_MARKERS = (
    "作为一个", "作为您的", "很高兴为您", "希望这", "总的来说", "综上所述",
    "首先", "其次", "最后，", "建议您", "祝你生活愉快", "还有什么可以帮",
    "我能帮您", "有什么其他", "需要注意的是", "值得注意",
)

_ECHO_NGRAM = 8
_OPENER_CHARS = 6
_OPENER_STRIP = re.compile(r"[\s，。！？!?.、~～]")


@dataclass(frozen=True)
class BehaviorStats:
    """纯确定性 transcript 指标，不加任何 LLM。"""

    turns: int
    empty_rate: float
    robotic_marker_rate: float
    repeated_opener_rate: float
    echo_rate: float
    question_ratio: float
    mean_len: float
    len_std: float
    naturalness: float
    flags: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "turns": self.turns,
            "empty_rate": self.empty_rate,
            "robotic_marker_rate": self.robotic_marker_rate,
            "repeated_opener_rate": self.repeated_opener_rate,
            "echo_rate": self.echo_rate,
            "question_ratio": self.question_ratio,
            "mean_len": self.mean_len,
            "len_std": self.len_std,
            "naturalness": self.naturalness,
            "flags": list(self.flags),
        }


def behavior_stats(transcript: DialogueTranscript) -> BehaviorStats:
    replies = [turn.speak.strip() for turn in transcript.turns]
    users = [turn.user.strip() for turn in transcript.turns]
    turns = len(replies)
    if turns == 0:
        return BehaviorStats(
            turns=0,
            empty_rate=1.0,
            robotic_marker_rate=0.0,
            repeated_opener_rate=0.0,
            echo_rate=0.0,
            question_ratio=0.0,
            mean_len=0.0,
            len_std=0.0,
            naturalness=0.0,
            flags=("no_turns",),
        )

    empty = sum(1 for text in replies if not text)
    marker_hits = sum(
        sum(1 for marker in _ROBOTIC_MARKERS if marker in text) for text in replies
    )
    openers = [_opener(text) for text in replies]
    opener_counts: dict[str, int] = {}
    for opener in openers:
        opener_counts[opener] = opener_counts.get(opener, 0) + 1
    repeated = sum(1 for opener in openers if opener_counts[opener] > 1)
    echo = sum(
        1
        for index in range(1, turns)
        if _has_echo(users[index], replies[index])
    )
    questions = sum(1 for text in replies if "?" in text or "？" in text)
    lengths = [len(text) for text in replies]
    mean_len = sum(lengths) / turns
    len_std = statistics.pstdev(lengths) if turns > 1 else 0.0

    stats = BehaviorStats(
        turns=turns,
        empty_rate=empty / turns,
        robotic_marker_rate=marker_hits / turns,
        repeated_opener_rate=repeated / turns,
        echo_rate=echo / max(1, turns - 1),
        question_ratio=questions / turns,
        mean_len=mean_len,
        len_std=len_std,
        naturalness=0.0,
    )
    naturalness = behavior_naturalness(stats)
    flags = _flags(stats)
    return BehaviorStats(
        turns=stats.turns,
        empty_rate=stats.empty_rate,
        robotic_marker_rate=stats.robotic_marker_rate,
        repeated_opener_rate=stats.repeated_opener_rate,
        echo_rate=stats.echo_rate,
        question_ratio=stats.question_ratio,
        mean_len=stats.mean_len,
        len_std=stats.len_std,
        naturalness=naturalness,
        flags=flags,
    )


def behavior_naturalness(stats: BehaviorStats) -> float:
    """加权扣分制，权重和为 1，输出 [0, 1]。

    - 空回复是管线故障，最重罚；
    - 机器人腔按每轮平均命中数饱和；
    - 反问比的健康带在 0.45 附近（会接话会好奇，但不是每轮反问）；
    - 句长完全均一或明显长篇大论都扣分。
    """
    score = 1.0
    score -= 0.20 * stats.empty_rate
    score -= 0.15 * min(1.0, stats.robotic_marker_rate / 2.0)
    score -= 0.15 * stats.repeated_opener_rate
    score -= 0.15 * stats.echo_rate
    score -= 0.15 * min(1.0, abs(stats.question_ratio - 0.45) / 0.55)
    score -= 0.10 * max(0.0, 1.0 - stats.len_std / 15.0)
    score -= 0.10 * min(1.0, max(0.0, (stats.mean_len - 120.0) / 120.0))
    return round(max(0.0, min(1.0, score)), 4)


def _flags(stats: BehaviorStats) -> tuple[str, ...]:
    flags: list[str] = []
    if stats.empty_rate > 0:
        flags.append("empty_reply")
    if stats.robotic_marker_rate >= 0.5:
        flags.append("robotic_markers")
    if stats.repeated_opener_rate >= 0.5:
        flags.append("repeated_opener")
    if stats.echo_rate >= 0.5:
        flags.append("echo")
    if stats.question_ratio >= 0.9:
        flags.append("interrogation")
    if stats.question_ratio == 0.0:
        flags.append("never_asks")
    return tuple(flags)


def _opener(text: str) -> str:
    cleaned = _OPENER_STRIP.sub("", text)
    return cleaned[:_OPENER_CHARS]


def _has_echo(user_text: str, reply: str, n: int = _ECHO_NGRAM) -> bool:
    if not reply or len(user_text) < n:
        return False
    grams = {user_text[i : i + n] for i in range(len(user_text) - n + 1)}
    return any(gram in reply for gram in grams)
