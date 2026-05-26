from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.life.experience.unit import ExperienceUnit

_PBX_PREFIX = "__pbx:"


@dataclass
class PresenceExperienceBundle:
    """锚点/体验 → presence static+dynamic 转移的专用字段包（一次同步尽量覆盖）。"""

    session_id: str = "tao"
    source: str = ""
    experience_id: str = ""
    perception: str = ""
    narration: str = ""
    prior_thought: str = ""
    emotion_label: str = ""
    salience: float = 0.0
    valence_delta: float = 0.0
    arousal_delta: float = 0.0
    wants_to_share: bool = False
    share_topic: str = ""
    share_desire: str = "mild"
    share_salience: float = 0.0
    rumination_hint: str = ""
    dialogue_expectation: str = ""
    unit_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "source": self.source,
            "experience_id": self.experience_id,
            "perception": self.perception,
            "narration": self.narration,
            "prior_thought": self.prior_thought,
            "emotion_label": self.emotion_label,
            "salience": self.salience,
            "valence_delta": self.valence_delta,
            "arousal_delta": self.arousal_delta,
            "wants_to_share": self.wants_to_share,
            "share_topic": self.share_topic,
            "share_desire": self.share_desire,
            "share_salience": self.share_salience,
            "rumination_hint": self.rumination_hint,
            "dialogue_expectation": self.dialogue_expectation,
            "unit_ids": list(self.unit_ids),
        }

    @classmethod
    def from_dict(cls, d: dict) -> PresenceExperienceBundle:
        return cls(
            session_id=str(d.get("session_id", "tao")),
            source=str(d.get("source", "")),
            experience_id=str(d.get("experience_id", "")),
            perception=str(d.get("perception", "")),
            narration=str(d.get("narration", "")),
            prior_thought=str(d.get("prior_thought", "")),
            emotion_label=str(d.get("emotion_label", "")),
            salience=float(d.get("salience", 0.0)),
            valence_delta=float(d.get("valence_delta", 0.0)),
            arousal_delta=float(d.get("arousal_delta", 0.0)),
            wants_to_share=bool(d.get("wants_to_share", False)),
            share_topic=str(d.get("share_topic", "")),
            share_desire=str(d.get("share_desire", "mild")),
            share_salience=float(d.get("share_salience", 0.0)),
            rumination_hint=str(d.get("rumination_hint", "")),
            dialogue_expectation=str(d.get("dialogue_expectation", "")),
            unit_ids=[str(x) for x in (d.get("unit_ids") or [])],
        )

    def meta_for_dynamic(self) -> dict[str, str]:
        meta: dict[str, str] = {}
        if self.wants_to_share and self.share_topic.strip():
            meta["wants_to_share"] = "true"
            meta["share_topic"] = self.share_topic.strip()
            meta["share_desire"] = self.share_desire
            meta["share_salience"] = str(self.share_salience or self.salience)
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
    salience = unit.feeling.salience
    wants_share = salience >= 0.45 and bool(narration)
    share_desire = "eager" if salience >= 0.7 else "moderate" if salience >= 0.5 else "mild"

    return PresenceExperienceBundle(
        session_id=unit.situation.session_id or "tao",
        source=unit.source,
        experience_id=unit.id,
        perception=unit.situation.perception.strip(),
        narration=narration,
        prior_thought=unit.situation.prior_thought.strip(),
        emotion_label=unit.feeling.emotion_label.strip(),
        salience=salience,
        valence_delta=unit.feeling.valence_delta,
        arousal_delta=unit.feeling.arousal_delta,
        wants_to_share=wants_share,
        share_topic=narration[:120] if wants_share else "",
        share_desire=share_desire,
        share_salience=salience,
        unit_ids=[unit.id],
    )


def merge_presence_bundles(bundles: list[PresenceExperienceBundle]) -> PresenceExperienceBundle | None:
    if not bundles:
        return None
    peak = max(bundles, key=lambda b: b.salience)
    parts_narration: list[str] = []
    parts_perception: list[str] = []
    unit_ids: list[str] = []
    wants_share = False
    share_topic = ""
    share_desire = "mild"
    for b in bundles:
        if b.narration and b.narration not in parts_narration:
            parts_narration.append(b.narration)
        if b.perception and b.perception not in parts_perception:
            parts_perception.append(b.perception)
        unit_ids.extend(b.unit_ids)
        if b.wants_to_share and b.share_topic:
            wants_share = True
            if not share_topic or b.salience >= peak.salience:
                share_topic = b.share_topic
                share_desire = b.share_desire
    return PresenceExperienceBundle(
        session_id=peak.session_id,
        source=peak.source,
        experience_id=peak.experience_id,
        perception="\n".join(parts_perception)[:800],
        narration="\n".join(parts_narration)[:800],
        prior_thought=peak.prior_thought,
        emotion_label=peak.emotion_label,
        salience=peak.salience,
        valence_delta=peak.valence_delta,
        arousal_delta=peak.arousal_delta,
        wants_to_share=wants_share,
        share_topic=share_topic,
        share_desire=share_desire,
        share_salience=peak.share_salience or peak.salience,
        rumination_hint=peak.rumination_hint,
        dialogue_expectation=peak.dialogue_expectation,
        unit_ids=unit_ids,
    )
