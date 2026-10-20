from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GamePerceptionInbound:
    """游戏/仿真侧亲历事件入站包（感知协议层 → life）。

    一切经历皆自然语言：``narrative`` 是已翻译成流畅自然语言的事件描述
    （协议保证），life 层不做二次改写。``perception`` 可提供更感官化的
    现场文本（缺省截取 narrative）。原始结构化数据走 ``evidence``，
    供事后归因与检索，不参与提示词。

    与 ``LifeIncident`` 的分工：incident 服务于心跳/地标/意外等系统内
    生成事件；本类型是外部世界（游戏、仿真）向 agent 生命经验灌入的
    专用通道，source 固定为 ``game``。
    """

    narrative: str
    session_id: str = "tao"
    channel_id: str = ""
    perception: str = ""
    action_summary: str = ""
    emotion_text: str = ""
    emotion_label: str = ""
    valence_delta: float = 0.0
    arousal_delta: float = 0.0
    salience: float = 0.4
    trigger: str = "game"
    scene: str = ""
    evidence: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.narrative.strip():
            raise ValueError("GamePerceptionInbound.narrative 不能为空（协议要求自然语言事件描述）")

    @property
    def effective_perception(self) -> str:
        return self.perception.strip() or self.narrative.strip()[:80]

    @property
    def effective_action_summary(self) -> str:
        return self.action_summary.strip() or self.narrative.strip()[:60]
