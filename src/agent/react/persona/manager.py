from __future__ import annotations

from config.agent.persona_config import PersonaConfig
from llm_core.llm import BaseLLM
from ..memory.memory import Step
from ..persona.engine import EvolutionEngine
from ..persona.preference.block import PreferenceBlock
from ..persona.preference.recent import RecentPreference
from ..persona.preference.store import PreferenceStore
from ..persona.preference.updater import PreferenceUpdater
from ..persona.profile.block import ProfileBlock, ReflectionBlock, SkillsBlock
from ..persona.profile.evolver import PersonaEvolver
from ..persona.profile.profile import PersonaProfile
from ..persona.profile.skills import SkillsLibrary
from ..persona.profile.store import ProfileStore
from ..prompt.block import PromptBlock


class PersonaManager:
    """Persona 子系统的统一入口。

    协调 profile/ preference/ 两个子模块，对外提供：
    - 各类 PromptBlock（供 TaoLoop 注入 system prompt）
    - evolve()（每轮对话结束后驱动演化引擎）
    """

    def __init__(self, cfg: PersonaConfig, llm: BaseLLM | None = None) -> None:
        self._cfg = cfg

        # ── 存储层 ────────────────────────────────────────────────────────────
        self._profile_store = ProfileStore(cfg.persona_dir)
        self._preference_store = PreferenceStore(cfg.persona_dir)

        # ── 数据层 ────────────────────────────────────────────────────────────
        self._profile: PersonaProfile = self._profile_store.load_profile()
        self._skills: SkillsLibrary = (
            self._profile_store.load_skills(cfg.max_skills)
            if cfg.skills_enabled
            else SkillsLibrary()
        )
        self._reflection: str = (
            self._profile_store.load_reflection() if cfg.reflection_enabled else ""
        )
        self._turn_count: int = 0

        # ── 演化引擎（需 LLM + evolution_enabled）────────────────────────────
        self._engine: EvolutionEngine | None = (
            EvolutionEngine(
                llm=llm,
                profile_store=self._profile_store,
                evolve_interval=cfg.evolve_interval,
                skills_enabled=cfg.skills_enabled,
                reflection_enabled=cfg.reflection_enabled,
                reflect_interval=cfg.reflect_interval,
            )
            if cfg.evolution_enabled and llm is not None
            else None
        )

        # ── 近期偏好（动态层，持久化到 preference.json）───────────────────────
        self._recent_preference: RecentPreference = (
            self._preference_store.load(
                window_days=cfg.preference_window_days,
                max_topics=cfg.max_preference_topics,
            )
            if cfg.preference_enabled
            else RecentPreference(
                window_days=cfg.preference_window_days,
                max_topics=cfg.max_preference_topics,
            )
        )
        self._preference_updater: PreferenceUpdater | None = (
            PreferenceUpdater(llm)
            if cfg.preference_enabled and llm is not None
            else None
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def profile(self) -> PersonaProfile:
        return self._profile

    @property
    def skills(self) -> SkillsLibrary:
        return self._skills

    @property
    def reflection(self) -> str:
        return self._reflection

    @property
    def recent_preference(self) -> RecentPreference:
        return self._recent_preference

    # ── Prompt blocks ──────────────────────────────────────────────────────────

    def profile_block(self) -> ProfileBlock:
        return ProfileBlock(self._profile, max_chars=self._cfg.max_profile_chars)

    def skills_block(self) -> SkillsBlock:
        return SkillsBlock(
            self._skills,
            top_k=self._cfg.max_skills_in_prompt,
            max_chars=self._cfg.max_skills_chars,
        )

    def reflection_block(self) -> ReflectionBlock:
        return ReflectionBlock(self._reflection, max_chars=self._cfg.max_reflection_chars)

    def preference_block(self) -> PreferenceBlock:
        return PreferenceBlock(
            self._recent_preference,
            max_chars=self._cfg.max_preference_chars,
        )

    def all_blocks(self) -> list[PromptBlock]:
        """返回本轮应注入 Prompt 的全部 persona 块。"""
        blocks: list[PromptBlock] = [self.profile_block()]
        if self._cfg.skills_enabled:
            blocks.append(self.skills_block())
        if self._cfg.reflection_enabled and self._reflection:
            blocks.append(self.reflection_block())
        if self._cfg.preference_enabled and self._recent_preference.render():
            blocks.append(self.preference_block())
        return blocks

    def bias_query(self, query: str) -> str:
        """Return query augmented with recent topic interests for biased L3 retrieval."""
        bias = self._recent_preference.to_query_bias()
        if not bias:
            return query
        return f"{query} {bias}"

    # ── Evolution ──────────────────────────────────────────────────────────────

    def evolve(self, question: str, answer: str, steps: list[Step]) -> None:
        """每轮对话结束后调用，驱动演化引擎并更新内部状态。"""
        self._turn_count += 1

        if self._engine is not None:
            new_reflection = self._engine.run(
                question=question,
                answer=answer,
                steps=steps,
                profile=self._profile,
                skills=self._skills,
                turn_count=self._turn_count,
            )
            if new_reflection is not None:
                self._reflection = new_reflection

        # 近期偏好更新（每 N 轮触发一次）
        if (
            self._preference_updater is not None
            and self._turn_count % self._cfg.preference_update_every_n == 0
        ):
            self._recent_preference = self._preference_updater.update(
                self._recent_preference, question, answer
            )
            self._preference_store.save(self._recent_preference)

    def save_profile(self) -> None:
        self._profile_store.save_profile(self._profile)

    def clear_drift(self) -> None:
        """删除所有演化漂移文件（profile/skills/reflection/preference），并重置内存状态。

        不删除 persona_config.json（用户手动配置的基础人格设定）。
        """
        import os
        store = self._profile_store
        pref_store = self._preference_store

        for path in (
            store._profile_path,
            store._skills_path,
            store._reflection_path,
        ):
            if path.exists():
                os.remove(path)

        pref_path = pref_store._path
        if os.path.exists(pref_path):
            os.remove(pref_path)

        # Reset in-memory objects
        from ..persona.profile.profile import PersonaProfile
        from ..persona.profile.skills import SkillsLibrary
        from ..persona.preference.recent import RecentPreference

        self._profile = PersonaProfile()
        self._skills = SkillsLibrary()
        self._reflection = ""
        self._recent_preference = RecentPreference(
            window_days=self._cfg.preference_window_days,
            max_topics=self._cfg.max_preference_topics,
        )
        self._turn_count = 0
