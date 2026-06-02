from __future__ import annotations

import logging
from dataclasses import replace

from config.agent.persona_config import PersonaConfig
from config.storage import StorageConfig
from infra.llm import BaseLLM
from agent.react.prompt.block import PromptBlock
from agent.soul.workers import DomainWorker

from .profile.block import ProfileBlock
from .profile.profile import PersonaProfile
from .profile.store import ProfileStore
from .builder import ProfileBuilder
from .buffer import (
    BufferMeta,
    ClusterSignal,
    EmbedderBackend,
    ExperienceBuffer,
    ExperienceBufferStore,
    MemoryDriftUnitPort,
    MonthlyDriftUpdater,
    current_month,
)
from .self_concept import SelfConcept, SelfConceptBlock, SelfConceptStore
from .distill import DistillEnsureResult, PersonaDistillPack, ensure_distill

logger = logging.getLogger(__name__)


class PersonaManager:
    """Persona 子系统：profile + buffer + self_concept。

    - profile：静态画像
    - buffer：聚类主题元数据（月度 self_concept 漂移调度）
    - self_concept：慢变自我叙事（build 初始化；**仅**月度漂移写入）

    快变情绪状态在 ``PresenceState.affect``。
    """

    def __init__(
        self,
        cfg: PersonaConfig,
        llm: BaseLLM | None = None,
    ) -> None:
        self._cfg = cfg
        self._worker: DomainWorker | None = None
        self._llm = llm

        _storage = StorageConfig()
        _persona_dir = _storage.resolve_persona_dir(cfg.persona_dir)
        if _persona_dir != cfg.persona_dir:
            cfg = replace(cfg, persona_dir=_persona_dir)
            self._cfg = cfg

        self._profile_store = ProfileStore(cfg.persona_dir)
        self._raw_profile: PersonaProfile = self._profile_store.load_profile()
        _built: PersonaProfile | None = ProfileBuilder.load_built_profile(cfg.persona_dir)
        self._profile: PersonaProfile = _built if _built is not None else self._raw_profile

        self._sc_store = SelfConceptStore(cfg.persona_dir)
        self._self_concept: SelfConcept = self._sc_store.load()

        self._buffer_store = ExperienceBufferStore(cfg.persona_dir)
        _buffer_state = self._buffer_store.load_state()
        self._buffer: ExperienceBuffer = _buffer_state.buffer
        self._buffer_meta: BufferMeta = _buffer_state.meta
        self._drift_updater = MonthlyDriftUpdater()
        self._memory_port: MemoryDriftUnitPort | None = None
        self._embedder: EmbedderBackend | None = None
        self._distill_pack: PersonaDistillPack | None = None

    @property
    def profile(self) -> PersonaProfile:
        return self._profile

    @property
    def buffer(self) -> ExperienceBuffer:
        return self._buffer

    @property
    def self_concept(self) -> SelfConcept:
        return self._self_concept

    @property
    def buffer_meta(self) -> BufferMeta:
        return self._buffer_meta

    def set_worker(self, worker: DomainWorker | None) -> None:
        self._worker = worker

    def set_memory_port(self, port: MemoryDriftUnitPort | None) -> None:
        self._memory_port = port

    def set_embedder(self, embedder: EmbedderBackend | None) -> None:
        self._embedder = embedder

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
        blocks: list[PromptBlock] = [self.profile_block()]
        if not self._self_concept.is_empty():
            blocks.append(self.self_concept_block())
        return blocks

    def bias_query(self, query: str) -> str:
        sc_keywords = " ".join(self._self_concept.query_bias_keywords())
        if sc_keywords:
            return f"{query} {sc_keywords}"
        return query

    def ensure_distill(self, *, force: bool = False) -> DistillEnsureResult:
        if self._worker is not None:
            return self._worker.submit(
                lambda: self._ensure_distill_impl(force=force)
            ).result()
        return self._ensure_distill_impl(force=force)

    def _ensure_distill_impl(self, *, force: bool = False) -> DistillEnsureResult:
        result = ensure_distill(
            persona_dir=self._cfg.persona_dir,
            profile=self._profile,
            self_concept=self._self_concept,
            attention_keywords=self._self_concept.query_bias_keywords(),
            source_revision=self.portrait_revision(),
            llm=self._llm,
            force=force,
        )
        self._distill_pack = result.pack
        return result

    def snapshot(self) -> dict:
        distill_result = self._ensure_distill_impl()
        data = {
            "profile": self._profile.to_dict(),
            "buffer": {
                **self._buffer.summary(),
                "last_drift_at": self._buffer_meta.last_drift_at,
                "last_drift_month": self._buffer_meta.last_drift_month,
            },
            "self_concept": self._self_concept.to_dict(),
            "attention_keywords": self._self_concept.query_bias_keywords(),
        }
        if distill_result.pack is not None:
            data["persona_distill"] = distill_result.pack.to_dict()
        return data

    def buffer_snapshot(self, *, include_signals: bool = False) -> dict:
        data = self.snapshot()["buffer"]
        if include_signals:
            detail = self._buffer.snapshot(include_signals=True)
            data["signals"] = detail["signals"]
        return data

    def record_cluster_signals(self, payloads: list[dict]) -> dict:
        """Memory.persona_clusters 元数据写入 buffer（唯一注入入口）。"""
        if self._worker is not None:
            return self._worker.submit(
                lambda: self._record_cluster_signals_impl(payloads)
            ).result()
        return self._record_cluster_signals_impl(payloads)

    def _record_cluster_signals_impl(self, payloads: list[dict]) -> dict:
        signal_ids: list[str] = []
        for payload in payloads:
            signal = ClusterSignal.from_cluster_meta(payload)
            self._buffer.append(signal)
            self._buffer_store.append(signal)
            signal_ids.append(signal.id)
        return {
            "ok": True,
            "applied": len(signal_ids),
            "signal_ids": signal_ids,
            "buffer": self.buffer_snapshot(),
        }

    def run_monthly_drift(self, *, force: bool = False, month: str = "") -> dict:
        """唯一 self_concept 漂移：buffer 主题 → Memory 回查 → 整合写回。"""
        if self._worker is not None:
            return self._worker.submit(
                lambda: self._run_monthly_drift_impl(force=force, month=month)
            ).result()
        return self._run_monthly_drift_impl(force=force, month=month)

    def _run_monthly_drift_impl(self, *, force: bool, month: str) -> dict:
        target_month = month or current_month()
        result = self._drift_updater.run(
            buffer=self._buffer,
            meta=self._buffer_meta,
            concept=self._self_concept,
            profile=self._profile,
            memory_port=self._memory_port,
            embedder=self._embedder,
            llm=self._llm,
            month=target_month,
            force=force,
        )
        detail = dict(result.detail)
        detail["buffer"] = self.buffer_snapshot()
        if result.plan is not None:
            apply_result = self._apply_self_concept_delta_impl(result.plan.delta)
            detail["self_concept"] = apply_result
            marked = self._buffer.mark_consolidated(result.plan.signal_ids)
            self._buffer_store.save(self._buffer)
            self._buffer_meta = self._buffer_store.touch_drift_run(target_month)
            detail["marked"] = marked
        return {
            "ok": result.ok,
            "applied": result.applied,
            "reason": result.reason,
            **detail,
        }

    def apply_self_concept_delta(self, delta) -> dict:
        """内部：月度漂移完成后写回 self_concept。"""
        if self._worker is not None:
            return self._worker.submit(
                lambda: self._apply_self_concept_delta_impl(delta)
            ).result()
        return self._apply_self_concept_delta_impl(delta)

    def _apply_self_concept_delta_impl(self, delta) -> dict:
        from .self_concept.concept import SelfConceptDelta

        if not isinstance(delta, SelfConceptDelta):
            raise TypeError("delta must be SelfConceptDelta")
        if delta.is_empty():
            return {"ok": True, "applied": False, "reason": "empty_delta"}
        self._self_concept.apply_delta(delta)
        self._sc_store.save(self._self_concept)
        distill = self._ensure_distill_impl()
        return {
            "ok": True,
            "applied": True,
            "reason": "self_concept_drifted",
            "portrait_revision": self.portrait_revision(),
            "persona_distill_refreshed": distill.refreshed,
            "persona_distill_reason": distill.reason,
        }

    def _clear_buffer_impl(self) -> None:
        self._buffer.clear()
        self._buffer_store.clear()

    def portrait_revision(self) -> str:
        profile_tag = self._profile.built_at or f"raw:{self._profile.name}"
        return f"{profile_tag}|{self._self_concept.updated_at}"

    def reload_profile(self) -> dict:
        if self._worker is not None:
            return self._worker.submit(self._reload_profile_impl).result()
        return self._reload_profile_impl()

    def _reload_profile_impl(self) -> dict:
        self._raw_profile = self._profile_store.load_profile()
        built = ProfileBuilder.load_built_profile(self._cfg.persona_dir)
        self._profile = built if built is not None else self._raw_profile
        self._self_concept = self._sc_store.load()
        _buffer_state = self._buffer_store.load_state()
        self._buffer = _buffer_state.buffer
        self._buffer_meta = _buffer_state.meta
        distill = self._ensure_distill_impl()
        return {
            "ok": True,
            "applied": True,
            "reason": "reload_profile",
            "profile_source": "built" if built is not None else "raw",
            "portrait_revision": self.portrait_revision(),
            "persona_distill_refreshed": distill.refreshed,
            "persona_distill_reason": distill.reason,
        }

    def rebuild_profile(self, *, preserve_self_concept: bool = False) -> dict:
        if self._worker is not None:
            return self._worker.submit(
                lambda: self._rebuild_profile_impl(
                    preserve_self_concept=preserve_self_concept,
                )
            ).result()
        return self._rebuild_profile_impl(preserve_self_concept=preserve_self_concept)

    def _rebuild_profile_impl(self, *, preserve_self_concept: bool) -> dict:
        if self._llm is None:
            return {"ok": False, "applied": False, "reason": "no llm"}

        raw_profile = self._profile_store.load_profile()
        result = ProfileBuilder(self._llm).build(raw_profile)
        if preserve_self_concept:
            ProfileBuilder.save_built_profile(result.profile, self._cfg.persona_dir)
        else:
            ProfileBuilder.save(result, self._cfg.persona_dir)
            self._self_concept = result.self_concept

        self._raw_profile = raw_profile
        self._profile = result.profile
        if preserve_self_concept:
            self._self_concept = self._sc_store.load()

        distill = self._ensure_distill_impl()
        return {
            "ok": True,
            "applied": True,
            "reason": "rebuild_profile",
            "profile_source": "built",
            "self_concept_reset": not preserve_self_concept,
            "built_at": result.profile.built_at,
            "portrait_revision": self.portrait_revision(),
            "persona_distill_refreshed": distill.refreshed,
            "persona_distill_reason": distill.reason,
        }

    def portrait_for_narrative(
        self,
        max_chars: int = 1200,
        *,
        compact: bool = False,
    ) -> str:
        if compact:
            text = self._self_concept.render_for_role_llm(
                top_k=2,
                warn_main_portrait=True,
                caller="PersonaManager.portrait_for_narrative",
            )
            if not text.strip():
                text = self._profile.render(
                    warn_main_portrait=True,
                    caller="PersonaManager.portrait_for_narrative",
                )
        else:
            parts: list[str] = []
            profile_text = self._profile.render(
                warn_main_portrait=True,
                caller="PersonaManager.portrait_for_narrative",
            )
            if profile_text.strip():
                parts.append(profile_text)
            concept_text = self._self_concept.render_for_role_llm(
                top_k=2,
                warn_main_portrait=True,
                caller="PersonaManager.portrait_for_narrative",
            )
            if concept_text.strip():
                parts.append(concept_text)
            text = "\n\n".join(parts)
        if max_chars > 0 and len(text) > max_chars:
            text = text[-max_chars:]
        return text

    def reset_self_concept(self) -> None:
        """管理操作：清空 self_concept 与 buffer（非漂移路径）。"""
        self._enqueue_write(self._reset_self_concept_impl)

    def _reset_self_concept_impl(self) -> None:
        self._sc_store.clear()
        self._self_concept = SelfConcept()
        self._clear_buffer_impl()
        self._buffer_meta = BufferMeta()
