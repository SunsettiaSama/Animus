from __future__ import annotations

import logging

from config.agent.persona_config import PersonaConfig
from infra.llm import BaseLLM
from agent.react.context.memory import Step
from ..persona.profile.block import ProfileBlock
from ..persona.profile.profile import PersonaProfile
from ..persona.profile.store import ProfileStore
from ..persona.status import LifeContextInput, StatusManager
from agent.react.prompt.block import PromptBlock
from agent.soul.persona.self_concept import (
    SelfConcept,
    SelfConceptBlock,
    SelfConceptEvolver,
    SelfConceptStore,
)
from agent.soul.persona.self_concept.associative import AssociativeEvolver
from agent.soul.persona.builder import ProfileBuilder

logger = logging.getLogger(__name__)


class PersonaManager:
    """Persona 子系统的统一对外接口。

    三层结构
    --------
    - 静态层（profile）    ：ProfileBuilder build 后永久只读
    - 自我认知层（self_concept）：narrative + beliefs，由心跳双链路演化
    - 动态状态层（status） ：agent 自身情绪体验，由 StatusManager 管理

    对外接口
    --------
    - all_blocks()              → 当前轮次应注入 prompt 的全部块
    - bias_query(query)         → 检索偏置（基于自我认知关键词）
    - evolve(...)               → 每轮对话后更新情绪状态
    - evolve_self_concept()     → 时间轴演进（日终心跳触发）
    - apply_associative_seeds() → 启发式演进（wander tick 触发）
    - read_state() / receive_drift() → heartbeat bridge 接口
    """

    def __init__(self, cfg: PersonaConfig, llm: BaseLLM | None = None) -> None:
        self._cfg = cfg

        # ── 静态层 ────────────────────────────────────────────────────────────
        self._profile_store = ProfileStore(cfg.persona_dir)
        self._raw_profile: PersonaProfile = self._profile_store.load_profile()
        _built: PersonaProfile | None = ProfileBuilder.load_built_profile(cfg.persona_dir)
        self._profile: PersonaProfile = _built if _built is not None else self._raw_profile

        # ── 自我认知层 ────────────────────────────────────────────────────────
        self._sc_store = SelfConceptStore(cfg.persona_dir)
        self._self_concept: SelfConcept = self._sc_store.load()
        self._sc_evolver: SelfConceptEvolver | None = (
            SelfConceptEvolver(llm) if cfg.evolution_enabled and llm is not None else None
        )
        self._assoc_evolver: AssociativeEvolver | None = (
            AssociativeEvolver(llm) if cfg.evolution_enabled and llm is not None else None
        )

        # ── 动态状态层（agent 自身情绪）─────────────────────────────────────
        # 传入 profile 引用，供 StatusSynthesizer 获取性格背景
        self._status = StatusManager(cfg.persona_dir, cfg, llm, profile=self._profile)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def profile(self) -> PersonaProfile:
        return self._profile

    @property
    def status(self) -> StatusManager:
        return self._status

    # ── Prompt blocks ──────────────────────────────────────────────────────────

    def profile_block(self) -> ProfileBlock:
        return ProfileBlock(self._profile, max_chars=self._cfg.max_profile_chars)

    def self_concept_block(self) -> SelfConceptBlock:
        return SelfConceptBlock(self._self_concept)

    def all_blocks(self) -> list[PromptBlock]:
        """当前轮次应注入 prompt 的全部 persona 块。

        顺序：静态身份 → 自我认知 → 当前情绪状态
        """
        blocks: list[PromptBlock] = [self.profile_block()]
        if not self._self_concept.is_empty():
            blocks.append(self.self_concept_block())
        if not self._status.is_empty():
            blocks.append(self._status.status_block())
        return blocks

    def bias_query(self, query: str) -> str:
        """返回附加了自我认知关键词的检索查询。"""
        sc_keywords = " ".join(self._self_concept.query_bias_keywords())
        if sc_keywords:
            return f"{query} {sc_keywords}"
        return query

    # ── 每轮演化（状态层）────────────────────────────────────────────────────

    def evolve(
        self,
        question: str,
        answer: str,
        steps: list[Step],
        life_context: LifeContextInput | None = None,
        medium_term_context: str = "",
    ) -> None:
        """每轮对话结束后：轻量缓冲交互内容，达到频率时合成 texture。

        不再每轮调用 LLM，由 StatusManager 按 update_interval 控制合成时机。
        life_context 若非空则同时推送至 life 通道（不立即触发合成，等到下次频率触发）。
        """
        self._status.record_interaction(question=question, answer=answer)
        if life_context is not None:
            self._status.receive_life_context(life_context, trigger_update=False)

    # ── SelfConcept 演化（心跳触发）──────────────────────────────────────────

    def evolve_self_concept(
        self,
        recent_anchors: list | None = None,
        recent_ruminations: list | None = None,
    ) -> bool:
        """时间轴演进：用近期情绪锚点和反刍记忆微调叙事与信念。

        由 HeartbeatModule 日终回顾后调用，返回 True 表示有实质变化并已写盘。
        """
        if self._sc_evolver is None:
            return False

        anchors = recent_anchors or list(self._status.emotional_state.anchors)
        delta = self._sc_evolver.evolve(
            concept=self._self_concept,
            built_profile=self._profile,
            recent_anchors=anchors,
            recent_ruminations=recent_ruminations or [],
        )
        if delta.is_empty():
            return False

        self._self_concept.apply_delta(delta)
        self._sc_store.save(self._self_concept)
        logger.info(
            "[SelfConcept] evolved: %d upgrades, %d adds, narrative=%s",
            len(delta.upgrades),
            len(delta.adds),
            bool(delta.narrative),
        )
        return True

    def apply_associative_seeds(self, wandered_units: list) -> bool:
        """启发式演进：从 wander() 浮现的记忆中提炼 emerging 信念种子。

        由 HeartbeatCoreService._run_wander_tick() 触发，返回 True 表示有种子写盘。
        """
        if self._assoc_evolver is None or not wandered_units:
            return False

        delta = self._assoc_evolver.evolve(
            wandered=wandered_units,
            concept=self._self_concept,
            profile=self._profile,
        )
        if delta.is_empty():
            return False

        self._self_concept.apply_delta(delta)
        self._sc_store.save(self._self_concept)
        logger.info(
            "[AssociativeEvolver] seeded %d emerging belief(s) from wander",
            len(delta.adds),
        )
        return True

    # ── Bridge: PersonaHeartbeatPort ──────────────────────────────────────────

    def read_state(self):
        """实现 PersonaHeartbeatPort.read_state()。"""
        return self._status.to_persona_snapshot()

    def receive_drift(self, signal) -> None:
        """实现 PersonaHeartbeatPort.receive_drift()。"""
        self._status.receive_signal(signal, profile=self._profile)

    # ── 重置 ──────────────────────────────────────────────────────────────────

    def clear_drift(self) -> None:
        """清除所有演化漂移状态（self_concept + status），保留静态 profile。"""
        self._sc_store.clear()
        self._self_concept = SelfConcept()
        self._status.clear()
