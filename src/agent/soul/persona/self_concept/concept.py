from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_CORE_CHALLENGE_THRESHOLD = 3   # core 信念被挑战几次后才真正降级
_MAX_EMERGING_BELIEFS = 8       # emerging 信念上限，超出时淘汰最早的


# ── BeliefStrength ────────────────────────────────────────────────────────────

class BeliefStrength(str, Enum):
    """信念确认度——分级而非浮点，避免假精度。

    emerging     刚出现，基于 1~2 次经验，随时可能消失
    established  多次验证，成为相对稳定的自我认知
    core         深度认同，形成人格底色，极少改变
    """
    emerging    = "emerging"
    established = "established"
    core        = "core"

    @staticmethod
    def order() -> dict[str, int]:
        return {"emerging": 0, "established": 1, "core": 2}

    def rank(self) -> int:
        return BeliefStrength.order()[self.value]

    @classmethod
    def from_str(cls, s: str) -> BeliefStrength:
        try:
            return cls(s.strip().lower())
        except ValueError:
            return cls.emerging

    def can_upgrade_to(self, target: BeliefStrength) -> bool:
        return target.rank() == self.rank() + 1

    def upgraded(self) -> BeliefStrength:
        if self == BeliefStrength.core:
            return self
        ranks = {0: BeliefStrength.emerging, 1: BeliefStrength.established, 2: BeliefStrength.core}
        return ranks[self.rank() + 1]

    def downgraded(self) -> BeliefStrength:
        if self == BeliefStrength.emerging:
            return self
        ranks = {0: BeliefStrength.emerging, 1: BeliefStrength.established, 2: BeliefStrength.core}
        return ranks[self.rank() - 1]


# ── Belief ────────────────────────────────────────────────────────────────────

@dataclass
class Belief:
    """一条自我信念。

    content    — 第二人称陈述（面向角色 LLM），如"你擅长分解复杂问题"
    strength   — BeliefStrength 枚举：emerging / established / core
    source     — 来源标记："build"（初始）| "evolver"（演化产生）
    updated_at — 最近一次调整的 UTC 时间
    id         — 唯一标识（仅内部使用，不暴露给 LLM）
    """
    content: str
    strength: BeliefStrength
    source: str = "build"
    updated_at: str = field(default_factory=_now_iso)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    challenge_count: int = 0   # 仅 core 信念使用：积累挑战次数，达阈值才降级

    def matches(self, keyword: str) -> bool:
        """宽松内容匹配：keyword 是否是 content 的子串（双向）。"""
        kw = keyword.strip().lower()
        ct = self.content.strip().lower()
        return kw in ct or ct in kw

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "strength": self.strength.value,
            "source": self.source,
            "updated_at": self.updated_at,
            "challenge_count": self.challenge_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Belief:
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            content=d.get("content", ""),
            strength=BeliefStrength.from_str(d.get("strength", "emerging")),
            source=d.get("source", "build"),
            updated_at=d.get("updated_at", _now_iso()),
            challenge_count=int(d.get("challenge_count", 0)),
        )


# ── Delta ─────────────────────────────────────────────────────────────────────

@dataclass
class SelfConceptDelta:
    """SelfConceptEvolver 的计算产出，传给 SelfConcept.apply_delta()。

    narrative  — 新叙事摘要（主输出）；空字符串表示本次不更新
    upgrades   — 信念升级：{"match": "关键词", "to": "established"}
                 match 用于在现有 beliefs 中做内容匹配，无需 ID
    adds       — 新增信念：{"content": "你...", "strength": "emerging"}
    removes    — 待移除信念的关键词列表（内容匹配）
    """
    narrative: str = ""
    upgrades: list[dict] = field(default_factory=list)
    adds: list[dict] = field(default_factory=list)
    removes: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return (
            not self.narrative
            and not self.upgrades
            and not self.adds
            and not self.removes
        )


# ── SelfConcept ───────────────────────────────────────────────────────────────

class SelfConcept:
    """结构化自传：叙事摘要（主体）+ 信念索引（派生）。

    设计原则
    --------
    - narrative 是第一公民：人类通过叙事认识自己，信念是从叙事中提炼的索引
    - apply_delta() 使用内容语义匹配，不依赖 UUID
    - 不持有任何调度/时间逻辑
    """

    def __init__(
        self,
        beliefs: list[Belief] | None = None,
        narrative: str = "",
        updated_at: str = "",
    ) -> None:
        self._beliefs: list[Belief] = beliefs or []
        self._narrative: str = narrative
        self._updated_at: str = updated_at or _now_iso()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def beliefs(self) -> list[Belief]:
        return list(self._beliefs)

    @property
    def narrative(self) -> str:
        return self._narrative

    @property
    def updated_at(self) -> str:
        return self._updated_at

    def is_empty(self) -> bool:
        return not self._beliefs and not self._narrative

    # ── Apply delta ───────────────────────────────────────────────────────────

    def apply_delta(self, delta: SelfConceptDelta) -> None:
        """将外部计算好的 delta 应用到当前状态。

        匹配策略：内容关键词匹配，而非 UUID 匹配。
        同一内容关键词最多匹配第一条命中的信念，避免批量误改。
        """
        if delta.is_empty():
            return

        now = _now_iso()

        # 1. 更新叙事（主体）
        if delta.narrative.strip():
            self._narrative = delta.narrative.strip()

        # 2. 升级已有信念
        for upg in delta.upgrades:
            match_kw = upg.get("match", "").strip()
            target_str = upg.get("to", "")
            if not match_kw or not target_str:
                continue
            target = BeliefStrength.from_str(target_str)
            belief = self._find_first(match_kw)
            # 只允许单步升级，Python 层兜底，不信任 LLM 自我约束
            if belief is not None and target.rank() == belief.strength.rank() + 1:
                belief.strength = target
                belief.updated_at = now

        # 3. 降级或移除
        for rm_kw in delta.removes:
            belief = self._find_strongest(rm_kw)
            if belief is None:
                continue
            if belief.strength == BeliefStrength.core:
                # core 不直接降级：积累挑战次数，达阈值后才松动
                belief.challenge_count += 1
                belief.updated_at = now
                if belief.challenge_count >= _CORE_CHALLENGE_THRESHOLD:
                    belief.strength = BeliefStrength.established
                    belief.challenge_count = 0
                    belief.updated_at = now
            elif belief.strength == BeliefStrength.emerging:
                self._beliefs = [b for b in self._beliefs if b.id != belief.id]
            else:
                belief.strength = belief.strength.downgraded()
                belief.updated_at = now

        # 4. 新增信念（跳过语义重复的；emerging 数量超上限时淘汰最早的）
        for add in delta.adds:
            content = add.get("content", "").strip()
            if not content:
                continue
            if self._find_first(content) is not None:
                continue  # 已存在语义相近的信念，跳过
            strength = BeliefStrength.from_str(add.get("strength", "emerging"))
            self._beliefs.append(Belief(
                content=content,
                strength=strength,
                source="evolver",
                updated_at=now,
            ))
            # emerging 信念超出上限时，淘汰最早更新的那条
            emerging = [b for b in self._beliefs if b.strength == BeliefStrength.emerging]
            if len(emerging) > _MAX_EMERGING_BELIEFS:
                oldest = min(emerging, key=lambda b: b.updated_at)
                self._beliefs = [b for b in self._beliefs if b.id != oldest.id]

        self._updated_at = now

    def _find_first(self, keyword: str) -> Belief | None:
        """内容匹配，多条命中时：
        - 用于 upgrades → 取强度最低的（最保守，避免跳级）
        - 用于 removes  → 取强度最高的（先降最稳固的）
        默认返回强度最低的，调用方可按需覆盖。
        """
        matched = [b for b in self._beliefs if b.matches(keyword)]
        if not matched:
            return None
        return min(matched, key=lambda b: b.strength.rank())

    def _find_strongest(self, keyword: str) -> Belief | None:
        matched = [b for b in self._beliefs if b.matches(keyword)]
        if not matched:
            return None
        return max(matched, key=lambda b: b.strength.rank())

    # ── Query helpers ─────────────────────────────────────────────────────────

    def top_beliefs(
        self,
        k: int = 3,
        min_strength: BeliefStrength = BeliefStrength.emerging,
    ) -> list[Belief]:
        """按强度降序返回前 k 条，过滤低于 min_strength 的条目。"""
        filtered = [b for b in self._beliefs if b.strength.rank() >= min_strength.rank()]
        return sorted(filtered, key=lambda b: b.strength.rank(), reverse=True)[:k]

    def query_bias_keywords(self) -> list[str]:
        """提取 established 及以上信念的内容，用于记忆检索偏置。"""
        return [
            b.content for b in self.top_beliefs(k=2, min_strength=BeliefStrength.established)
        ]

    def render_for_role_llm(
        self,
        *,
        top_k: int = 3,
        min_strength: BeliefStrength = BeliefStrength.established,
        warn_main_portrait: bool = False,
        caller: str = "",
    ) -> str:
        """面向角色 LLM 的自叙正文：第二人称「你」。"""
        if self.is_empty():
            return ""
        if warn_main_portrait:
            from agent.soul.persona.portrait import warn_main_portrait_usage

            warn_main_portrait_usage(caller or "SelfConcept.render_for_role_llm")

        parts: list[str] = ["【你的自我认知】"]
        if self._narrative.strip():
            narrative = self._narrative.strip()
            if narrative.startswith("我"):
                narrative = "你" + narrative[1:]
            parts.append(narrative)

        grouped: dict[str, list[str]] = {
            BeliefStrength.core.value: [],
            BeliefStrength.established.value: [],
            BeliefStrength.emerging.value: [],
        }
        for belief in self.top_beliefs(k=top_k * 2, min_strength=min_strength):
            text = belief.content.strip()
            if text.startswith("我"):
                text = "你" + text[1:]
            grouped[belief.strength.value].append(text)

        if grouped[BeliefStrength.core.value]:
            parts.append("你的核心信念：")
            parts.extend(f"- {text}" for text in grouped[BeliefStrength.core.value][:top_k] if text)
        if grouped[BeliefStrength.established.value]:
            parts.append("你已确立的信念：")
            parts.extend(
                f"- {text}"
                for text in grouped[BeliefStrength.established.value][:top_k]
                if text
            )
        emerging = grouped[BeliefStrength.emerging.value][:top_k]
        if emerging:
            parts.append("你正在形成的认识：")
            parts.extend(f"- {text}" for text in emerging if text)

        return "\n".join(parts)

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "beliefs": [b.to_dict() for b in self._beliefs],
            "narrative": self._narrative,
            "updated_at": self._updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SelfConcept:
        return cls(
            beliefs=[Belief.from_dict(b) for b in d.get("beliefs", [])],
            narrative=d.get("narrative", ""),
            updated_at=d.get("updated_at", ""),
        )
