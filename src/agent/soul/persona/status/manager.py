from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from config.agent.persona_config import PersonaConfig
from infra.llm import BaseLLM
from .block import StatusBlock
from .emotional import EmotionalAnchor, EmotionalState, EmotionalStateStore
from .life_bridge import LifeContextInput
from .synthesizer import StatusSynthesizer

logger = logging.getLogger(__name__)


class StatusManager:
    """Agent 自身情绪状态的管理器。

    两条输入通道
    ────────────
    1. record_interaction()  每轮对话轻量缓冲，不调用 LLM
    2. receive_life_context() life 层故事背景接口，可主动触发 texture 更新

    texture 更新策略
    ────────────────
    - 每隔 update_interval 轮对话，由 StatusSynthesizer 合成新 texture
    - life 层传入背景时也可触发更新（trigger_update=True）
    - 心跳高强度漂移信号时触发异步更新

    状态持久化
    ──────────
    EmotionalState 每次更新后自动写盘（emotional_state.json）。
    """

    def __init__(
        self,
        persona_dir: str,
        cfg: PersonaConfig,
        llm: BaseLLM | None = None,
        profile=None,
    ) -> None:
        self._cfg = cfg
        self._profile = profile
        self._update_interval: int = getattr(cfg, "status_update_interval", 5)
        self._turn_count: int = 0

        # ── 状态 ──────────────────────────────────────────────────────────────
        self._emotional_store = EmotionalStateStore(persona_dir)
        self._emotional: EmotionalState = self._emotional_store.load()

        # ── 缓冲区 ────────────────────────────────────────────────────────────
        self._interaction_buffer: list[str] = []
        self._life_context: str = ""

        # ── 合成器 ────────────────────────────────────────────────────────────
        self._synthesizer: StatusSynthesizer | None = (
            StatusSynthesizer(llm) if cfg.evolution_enabled and llm is not None else None
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def emotional_state(self) -> EmotionalState:
        return self._emotional

    def is_empty(self) -> bool:
        return self._emotional.is_empty()

    # ── Prompt block ──────────────────────────────────────────────────────────

    def status_block(self) -> StatusBlock:
        return StatusBlock(
            emotional=self._emotional,
            max_chars=getattr(self._cfg, "max_status_chars", 600),
        )

    # ── 输入通道 1：每轮交互缓冲（轻量，不调用 LLM）────────────────────────

    def record_interaction(self, question: str, answer: str) -> None:
        """每轮对话后调用：将交互摘要写入缓冲区，达到频率时触发 texture 合成。

        不调用 LLM，只做轻量文本记录。
        """
        summary = f"用户：{question[:80]}"
        if answer:
            summary += f" | 回应：{answer[:80]}"
        self._interaction_buffer.append(summary)
        self._turn_count += 1

        if (
            self._synthesizer is not None
            and self._turn_count % self._update_interval == 0
        ):
            self._synthesize_texture()

    # ── 输入通道 2：life 层故事背景接口 ──────────────────────────────────────

    def receive_life_context(
        self, ctx: LifeContextInput, trigger_update: bool = True
    ) -> None:
        """Life 层接口：传入事实性故事背景。

        ctx             : LifeContextInput，由 life 层通过 life_bridge 构建
        trigger_update  : 是否立即触发 texture 合成（默认是）
        """
        if ctx.is_empty():
            return
        self._life_context = ctx.render_for_prompt()
        if trigger_update and self._synthesizer is not None:
            self._synthesize_texture()

    # ── Texture 合成（LLM 调用，频率控制）────────────────────────────────────

    def _synthesize_texture(self) -> None:
        if self._synthesizer is None:
            return
        if not self._interaction_buffer and not self._life_context:
            return
        if self._profile is None:
            return

        new_state = self._synthesizer.synthesize(
            current=self._emotional,
            profile=self._profile,
            interaction_buffer=list(self._interaction_buffer),
            life_context=self._life_context,
        )
        if new_state is not self._emotional:
            self._emotional = new_state
            self._emotional_store.save(new_state)
            self._interaction_buffer.clear()
            logger.debug("[Status] texture 已更新，缓冲区已清空")

    # ── 心跳漂移接口 ──────────────────────────────────────────────────────────

    def receive_signal(self, signal, profile=None) -> None:
        """接收 heartbeat 情绪漂移信号。

        低强度（< 0.3）：直接追加为一条锚点，不触发 texture 合成。
        高强度（>= 0.3）：追加锚点 + 异步触发 texture 合成。
        """
        if signal.intensity < 0.05:
            return

        _profile = profile or self._profile
        anchor = EmotionalAnchor(
            ts=datetime.now(timezone.utc).isoformat(),
            event=signal.narrative_hint or f"心跳漂移（{signal.dominant_emotion}）",
            felt=f"{signal.dominant_emotion}，烈度 {signal.intensity:.2f}",
        )
        new_anchors = (self._emotional.anchors + [anchor])[-10:]
        self._emotional = EmotionalState(
            updated_at=datetime.now(timezone.utc).isoformat(),
            texture=self._emotional.texture,
            anchors=new_anchors,
        )
        self._emotional_store.save(self._emotional)

        if signal.intensity >= 0.3 and self._synthesizer is not None and _profile is not None:
            threading.Thread(
                target=self._async_synthesize,
                args=(_profile,),
                daemon=True,
                name="status-signal-synth",
            ).start()

    def _async_synthesize(self, profile) -> None:
        new_state = self._synthesizer.synthesize(
            current=self._emotional,
            profile=profile,
            interaction_buffer=list(self._interaction_buffer),
            life_context=self._life_context,
        )
        if new_state is not self._emotional:
            self._emotional = new_state
            self._emotional_store.save(new_state)
            self._interaction_buffer.clear()

    # ── Bridge 接口 ───────────────────────────────────────────────────────────

    def to_persona_snapshot(self):
        from agent.soul.heartbeat.bridge import PersonaSnapshot
        return PersonaSnapshot(
            emotional_state=self._emotional.texture or "",
            valence_bias=None,
            attention_keywords=[],
        )

    # ── 重置 ──────────────────────────────────────────────────────────────────

    def clear(self) -> None:
        self._emotional_store.clear()
        self._emotional = EmotionalState()
        self._interaction_buffer.clear()
        self._life_context = ""
        self._turn_count = 0
