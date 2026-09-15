from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agent.react.tao import TaoLoop
    from agent.soul.life.experience.hub import LifeExperienceStack


class PendingDialogueTurn(Protocol):
    question: str
    answer: str


def peek_pending_turn(tao: TaoLoop) -> PendingDialogueTurn | None:
    pending = tao.peek_pending_finish()
    if pending is None:
        return None
    return pending


def record_pending_turn(
    *,
    experience: LifeExperienceStack | None = None,
    soul=None,
    tao: TaoLoop,
    session_id: str = "tao",
) -> None:
    """Tao 轮末：从 TaoLoop 取 pending finish → experience stack 记账。"""
    from agent.soul.life.experience.dialogue.coordinator import record_dialogue_turn

    pending = peek_pending_turn(tao)
    if pending is None:
        return
    record_dialogue_turn(
        experience=experience,
        soul=soul,
        session_id=session_id,
        user_text=pending.question,
        agent_text=pending.answer,
    )
    # 用户轮信号 → life 导演侧（剧情重估/缓存失效判定，协议 v1.2 StorySignal）
    if soul is not None:
        from agent.soul.wiring.story import send_story_signal

        send_story_signal(
            soul,
            session_id=session_id,
            turn_digest=pending.question,
        )
        # 时间轴窗口刷新（上下文唯一历史语义，v7）：轮末把最近 k 条
        # （轮次 + 剧情事件混排）重新注入 compose buffer，与轮次无关。
        try:
            _speak = soul._ensure_speak_service()
            if _speak is not None:
                _speak.inject_timeline_window(session_id)
        except Exception:  # noqa: BLE001 — 注入失败不打断记账
            pass


def commit_turn_and_post_process(
    *,
    experience: LifeExperienceStack | None = None,
    soul=None,
    tao: TaoLoop,
    session_id: str = "tao",
) -> None:
    """Tao 标准轮末：dialogue 记账 → TaoLoop 上下文 post_process。"""
    record_pending_turn(
        experience=experience,
        soul=soul,
        tao=tao,
        session_id=session_id,
    )
    tao.post_process()
