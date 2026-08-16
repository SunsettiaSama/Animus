from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.life.experience.domain.unit import ExperienceUnit

_PBX_PREFIX = "__pbx:"


@dataclass
class PresenceExperienceBundle:
    """锚点/体验 → presence static+dynamic 转移的专用字段包（一次同步尽量覆盖）。"""

    session_id: str = "tao"
    channel_id: str = ""
    source: str = ""
    experience_id: str = ""
    perception: str = ""
    narration: str = ""
    prior_thought: str = ""
    emotion_label: str = ""
    mood_span: str = ""
    linger_days: float = 0.0
    subjective_narrative: str = ""
    salience: float = 0.0
    valence_delta: float = 0.0
    arousal_delta: float = 0.0
    enqueue_share: bool = False
    push_to_user: bool = False
    share_content: str = ""
    share_why: str = ""
    share_desire: str = "mild"
    share_salience: float = 0.0
    promote_to_memory: bool = False
    impression_intensity: float = 0.0
    impression_why: str = ""
    annotation_decided: bool = False
    rumination_hint: str = ""
    dialogue_expectation: str = ""
    unit_ids: list[str] = field(default_factory=list)

    @property
    def wants_to_share(self) -> bool:
        return bool(self.enqueue_share) and bool(self.share_topic.strip())

    @property
    def share_topic(self) -> str:
        content = self.share_content.strip()
        if content:
            return content[:120]
        return ""

    @property
    def target_channel_id(self) -> str:
        return (self.channel_id or "").strip()

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "channel_id": self.channel_id,
            "source": self.source,
            "experience_id": self.experience_id,
            "perception": self.perception,
            "narration": self.narration,
            "prior_thought": self.prior_thought,
            "emotion_label": self.emotion_label,
            "mood_span": self.mood_span,
            "linger_days": self.linger_days,
            "subjective_narrative": self.subjective_narrative,
            "salience": self.salience,
            "valence_delta": self.valence_delta,
            "arousal_delta": self.arousal_delta,
            "enqueue_share": self.enqueue_share,
            "push_to_user": self.push_to_user,
            "share_content": self.share_content,
            "share_why": self.share_why,
            "share_desire": self.share_desire,
            "share_salience": self.share_salience,
            "promote_to_memory": self.promote_to_memory,
            "impression_intensity": self.impression_intensity,
            "impression_why": self.impression_why,
            "annotation_decided": self.annotation_decided,
            "wants_to_share": self.wants_to_share,
            "share_topic": self.share_topic,
            "rumination_hint": self.rumination_hint,
            "dialogue_expectation": self.dialogue_expectation,
            "unit_ids": list(self.unit_ids),
        }

    @classmethod
    def from_dict(cls, d: dict) -> PresenceExperienceBundle:
        enqueue = bool(d.get("enqueue_share", False))
        if "wants_to_share" in d and "enqueue_share" not in d:
            enqueue = bool(d.get("wants_to_share", False))
        share_content = str(d.get("share_content", "") or "")
        if not share_content:
            share_content = str(d.get("share_topic", "") or "")
        return cls(
            session_id=str(d.get("session_id", "tao")),
            channel_id=str(d.get("channel_id", "") or d.get("target_channel_id", "") or ""),
            source=str(d.get("source", "")),
            experience_id=str(d.get("experience_id", "")),
            perception=str(d.get("perception", "")),
            narration=str(d.get("narration", "")),
            prior_thought=str(d.get("prior_thought", "")),
            emotion_label=str(d.get("emotion_label", "")),
            mood_span=str(d.get("mood_span", "")),
            linger_days=float(d.get("linger_days", 0.0) or 0.0),
            subjective_narrative=str(d.get("subjective_narrative", "")),
            salience=float(d.get("salience", 0.0)),
            valence_delta=float(d.get("valence_delta", 0.0)),
            arousal_delta=float(d.get("arousal_delta", 0.0)),
            enqueue_share=enqueue,
            push_to_user=bool(d.get("push_to_user", False)),
            share_content=share_content,
            share_why=str(d.get("share_why", "") or ""),
            share_desire=str(d.get("share_desire", "mild")),
            share_salience=float(d.get("share_salience", 0.0)),
            promote_to_memory=bool(d.get("promote_to_memory", False)),
            impression_intensity=float(d.get("impression_intensity", 0.0) or 0.0),
            impression_why=str(d.get("impression_why", "") or ""),
            annotation_decided=bool(d.get("annotation_decided", False)),
            rumination_hint=str(d.get("rumination_hint", "")),
            dialogue_expectation=str(d.get("dialogue_expectation", "")),
            unit_ids=[str(x) for x in (d.get("unit_ids") or [])],
        )

    def meta_for_dynamic(self) -> dict[str, str]:
        meta: dict[str, str] = {}
        topic = self.share_topic
        content = self.share_content.strip() or topic
        if (self.enqueue_share or self.push_to_user) and content:
            if self.enqueue_share:
                meta["wants_to_share"] = "true"
                meta["enqueue_share"] = "true"
            if self.push_to_user:
                meta["push_to_user"] = "true"
            meta["share_topic"] = topic or content[:120]
            meta["share_content"] = content
            meta["share_desire"] = self.share_desire
            meta["share_salience"] = str(
                self.share_salience or self.salience or self.impression_intensity
            )
            if self.share_why.strip():
                meta["share_why"] = self.share_why.strip()
        if self.channel_id.strip():
            meta["target_channel_id"] = self.channel_id.strip()
        if self.promote_to_memory:
            meta["promote_to_memory"] = "true"
        if self.impression_why.strip():
            meta["impression_why"] = self.impression_why.strip()
        if self.impression_intensity:
            meta["impression_intensity"] = str(self.impression_intensity)
        if self.rumination_hint.strip():
            meta["rumination_hint"] = self.rumination_hint.strip()
        if self.dialogue_expectation.strip():
            meta["dialogue_expectation"] = self.dialogue_expectation.strip()
        return meta


def stamp_presence_bundle(unit: ExperienceUnit, bundle: PresenceExperienceBundle) -> None:
    raw = (unit.situation.prior_thought or "").strip()
    if raw.startswith("__actx:"):
        return
    unit.situation.prior_thought = _PBX_PREFIX + json.dumps(
        bundle.to_dict(), ensure_ascii=False
    )


def read_presence_bundle(unit: ExperienceUnit) -> PresenceExperienceBundle | None:
    raw = (unit.situation.prior_thought or "").strip()
    if not raw.startswith(_PBX_PREFIX):
        return None
    return PresenceExperienceBundle.from_dict(json.loads(raw[len(_PBX_PREFIX):]))


def presence_bundle_from_unit(unit: ExperienceUnit) -> PresenceExperienceBundle:
    stored = read_presence_bundle(unit)
    if stored is not None:
        return stored

    narration = (
        unit.situation.narration.strip()
        or unit.action.content.strip()
        or unit.situation.perception.strip()
    )
    feeling = unit.feeling
    share_content = feeling.share_content.strip()
    enqueue = bool(feeling.enqueue_share) and bool(share_content)
    if feeling.annotation_decided and feeling.enqueue_share and not share_content and narration:
        share_content = narration[:240]
        enqueue = True

    subjective = feeling.effective_subjective_narrative()
    if not subjective:
        subjective = unit.situation.narration.strip()

    channel_id = (unit.situation.channel_id or "").strip()
    return PresenceExperienceBundle(
        session_id=unit.situation.session_id or "tao",
        channel_id=channel_id,
        source=unit.source,
        experience_id=unit.id,
        perception=unit.situation.perception.strip(),
        narration=narration,
        prior_thought=unit.situation.prior_thought.strip(),
        emotion_label=feeling.emotion_label.strip(),
        mood_span=feeling.effective_mood_span(),
        linger_days=float(feeling.linger_days or 0.0),
        subjective_narrative=subjective,
        salience=feeling.salience,
        valence_delta=feeling.valence_delta,
        arousal_delta=feeling.arousal_delta,
        enqueue_share=enqueue,
        push_to_user=bool(feeling.push_to_user) and bool(share_content),
        share_content=share_content,
        share_why=feeling.share_why.strip(),
        share_desire=feeling.share_desire or "mild",
        share_salience=feeling.impression_intensity or feeling.salience,
        promote_to_memory=bool(feeling.promote_to_memory),
        impression_intensity=float(feeling.impression_intensity or 0.0),
        impression_why=feeling.impression_why.strip(),
        annotation_decided=bool(feeling.annotation_decided),
        unit_ids=[unit.id],
    )


def merge_presence_bundles(bundles: list[PresenceExperienceBundle]) -> PresenceExperienceBundle | None:
    """合并 static 叙事字段。分享意图不在此折叠——由逐条 annotation 入队。"""
    if not bundles:
        return None
    peak = max(bundles, key=lambda b: b.salience)
    parts_narration: list[str] = []
    parts_perception: list[str] = []
    unit_ids: list[str] = []
    for b in bundles:
        if b.narration and b.narration not in parts_narration:
            parts_narration.append(b.narration)
        if b.source != "interaction" and b.perception and b.perception not in parts_perception:
            parts_perception.append(b.perception)
        unit_ids.extend(b.unit_ids)
    return PresenceExperienceBundle(
        session_id=peak.session_id,
        channel_id=peak.channel_id,
        source=peak.source,
        experience_id=peak.experience_id,
        perception="\n".join(parts_perception)[:800],
        narration="\n".join(parts_narration)[:800],
        prior_thought=peak.prior_thought,
        emotion_label=peak.emotion_label,
        mood_span=peak.mood_span or next((b.mood_span for b in bundles if b.mood_span.strip()), ""),
        linger_days=max((b.linger_days for b in bundles), default=0.0),
        subjective_narrative=peak.subjective_narrative or peak.narration,
        salience=peak.salience,
        valence_delta=peak.valence_delta,
        arousal_delta=peak.arousal_delta,
        enqueue_share=False,
        push_to_user=False,
        share_content="",
        share_why="",
        share_desire="mild",
        share_salience=0.0,
        promote_to_memory=False,
        impression_intensity=0.0,
        impression_why="",
        annotation_decided=False,
        rumination_hint=peak.rumination_hint,
        dialogue_expectation=peak.dialogue_expectation,
        unit_ids=unit_ids,
    )
