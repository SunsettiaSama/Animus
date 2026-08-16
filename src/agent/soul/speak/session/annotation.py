from __future__ import annotations

from dataclasses import dataclass

from .chunk import SpeakFeelingChunk


@dataclass(frozen=True)
class SpeakProductionAnnotation:
    """Speak 边界结构化产出标注（不进入主回复 schema）。"""

    enqueue_share: bool = False
    push_to_user: bool = False
    share_content: str = ""
    share_why: str = ""
    share_desire: str = "mild"
    promote_to_memory: bool = False
    impression_intensity: float = 0.0
    impression_why: str = ""
    annotation_decided: bool = False


def annotation_from_feeling(
    feeling: SpeakFeelingChunk,
    *,
    agent_text: str = "",
) -> SpeakProductionAnnotation:
    """从 SpeakFeelingChunk 可选结构化字段组装标注；未填则 undecided。"""
    impression_why = feeling.impression_why.strip() or feeling.salience.strip()
    if not feeling.annotation_decided:
        return SpeakProductionAnnotation(
            impression_why=impression_why,
            annotation_decided=False,
        )

    content = feeling.share_content.strip()
    if not content and (feeling.enqueue_share or feeling.push_to_user):
        content = agent_text.strip()[:240]
    why = feeling.share_why.strip() or feeling.salience.strip()
    return SpeakProductionAnnotation(
        enqueue_share=bool(feeling.enqueue_share) and bool(content),
        push_to_user=bool(feeling.push_to_user) and bool(content),
        share_content=content,
        share_why=why,
        share_desire=feeling.share_desire.strip() or "mild",
        promote_to_memory=bool(feeling.promote_to_memory),
        impression_intensity=float(feeling.impression_intensity or 0.0),
        impression_why=impression_why,
        annotation_decided=True,
    )
