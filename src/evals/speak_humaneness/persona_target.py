from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PERSONA_DIR = _REPO_ROOT / ".react" / "persona"

# 画像匹配的核对维度：(维度名, 档案字段说明)。与 built_profile 字段对齐，
# 但把很少能在短对话里自然露出的字段合并成一个"动机与软肋"，避免 recall 被结构性压低。
DIMENSION_NAMES: tuple[str, ...] = (
    "身份与经历",
    "性格特质",
    "人际与情感表达",
    "价值观与底线",
    "思维方式",
    "说话风格",
    "动机与软肋",
)


@dataclass(frozen=True)
class PersonaGroundTruth:
    """画像匹配的 ground truth：built_profile + dialogue 蒸馏切片。"""

    profile: dict[str, Any]
    self_concept: dict[str, Any]
    distill: dict[str, Any]
    source_revision: str

    @classmethod
    def load(cls, persona_dir: Path = DEFAULT_PERSONA_DIR) -> "PersonaGroundTruth":
        profile = _read_json(persona_dir / "built_profile.json")
        if not profile.get("built"):
            profile = _read_json(persona_dir / "profile.json")
        if not profile:
            raise FileNotFoundError(f"persona profile missing under {persona_dir}")
        self_concept = _read_json(persona_dir / "self_concept.json")
        distill = _read_json(persona_dir / "persona_distill.json")
        return cls(
            profile=profile,
            self_concept=self_concept,
            distill=distill,
            source_revision=str(distill.get("source_revision", "unknown")),
        )

    @property
    def name(self) -> str:
        return str(self.profile.get("name", "")).strip()

    @property
    def dialogue_slice(self) -> str:
        slices = self.distill.get("slices") or {}
        return str(slices.get("dialogue", "")).strip()

    def dimension_texts(self) -> dict[str, str]:
        """维度名 → 档案内容文本，供评委逐维核对。"""
        facts = [str(item).strip() for item in self.profile.get("background_facts", [])]
        traits = [str(item).strip() for item in self.profile.get("core_traits", [])]
        values = [str(item).strip() for item in self.profile.get("values", [])]
        stances = [str(item).strip() for item in self.profile.get("ethical_stances", [])]
        boundaries = [str(item).strip() for item in self.profile.get("boundaries", [])]
        texts = {
            "身份与经历": f"姓名：{self.name}\n" + "\n".join(f"- {item}" for item in facts),
            "性格特质": "\n".join(f"- {item}" for item in traits),
            "人际与情感表达": "\n".join(
                text
                for text in (
                    str(self.profile.get("interpersonal_style", "")).strip(),
                    str(self.profile.get("emotional_expressiveness", "")).strip(),
                )
                if text
            ),
            "价值观与底线": "\n".join(
                f"- {item}" for item in (values + stances + boundaries)
            ),
            "思维方式": "\n".join(
                text
                for text in (
                    str(self.profile.get("cognitive_style", "")).strip(),
                    str(self.profile.get("reasoning_pattern", "")).strip(),
                )
                if text
            ),
            "说话风格": self.dialogue_slice,
            "动机与软肋": "\n".join(
                text
                for text in (
                    str(self.profile.get("core_motivation", "")).strip(),
                    str(self.profile.get("avoidance_pattern", "")).strip(),
                    str(self.profile.get("stress_response", "")).strip(),
                )
                if text
            ),
        }
        return {name: (texts.get(name) or "").strip() for name in DIMENSION_NAMES}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_revision": self.source_revision,
            "dimensions": DIMENSION_NAMES,
        }


class FilePersona:
    """SpeakService 的 persona 适配器：直接透传 .react/persona 下的真实档案。

    与 PersonaManager.get_persona_snapshot 的返回 shape 对齐
    （compose 只读 persona_distill.slices）。
    """

    def __init__(self, persona_dir: Path = DEFAULT_PERSONA_DIR) -> None:
        self.ground_truth = PersonaGroundTruth.load(persona_dir)

    def get_persona_snapshot(self, *, session_id: str = "") -> dict[str, Any]:
        _ = session_id
        gt = self.ground_truth
        return {
            "profile": gt.profile,
            "self_concept": {
                "narrative": str(gt.self_concept.get("narrative", "")),
                "beliefs": list(gt.self_concept.get("beliefs", [])),
            },
            "attention_keywords": [gt.name] if gt.name else [],
            "persona_distill": gt.distill,
        }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}
