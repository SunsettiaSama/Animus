from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.life.experience.stack import LifeExperienceStack


def _resolve_experience(
    *,
    experience: LifeExperienceStack | None,
    soul,
) -> LifeExperienceStack | None:
    if experience is not None:
        return experience
    if soul is None:
        return None
    return getattr(soul, "experience", None)


def close_dialogue_session(
    *,
    experience: LifeExperienceStack | None = None,
    soul=None,
    session_id: str = "tao",
) -> None:
    """会话闭合：life ↔ presence 经 experience stack 直连。"""
    stack = _resolve_experience(experience=experience, soul=soul)
    if stack is None:
        return
    stack.close_dialogue(session_id)


def record_dialogue_turn(
    *,
    experience: LifeExperienceStack | None = None,
    soul=None,
    session_id: str = "tao",
    user_text: str,
    agent_text: str,
) -> None:
    """轮末记账：life ↔ presence 经 experience stack 直连。"""
    stack = _resolve_experience(experience=experience, soul=soul)
    if stack is None:
        return
    stack.record_dialogue_turn(
        session_id=session_id,
        user_text=user_text,
        agent_text=agent_text,
    )
