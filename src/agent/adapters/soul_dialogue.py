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
