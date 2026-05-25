from __future__ import annotations

from agent.soul.access import READ_API_ACTIONS, is_read_api_action
from agent.soul.handlers.api.actions import LifeAction, MemoryAction, PersonaAction, SpeakAction
from agent.soul.request import SoulDomain


def test_read_api_actions_cover_query_wrappers():
    expected = {
        (SoulDomain.persona.value, PersonaAction.GET_SNAPSHOT),
        (SoulDomain.memory.value, MemoryAction.SEARCH),
        (SoulDomain.life.value, LifeAction.RECENT_CHRONICLE),
        (SoulDomain.life.value, LifeAction.HOT_STORAGE),
        (SoulDomain.speak.value, SpeakAction.DRIVE_SNAPSHOT),
        (SoulDomain.speak.value, SpeakAction.DIALOGUE_STATE),
    }
    assert expected.issubset(READ_API_ACTIONS)


def test_write_actions_not_read():
    assert not is_read_api_action(SoulDomain.memory, MemoryAction.FLUSH)
    assert not is_read_api_action(SoulDomain.persona, PersonaAction.RELOAD_PROFILE)
    assert not is_read_api_action(SoulDomain.persona, PersonaAction.REBUILD_PROFILE)
    assert not is_read_api_action(SoulDomain.persona, PersonaAction.RUN_MONTHLY_DRIFT)
    assert not is_read_api_action(SoulDomain.persona, PersonaAction.RESET_SELF_CONCEPT)
    assert not is_read_api_action(SoulDomain.memory, MemoryAction.FORGET_SCAN)
    assert not is_read_api_action(SoulDomain.life, LifeAction.RECORD_TURN)
    assert not is_read_api_action(SoulDomain.speak, SpeakAction.RECORD_DIALOGUE)
    assert not is_read_api_action(SoulDomain.speak, SpeakAction.CLOSE_SESSION)


def test_is_read_api_action_accepts_string_domain():
    assert is_read_api_action("memory", MemoryAction.SEARCH)
