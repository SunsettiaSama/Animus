from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agent.react.tao import TaoLoop
    from agent.soul.service import SoulService


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
    soul: SoulService | None,
    tao: TaoLoop,
    session_id: str = "tao",
) -> None:
    """轮末：presence dialogue 记账（FSM + turn 累积）。"""
    pending = peek_pending_turn(tao)
    if soul is None or pending is None:
        return
    soul.record_dialogue_turn(
        pending.question,
        pending.answer,
        session_id=session_id,
    )


def close_dialogue_session(
    *,
    soul: SoulService | None,
    session_id: str = "tao",
) -> None:
    """会话闭合：presence dialogue 导出长体验并注入 memory。"""
    if soul is None:
        return
    soul.close_dialogue_interaction(session_id)


def commit_turn_and_post_process(
    *,
    soul: SoulService | None,
    tao: TaoLoop,
    session_id: str = "tao",
) -> None:
    """标准轮末：dialogue 记账 → TaoLoop 上下文 post_process。"""
    record_pending_turn(soul=soul, tao=tao, session_id=session_id)
    tao.post_process()
