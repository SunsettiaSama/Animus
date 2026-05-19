from __future__ import annotations

import logging

from dataclasses import replace

from config.agent.persona_config import PersonaConfig
from config.storage import StorageConfig
from infra.llm import BaseLLM
from agent.react.context.memory import Step
from agent.soul.workers import DomainWorker
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
    ReflectionDecomposer,
    TaoReflectionSession,
)
from agent.soul.handlers.tao.handler import BaseTaoHandler
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
    - evolve_self_concept()     → 自我叙事微调（可带日终反省材料）
    - run_daily_reflection()    → 日终自我反省 + 自我叙事演进（Heartbeat 触发）
    - apply_associative_seeds() → 启发式演进（wander tick 触发）
    - read_state() / receive_drift() → heartbeat bridge 接口
    """

    def __init__(
        self,
        cfg: PersonaConfig,
        llm: BaseLLM | None = None,
        tao_handler: BaseTaoHandler | None = None,
    ) -> None:
        self._cfg = cfg
        self._tao_handler = tao_handler
        self._worker: DomainWorker | None = None

        _storage = StorageConfig()
        _persona_dir = _storage.resolve_persona_dir(cfg.persona_dir)
        if _persona_dir != cfg.persona_dir:
            cfg = replace(cfg, persona_dir=_persona_dir)
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

    def set_tao_handler(self, handler: BaseTaoHandler | None) -> None:
        self._tao_handler = handler

    def set_worker(self, worker: DomainWorker | None) -> None:
        self._worker = worker

    def _enqueue_write(self, fn) -> None:
        if self._worker is not None:
            self._worker.enqueue(fn)
        else:
            fn()

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

    def snapshot(self) -> dict:
        """对外只读快照：静态画像 + 自我叙事 + 情绪状态。"""
        return {
            "profile": self._profile.to_dict(),
            "self_concept": self._self_concept.to_dict(),
            "status": self._status.emotional_state.to_dict(),
            "attention_keywords": self.read_state().attention_keywords,
        }

    def portrait_revision(self) -> str:
        """Life 叙事引擎用：轻量版本指纹，画像未变时可跳过全量拉取。"""
        emotional = self._status.emotional_state
        profile_tag = self._profile.built_at or f"raw:{self._profile.name}"
        return f"{profile_tag}|{self._self_concept.updated_at}|{emotional.updated_at}"

    def portrait_for_narrative(
        self,
        max_chars: int = 1200,
        *,
        compact: bool = False,
    ) -> str:
        """Life 叙事引擎用：compact=填充实况；完整版=规划地标。"""
        if compact:
            parts: list[str] = []
            narrative = self._self_concept.narrative.strip()
            if narrative:
                parts.append(narrative)
            texture = self._status.emotional_state.texture.strip()
            if texture:
                parts.append(texture)
            text = "\n\n".join(parts)
            if not text:
                text = self._profile.render()
        else:
            trait_hint = ""
            if self._profile.core_traits:
                trait_hint = "、".join(self._profile.core_traits[:4])
            head = f"【{self._profile.name}】"
            if trait_hint:
                head += f" {trait_hint}"
            parts = [head]
            narrative = self._self_concept.narrative.strip()
            if narrative:
                parts.append(narrative)
            texture = self._status.emotional_state.texture.strip()
            if texture:
                parts.append(texture)
            text = "\n\n".join(parts)
        if max_chars > 0 and len(text) > max_chars:
            text = text[-max_chars:]
        return text

    # ── 每轮演化（状态层）────────────────────────────────────────────────────

    def evolve(
        self,
        question: str,
        answer: str,
        steps: list[Step],
        *,
        life_context: LifeContextInput | None = None,
        medium_term_context: str = "",
    ) -> None:
        """每轮对话结束后：status 层演化（交互缓冲 + life 事实背景 + MTM）。"""
        self._enqueue_write(lambda: self._evolve_impl(
            question, answer, steps,
            life_context=life_context,
            medium_term_context=medium_term_context,
        ))

    def _evolve_impl(
        self,
        question: str,
        answer: str,
        steps: list[Step],
        *,
        life_context: LifeContextInput | None = None,
        medium_term_context: str = "",
    ) -> None:
        self._status.record_interaction(
            question=question,
            answer=answer,
            medium_term_context=medium_term_context,
        )
        if life_context is not None and not life_context.is_empty():
            self._status.receive_life_context(life_context, trigger_update=False)

    # ── SelfConcept 演化（心跳触发）──────────────────────────────────────────

    def evolve_self_concept(
        self,
        recent_anchors: list | None = None,
        recent_ruminations: list | None = None,
        daily_reflection=None,
    ) -> bool:
        """时间轴演进：用近期情绪锚点、反刍记忆与日终反省微调叙事与信念。"""
        if self._worker is not None:
            future = self._worker.submit(lambda: self._evolve_self_concept_impl(
                recent_anchors=recent_anchors,
                recent_ruminations=recent_ruminations,
                daily_reflection=daily_reflection,
            ))
            return bool(future.result())
        return self._evolve_self_concept_impl(
            recent_anchors=recent_anchors,
            recent_ruminations=recent_ruminations,
            daily_reflection=daily_reflection,
        )

    def _evolve_self_concept_impl(
        self,
        recent_anchors: list | None = None,
        recent_ruminations: list | None = None,
        daily_reflection=None,
    ) -> bool:
        if self._sc_evolver is None:
            return False

        anchors = recent_anchors or list(self._status.emotional_state.anchors)
        delta = self._sc_evolver.evolve(
            concept=self._self_concept,
            built_profile=self._profile,
            recent_anchors=anchors,
            recent_ruminations=recent_ruminations or [],
            daily_reflection=daily_reflection,
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

    def run_daily_reflection(
        self,
        today_dialogue: str = "",
        today_scheduler_tasks: str = "",
    ) -> dict:
        """日终自我反省：经 Base Tao 完整推理，拆解后驱动 self_concept 演进。"""
        if self._worker is not None:
            return self._worker.submit(lambda: self._run_daily_reflection_impl(
                today_dialogue=today_dialogue,
                today_scheduler_tasks=today_scheduler_tasks,
            )).result()
        return self._run_daily_reflection_impl(
            today_dialogue=today_dialogue,
            today_scheduler_tasks=today_scheduler_tasks,
        )

    def _run_daily_reflection_impl(
        self,
        today_dialogue: str = "",
        today_scheduler_tasks: str = "",
    ) -> dict:
        if self._tao_handler is None:
            return {"ok": False, "reason": "no tao service"}

        request = TaoReflectionSession.build_request(
            profile=self._profile,
            concept=self._self_concept,
            today_dialogue=today_dialogue,
            today_scheduler_tasks=today_scheduler_tasks,
            recent_anchors=list(self._status.emotional_state.anchors),
        )
        tao_result = self._tao_handler.run(request)
        reflection = ReflectionDecomposer.decompose(tao_result)

        if self._sc_evolver is None:
            return {
                "ok": True,
                "tao_steps": tao_result.step_count,
                "thought_records": len(reflection.thought_records),
                "reflective_note": bool(reflection.reflective_note.strip()),
                "self_concept_changed": False,
                "reason": "evolution disabled",
            }

        changed = self._evolve_self_concept_impl(daily_reflection=reflection)
        return {
            "ok": True,
            "tao_steps": tao_result.step_count,
            "thought_records": len(reflection.thought_records),
            "reflective_note": bool(reflection.reflective_note.strip()),
            "self_concept_changed": changed,
        }

    def apply_associative_seeds(self, wandered_units: list) -> bool:
        """启发式演进：从 wander() 浮现的记忆中提炼 emerging 信念种子。"""
        if self._worker is not None:
            future = self._worker.submit(
                lambda: self._apply_associative_seeds_impl(wandered_units)
            )
            return bool(future.result())
        return self._apply_associative_seeds_impl(wandered_units)

    def _apply_associative_seeds_impl(self, wandered_units: list) -> bool:
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
        snap = self._status.to_persona_snapshot()
        extra_kw = self._self_concept.query_bias_keywords()
        merged = list(dict.fromkeys([*snap.attention_keywords, *extra_kw]))[:20]
        return replace(snap, attention_keywords=merged)

    def receive_drift(self, signal) -> None:
        """实现 PersonaHeartbeatPort.receive_drift()。"""
        self._enqueue_write(lambda: self._status.receive_signal(signal, profile=self._profile))

    def apply_wander_result(self, result, floor: float) -> None:
        """Wander pipeline 人格侧效应；须在 persona-worker 线程内执行。"""
        if result.signal.intensity > floor:
            self._status.receive_signal(result.signal, profile=self._profile)
        if result.wandered_units:
            self._apply_associative_seeds_impl(result.wandered_units)

    # ── 重置 ──────────────────────────────────────────────────────────────────

    def clear_drift(self) -> None:
        """清除所有演化漂移状态（self_concept + status），保留静态 profile。"""
        self._enqueue_write(self._clear_drift_impl)

    def _clear_drift_impl(self) -> None:
        self._sc_store.clear()
        self._self_concept = SelfConcept()
        self._status.clear()
