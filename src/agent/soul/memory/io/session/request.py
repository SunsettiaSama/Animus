from __future__ import annotations

from dataclasses import dataclass, field

from agent.soul.life.experience.domain.unit import ExperienceUnit

from .types import DialogueCompressionBlock, SessionBlockRecord


@dataclass(frozen=True)
class CompressionBlockInbound:
    """Speak → Memory：上下文压缩块入站。"""

    block: DialogueCompressionBlock
    interactor_id: str = ""


@dataclass(frozen=True)
class SessionCloseInbound:
    """Speak → Memory：会话闭合入站。"""

    session_id: str
    interactor_id: str = ""
    final_unit: ExperienceUnit | None = None


@dataclass
class CompressionBlockAck:
    """Memory → Speak：压缩块已缓冲。"""

    session_id: str
    record: SessionBlockRecord | None = None


@dataclass
class SessionCloseAck:
    """Memory → Speak：会话闭合整合完成。"""

    session_id: str
    interactor_id: str = ""
    merged_node_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DialogueTurnInbound:
    """Speak → Memory：一轮用户/Agent 对话环，触发异步检索。"""

    session_id: str
    turn_index: int
    user_text: str
    agent_text: str = ""
    interactor_id: str = ""
    channel_id: str = ""
    want_dynamic_portrait: bool = False
    want_dynamic_event: bool = False


@dataclass(frozen=True)
class StaticPortraitInbound:
    """Speak → Memory：账号/渠道绑定后拉取 SocialCore 静态画像。"""

    interactor_id: str
    session_id: str = ""
    turn_index: int = 0


@dataclass(frozen=True)
class InteractorPrefetchInbound:
    """Speak → Memory：interactor 绑定后 Social 网预取。"""

    session_id: str
    interactor_id: str
    turn_index: int = 0


@dataclass(frozen=True)
class KeywordQueryInbound:
    """Speak → Memory：当前轮粗粒度关键字检索。"""

    session_id: str
    turn_index: int
    user_text: str
    interactor_id: str = ""
    agent_text: str = ""
