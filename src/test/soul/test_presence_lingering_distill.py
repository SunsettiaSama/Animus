from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.life.experience.unit_layer.manage.log import ExperienceLog
from agent.soul.presence import PresenceService
from agent.soul.presence.lingering import apply_unit_lingering, expire_lingering_moods
from agent.soul.presence.state.lingering import LingeringMood
from agent.soul.presence.state.presence_state import PresenceState
from agent.soul.presence.unit_distill.prose import validate_agent_prose
from agent.soul.presence.unit_distill.writer import PresenceUnitDistillWriter
from agent.soul.speak.io.inbound.compose import collect_status_injected, render_presence_fuel_for_agent


def test_lingering_expires():
    state = PresenceState()
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    state.lingering_moods = [
        LingeringMood(text="你会有点累", until_iso=past, source_unit_id="u1"),
    ]
    expire_lingering_moods(state)
    assert state.lingering_moods == []


def test_apply_unit_lingering_writes_mood():
    state = PresenceState()
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(session_id="tao", narration="刚才你摔了一跤"),
        action=ExperienceAction(kind=ExperienceActionKind.attending, content="摔跤"),
        feeling=ExperienceFeeling(
            mood_span="接下来一两天你会有点沮丧",
            linger_days=2.0,
            salience=0.55,
        ),
        source="narrative",
    )
    notes = apply_unit_lingering(state, unit)
    assert notes
    assert len(state.lingering_moods) == 1
    assert "沮丧" in state.lingering_moods[0].text


def test_unit_distill_mock_llm(tmp_path):
    log = ExperienceLog(str(tmp_path))
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(
            session_id="tao",
            narration="今天你在雨里走了一段路",
        ),
        action=ExperienceAction(kind=ExperienceActionKind.reasoning, content="雨中行走"),
        feeling=ExperienceFeeling(
            mood_span="接下来几天你会带着一点潮湿的疲惫",
            linger_days=2.0,
            salience=0.5,
        ),
        source="narrative",
    )
    log.append(unit)
    unit2 = ExperienceUnit.make(
        situation=ExperienceSituation(session_id="tao", narration="你回家换了干衣服"),
        action=ExperienceAction(kind=ExperienceActionKind.attending, content="换衣"),
        feeling=ExperienceFeeling(salience=0.4),
        source="narrative",
    )
    log.append(unit2)

    llm = MagicMock()
    llm.generate_messages.return_value = (
        "这两天你在雨里走过一段路，鞋底还留着潮气；"
        "接下来几天你会带着一点潮湿的疲惫，说话也会慢半拍。"
    )
    svc = PresenceService()
    svc.bind_unit_distill_llm(llm)
    svc.on_unit_ingested(unit, log)
    svc.on_unit_ingested(unit2, log)

    snap = svc.snapshot("tao")
    assert snap.state.recent_portrait.narrative.startswith("这两天")
    assert "情感：" not in snap.state.recent_portrait.narrative


def test_validate_agent_prose_rejects_field_lines():
    raw = "【当下态·状态】\n情感：平静"
    raised = False
    try:
        validate_agent_prose(raw)
    except ValueError:
        raised = True
    assert raised


def test_collect_status_uses_recent_portrait_not_affect_labels():
    state = PresenceState()
    state.recent_portrait.narrative = "你这两天在雨里走过，还带着一点潮湿的疲惫。"
    state.affect.narrative = "不应出现在 speak"

    snap = MagicMock()
    snap.session_id = "tao"
    snap.state = state

    injected = collect_status_injected(presence_snap=snap)
    assert injected.presence.startswith("你这两天")
    assert "情感：" not in injected.presence
    assert "【当下态·状态】" not in injected.presence


def test_render_presence_fuel_empty_without_portrait():
    state = PresenceState()
    assert render_presence_fuel_for_agent(state) == ""
