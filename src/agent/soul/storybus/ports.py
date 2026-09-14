"""storybus.ports — 端口协议（L0，Protocol only）。

接线关系（wiring/story.py 组装）：
- life 侧持有并调用 ``LifeStoryOutboxPort``；实现 = 总线（投递 beat / 推进度）。
- speak 侧实现 ``SpeakBeatInboxPort``（收 beat / 收进度），经总线回 ack、发 signal。
- life 侧实现 ``BeatAckReceiver`` 与 ``StorySignalInbox``（账本推进 / 失效判定）。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .messages import BeatAck, LifeStoryBeat, StoryProgressSync, StorySignal


@runtime_checkable
class LifeStoryOutboxPort(Protocol):
    """life 侧出站口：投递 beat / 刷新卡片进度。"""

    def deliver_beat(self, beat: LifeStoryBeat) -> bool:
        """投递一个 beat；返回 False = 被拒（如已过期/重复）。"""
        ...

    def sync_progress(self, sync: StoryProgressSync) -> None:
        ...


@runtime_checkable
class SpeakBeatInboxPort(Protocol):
    """speak 侧收件口：角色消费 beat / 表演层收进度。"""

    def receive_beat(self, beat: LifeStoryBeat) -> None:
        ...

    def receive_progress(self, sync: StoryProgressSync) -> None:
        ...


@runtime_checkable
class BeatAckReceiver(Protocol):
    """life 侧回执收件口：账本推进 / landmark 推进钩子。"""

    def receive_ack(self, ack: BeatAck) -> None:
        ...


@runtime_checkable
class StorySignalInbox(Protocol):
    """life 侧用户轮信号收件口：导演缓存失效判定。"""

    def receive_signal(self, signal: StorySignal) -> None:
        ...
