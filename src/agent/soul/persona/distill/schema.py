from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

PERSONA_DISTILL_SCHEMA_VERSION = "persona_distill_v1"

SLICE_IDS = ("general", "dialogue", "story", "reasoning", "memory_anchor")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PersonaDistillPack:
    """五切片蒸馏产物（子画像）。

    各切片均为面向「扮演该角色的 LLM 服务」的自然语言 system 片段，
    按下游模块注入，职责互不重叠。Speak 对话仅允许使用 slices["dialogue"]。
    主画像（built_profile / self_concept 全文）不得接入 Speak。
    """

    schema_version: str = PERSONA_DISTILL_SCHEMA_VERSION
    source_revision: str = ""
    distilled_at: str = ""
    slices: dict[str, str] = field(default_factory=dict)

    def slice(self, key: str) -> str:
        return str(self.slices.get(key, "")).strip()

    def dialogue_text(self) -> str:
        return self.slice("dialogue")

    def is_current(self, revision: str) -> bool:
        return (
            self.schema_version == PERSONA_DISTILL_SCHEMA_VERSION
            and self.source_revision.strip() == revision.strip()
            and bool(self.slices)
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "source_revision": self.source_revision,
            "distilled_at": self.distilled_at,
            "slices": dict(self.slices),
        }

    @classmethod
    def from_dict(cls, d: dict) -> PersonaDistillPack:
        slices_raw = d.get("slices") or {}
        slices = {k: str(v).strip() for k, v in slices_raw.items() if str(v).strip()}
        distilled_at = str(d.get("distilled_at", "")).strip() or _now_iso()
        return cls(
            schema_version=str(d.get("schema_version", PERSONA_DISTILL_SCHEMA_VERSION)),
            source_revision=str(d.get("source_revision", "")),
            distilled_at=distilled_at,
            slices=slices,
        )

    @classmethod
    def empty(cls, *, source_revision: str = "") -> PersonaDistillPack:
        return cls(
            source_revision=source_revision,
            distilled_at=_now_iso(),
            slices={},
        )
