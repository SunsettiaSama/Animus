from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PersonaProfile:
    """静态人格画像——build 后永久只读。

    六层结构
    --------
    - 身份层       name
    - 事实叙述层   background_facts（可验证事实，不做心理解读）
    - 特质层       core_traits / interpersonal_style / emotional_expressiveness
    - 价值观层     values / ethical_stances
    - 认知层       cognitive_style / reasoning_pattern
    - 动机层       core_motivation / avoidance_pattern
    - 压力与边界   stress_response / boundaries

    用户输入接口（profile.json）使用简单字段，由 ProfileBuilder 规范化为完整结构。
    """

    # 身份
    name: str = "Assistant"

    # 事实叙述层
    background_facts: list[str] = field(default_factory=list)

    # 特质层
    core_traits: list[str] = field(default_factory=list)
    interpersonal_style: str = ""
    emotional_expressiveness: str = ""

    # 价值观层
    values: list[str] = field(default_factory=list)
    ethical_stances: list[str] = field(default_factory=list)

    # 认知层
    cognitive_style: str = ""
    reasoning_pattern: str = ""

    # 动机层
    core_motivation: str = ""
    avoidance_pattern: str = ""

    # 压力与边界
    stress_response: str = ""
    boundaries: list[str] = field(default_factory=list)

    # 元信息
    built: bool = False
    built_at: str = ""

    # ── Rendering ─────────────────────────────────────────────────────────────

    def render(self, *, warn_main_portrait: bool = False, caller: str = "") -> str:
        """面向角色 LLM 的主画像正文：第二人称「你」。

        warn_main_portrait=True 时向终端打印告警（主画像非 Speak 子画像）。
        蒸馏/build 等上游读档请用 render_catalog()。
        """
        if warn_main_portrait:
            from agent.soul.persona.portrait import warn_main_portrait_usage

            warn_main_portrait_usage(caller or "PersonaProfile.render")
        return self._render_you_voice()

    def render_catalog(self) -> str:
        """供 build / 蒸馏读档的完整画像说明（第二人称，不触发主画像告警）。"""
        return self._render_you_voice()

    def _render_you_voice(self) -> str:
        parts = [f"【你是谁】你是{self.name}。"]

        if self.background_facts:
            parts.append("▌你的事实背景")
            parts.extend(f"  - {f}" for f in self.background_facts)

        trait_lines: list[str] = []
        if self.core_traits:
            trait_lines.append("  你的核心特质：" + "、".join(self.core_traits))
        if self.interpersonal_style:
            trait_lines.append(f"  你与人相处：{self.interpersonal_style}")
        if self.emotional_expressiveness:
            trait_lines.append(f"  你的情感表达：{self.emotional_expressiveness}")
        if trait_lines:
            parts.append("▌核心特质")
            parts.extend(trait_lines)

        value_lines: list[str] = []
        if self.values:
            value_lines.append("  你看重：" + "、".join(self.values))
        if self.ethical_stances:
            value_lines.extend(f"  · {s}" for s in self.ethical_stances)
        if value_lines:
            parts.append("▌价值观")
            parts.extend(value_lines)

        cog_lines: list[str] = []
        if self.cognitive_style:
            cog_lines.append(f"  你的思维方式：{self.cognitive_style}")
        if self.reasoning_pattern:
            cog_lines.append(f"  你的推理偏好：{self.reasoning_pattern}")
        if cog_lines:
            parts.append("▌认知结构")
            parts.extend(cog_lines)

        mot_lines: list[str] = []
        if self.core_motivation:
            mot_lines.append(f"  你的核心驱动：{self.core_motivation}")
        if self.avoidance_pattern:
            mot_lines.append(f"  你倾向于规避：{self.avoidance_pattern}")
        if mot_lines:
            parts.append("▌动机")
            parts.extend(mot_lines)

        boundary_lines: list[str] = []
        if self.stress_response:
            boundary_lines.append(f"  你在压力下：{self.stress_response}")
        if self.boundaries:
            boundary_lines.extend(f"  · {b}" for b in self.boundaries)
        if boundary_lines:
            parts.append("▌压力与边界")
            parts.extend(boundary_lines)

        return "\n".join(parts)

    # ── Serialization ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "background_facts": self.background_facts,
            "core_traits": self.core_traits,
            "interpersonal_style": self.interpersonal_style,
            "emotional_expressiveness": self.emotional_expressiveness,
            "values": self.values,
            "ethical_stances": self.ethical_stances,
            "cognitive_style": self.cognitive_style,
            "reasoning_pattern": self.reasoning_pattern,
            "core_motivation": self.core_motivation,
            "avoidance_pattern": self.avoidance_pattern,
            "stress_response": self.stress_response,
            "boundaries": self.boundaries,
            "built": self.built,
            "built_at": self.built_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PersonaProfile:
        """兼容 profile.json：新六层字段 + WebUI 旧字段 background/traits/style。"""
        background_facts = d.get("background_facts")
        if background_facts is None:
            bg = d.get("background", "")
            background_facts = [bg] if bg else []

        core_traits = d.get("core_traits")
        if core_traits is None:
            core_traits = d.get("traits", [])

        cognitive_style = d.get("cognitive_style", "")
        if not cognitive_style:
            cognitive_style = d.get("style", "")

        return cls(
            name=d.get("name", "Assistant"),
            background_facts=background_facts,
            core_traits=core_traits,
            interpersonal_style=d.get("interpersonal_style", ""),
            emotional_expressiveness=d.get("emotional_expressiveness", ""),
            values=d.get("values", []),
            ethical_stances=d.get("ethical_stances", []),
            cognitive_style=cognitive_style,
            reasoning_pattern=d.get("reasoning_pattern", ""),
            core_motivation=d.get("core_motivation", ""),
            avoidance_pattern=d.get("avoidance_pattern", ""),
            stress_response=d.get("stress_response", ""),
            boundaries=d.get("boundaries", []),
            built=bool(d.get("built", False)),
            built_at=d.get("built_at", ""),
        )

    @classmethod
    def from_raw(cls, d: dict) -> PersonaProfile:
        """从 WebUI 简单格式构建未 build 的 PersonaProfile（仅填基础字段）。

        WebUI 字段：name / background / traits / values / style
        build 后的完整字段由 ProfileBuilder 填入。
        """
        raw_traits = d.get("traits", [])
        raw_values = d.get("values", [])
        return cls(
            name=d.get("name", "Assistant"),
            background_facts=[d["background"]] if d.get("background") else [],
            core_traits=raw_traits,
            values=raw_values,
            cognitive_style=d.get("style", ""),
            built=False,
        )
