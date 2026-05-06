from __future__ import annotations

from infra.llm import BaseLLM
from ..memory.memory import Step
from ..persona.profile.evolver import PersonaEvolver, ProfileDelta
from ..persona.profile.profile import PersonaProfile
from ..persona.profile.skills import Skill, SkillsLibrary
from ..persona.profile.store import ProfileStore


class EvolutionEngine:
    """摘要-写入-注入 循环的顶层调度器。

    每轮对话结束后由 PersonaManager.evolve() 调用，执行以下步骤：

    1. 【profile】   每 evolve_interval 轮用 LLM 分析交互，生成 ProfileDelta 并写入
    2. 【skills】    每 evolve_interval 轮用 LLM 更新技能库（与 profile 同周期）
    3. 【reflect】   每 reflect_interval 轮用 LLM 生成第一人称自省摘要

    所有 LLM 调用均为阻塞式，但 EvolutionEngine 应在后台线程中运行（由
    TaoLoop.post_process 保证），不影响用户侧响应。
    """

    def __init__(
        self,
        llm: BaseLLM,
        profile_store: ProfileStore,
        evolve_interval: int = 1,
        skills_enabled: bool = True,
        reflection_enabled: bool = False,
        reflect_interval: int = 3,
    ) -> None:
        self._evolver = PersonaEvolver(llm)
        self._profile_store = profile_store
        self._evolve_interval = max(1, evolve_interval)
        self._skills_enabled = skills_enabled
        self._reflection_enabled = reflection_enabled
        self._reflect_interval = max(1, reflect_interval)

    def run(
        self,
        question: str,
        answer: str,
        steps: list[Step],
        profile: PersonaProfile,
        skills: SkillsLibrary,
        turn_count: int,
    ) -> str | None:
        """执行一轮演化。返回新的自省文本（若本轮触发了自省），否则返回 None。"""
        # 1. Profile + Skills evolution — LLM（每 evolve_interval 轮触发）
        if turn_count % self._evolve_interval == 0:
            delta = self._evolver.evolve_profile(profile, question, answer, steps)
            _apply_profile_delta(profile, delta)
            self._profile_store.save_profile(profile)

            if self._skills_enabled:
                skill_delta = self._evolver.evolve_skills(
                    profile, skills, question, answer, steps
                )
                _apply_skill_delta(skills, skill_delta)
                self._profile_store.save_skills(skills)

        # 2. Self-reflection — LLM（每 reflect_interval 轮触发）
        new_reflection: str | None = None
        if self._reflection_enabled and turn_count % self._reflect_interval == 0:
            new_reflection = self._evolver.reflect(profile, skills)
            if new_reflection:
                self._profile_store.save_reflection(new_reflection)

        return new_reflection


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _apply_profile_delta(profile: PersonaProfile, delta: ProfileDelta) -> None:
    for t in delta.traits_add:
        if t and t not in profile.traits:
            profile.traits.append(t)
    profile.traits = [t for t in profile.traits if t not in delta.traits_remove]
    for v in delta.values_add:
        if v and v not in profile.values:
            profile.values.append(v)
    profile.values = [v for v in profile.values if v not in delta.values_remove]
    if delta.style_hint:
        profile.style = delta.style_hint


def _apply_skill_delta(skills: SkillsLibrary, delta) -> None:
    for item in delta.add:
        name = item.get("name", "").strip()
        if not name:
            continue
        skills.add(Skill(
            name=name,
            description=item.get("description", ""),
            trigger=item.get("trigger", ""),
            priority=int(item.get("priority", 5)),
        ))
    for item in delta.update:
        name = item.get("name", "").strip()
        if not name:
            continue
        skills.update_skill(name, **{k: v for k, v in item.items() if k != "name"})
    for name in delta.remove:
        if name:
            skills.remove(name)
