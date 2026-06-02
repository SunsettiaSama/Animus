from __future__ import annotations

from .handlers.api.actions import LifeAction, MemoryAction, PersonaAction, SpeakAction
from .request import SoulDomain

# API 通道只读 action：idle / running 均可；其余 action 须 running。
READ_API_ACTIONS: frozenset[tuple[str, str]] = frozenset({
    (SoulDomain.persona.value, PersonaAction.GET_SNAPSHOT),
    (SoulDomain.persona.value, PersonaAction.PORTRAIT_REVISION),
    (SoulDomain.persona.value, PersonaAction.PORTRAIT_FOR_NARRATIVE),
    (SoulDomain.persona.value, PersonaAction.GET_BUFFER),
    (SoulDomain.memory.value, MemoryAction.SEARCH),
    (SoulDomain.memory.value, MemoryAction.NARRATIVE_CONTINUITY),
    (SoulDomain.memory.value, MemoryAction.RECALL),
    (SoulDomain.memory.value, MemoryAction.FETCH_PERSONA_CLUSTER),
    (SoulDomain.memory.value, MemoryAction.LIST_DRIFT_UNITS),
    (SoulDomain.life.value, LifeAction.RECENT_CHRONICLE),
    (SoulDomain.life.value, LifeAction.HOT_STORAGE),
    (SoulDomain.life.value, LifeAction.LOAD_PROFILE),
    (SoulDomain.life.value, LifeAction.STATUS),
    (SoulDomain.life.value, LifeAction.COUNT_LANDMARKS_SINCE),
    (SoulDomain.speak.value, SpeakAction.DRIVE_SNAPSHOT),
    (SoulDomain.speak.value, SpeakAction.EVALUATE_DRIVE),
    (SoulDomain.speak.value, SpeakAction.WORKING_MEMORY),
    (SoulDomain.speak.value, SpeakAction.DIALOGUE_STATE),
    (SoulDomain.speak.value, SpeakAction.DIRECTOR_SNAPSHOT),
})


def is_read_api_action(domain: SoulDomain | str, action: str) -> bool:
    d = domain.value if isinstance(domain, SoulDomain) else domain
    return (d, action) in READ_API_ACTIONS
