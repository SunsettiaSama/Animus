"""performance.policy — 角色 beat 开口决策（R7；自 request_driven/character 迁入）。

职责边界：beat 到达后，"现在开口 / 挂起改期 / 沉默不表"由**角色**自决，
life 的 performance_hint 只是建议性输入（不是指令）。

本实现是确定性规则版（纯函数、无 LLM）；CharacterRuntime 的人格化节奏
（依性格/交互账本微调阈值）在此之上迭代，决策接口不变：

    perform_now  现在开口（经表演路径演出）
    hold         挂起改期（回执 suppressed，life 可重投）
    silence      沉默不表（回执 silenced——"…"也是表达）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PERFORM_NOW = "perform_now"
HOLD = "hold"
SILENCE = "silence"


@dataclass(frozen=True)
class OpeningDecision:
    action: str
    reason: str

    @property
    def perform_now(self) -> bool:
        return self.action == PERFORM_NOW


class BeatOpeningPolicy:
    """确定性开口决策：hint 建议 × 在场状态 → 三择一。"""

    def __init__(
        self,
        *,
        perform_threshold: float = 0.75,
        silence_threshold: float = 0.35,
        high_salience_signal: float = 0.7,
    ) -> None:
        self._perform_threshold = perform_threshold
        self._silence_threshold = silence_threshold
        self._high_salience_signal = high_salience_signal

    def decide(
        self,
        beat: Any,
        *,
        speak_ready: bool,
        user_busy: bool = False,
    ) -> OpeningDecision:
        hint = getattr(beat, "hint", None)
        urgency = str(getattr(hint, "urgency", "normal") or "normal")
        desire = float(getattr(hint, "share_desire", 0.5) or 0.0)

        if not speak_ready:
            return OpeningDecision(HOLD, "speak_not_ready")
        if user_busy:
            # 用户正在对话：不打断，挂起改期（协议 §7.3 优先级约定）
            return OpeningDecision(HOLD, "user_busy")
        if urgency == "eager" or desire >= self._perform_threshold:
            return OpeningDecision(PERFORM_NOW, "eager_or_high_desire")
        if urgency == "calm" and desire < self._silence_threshold:
            return OpeningDecision(SILENCE, "calm_low_desire")
        return OpeningDecision(PERFORM_NOW, "default_open")

    def salience_warrants_rewrite(self, salience_hint: float) -> bool:
        """用户轮显著度是否高到需要导演重估剧情（缓存失效判定输入）。"""
        return float(salience_hint) >= self._high_salience_signal


class FrameGate:
    """时间帧单开口闸（speak 底层约定：一个时间帧至多开口一次）。

    - 同渠道同帧窗口内首次开口放行，其后一律拒绝（改期语义：suppressed）；
    - 帧内无论开口、沉默还是改期，**都在当前帧完成裁决**——不留跨帧悬案；
    - 窗口默认 5s（对齐 poll 阶梯首档），可注入时钟做确定性测试。
    """

    def __init__(self, *, window_sec: float = 5.0, clock=None) -> None:
        import time as _time

        self._window = max(0.1, float(window_sec))
        self._clock = clock or _time.monotonic
        self._last_open: dict[str, float] = {}

    def try_open(self, channel: str) -> bool:
        now = self._clock()
        last = self._last_open.get(channel)
        if last is not None and (now - last) < self._window:
            return False
        self._last_open[channel] = now
        return True
