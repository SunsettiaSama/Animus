from __future__ import annotations

from dataclasses import dataclass, field

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.presence.state.dynamic.expectation.package import ShareFoldedPackage, fold_share_queue
from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent, ShareIntentQueue
from config.soul.presence.config import PROACTIVE_OPEN_THRESHOLD


@dataclass
class SharePromptHint:
    """注入 prompt 的分享提示（不含关键词 profile 展开）。"""

    wants_share: bool = False
    summary: str = ""


@dataclass
class ShareQueueEvaluation:
    """内驱/主动 speak 评估（保留阈值逻辑，供 drive 使用）。"""

    should_speak: bool
    summary: str
    package: ShareFoldedPackage
    toward_user: float = 0.0
    notes: list[str] = field(default_factory=list)


def evaluate_share_prompt(snap) -> SharePromptHint:
    """读取 presence 分享欲望：仅决定是否告知 agent + 摘要。"""
    state = snap.state
    interaction = snap.interaction
    queue = ShareIntentQueue.from_dict(
        (state.expectation.to_dict() or {}).get("share_queue"),
    )
    package = fold_share_queue(queue, interaction)
    summary = package.summary.strip()
    share_desire = interaction.share_desire
    wants_share = (
        not queue.is_empty()
        or share_desire != ShareDesire.none
        or bool(summary)
    )
    return SharePromptHint(wants_share=wants_share, summary=summary)


class ShareQueueComposer:
    """待分享队列评估（drive / 主动 speak 决策）。"""

    def __init__(
        self,
        *,
        proactive_threshold: float = PROACTIVE_OPEN_THRESHOLD,
    ) -> None:
        self._threshold = proactive_threshold

    def evaluate(self, snap) -> ShareQueueEvaluation:
        hint = evaluate_share_prompt(snap)
        state = snap.state
        interaction = snap.interaction
        queue = ShareIntentQueue.from_dict(
            (state.expectation.to_dict() or {}).get("share_queue"),
        )
        package = fold_share_queue(queue, interaction)
        toward_user = float(getattr(state.expectation, "toward_user", 0.0))
        notes: list[str] = []

        if not hint.wants_share:
            notes.append("no share desire")
            return ShareQueueEvaluation(
                should_speak=False,
                summary=hint.summary,
                package=package,
                toward_user=toward_user,
                notes=notes,
            )

        should_speak = toward_user >= self._threshold or float(interaction.impulse_level) >= 0.35
        if should_speak:
            notes.append("share desire ready for proactive speak")
        else:
            notes.append(
                f"share desire present, accumulating (toward_user={toward_user:.2f})"
            )
        return ShareQueueEvaluation(
            should_speak=should_speak,
            summary=hint.summary,
            package=package,
            toward_user=toward_user,
            notes=notes,
        )
