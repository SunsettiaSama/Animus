from __future__ import annotations

from dataclasses import dataclass, field

from .blocks import PersonaIdentityBlock, PersonaPresenceBlock, PersonaRelationalBlock
from .compose.state import PersonaComposeState


@dataclass
class SpeakPersonaLayer:
    """动态人格层：identity + presence（记忆/分享候选在 guidance 域）。"""

    identity: PersonaIdentityBlock = field(default_factory=PersonaIdentityBlock)
    presence: PersonaPresenceBlock = field(default_factory=PersonaPresenceBlock)
    relational: PersonaRelationalBlock = field(default_factory=PersonaRelationalBlock)
    dialogue_compressed: str = ""

    @classmethod
    def from_compose(cls, composed: PersonaComposeState) -> SpeakPersonaLayer:
        return cls(
            identity=PersonaIdentityBlock(
                narrative=composed.self_narrative,
                stable_source=composed.stable_portrait,
            ),
            presence=PersonaPresenceBlock(state=composed.state_portrait),
        )

    @property
    def self_narrative(self) -> str:
        return self.identity.narrative

    @self_narrative.setter
    def self_narrative(self, value: str) -> None:
        self.identity.narrative = value

    @property
    def dialogue(self) -> str:
        return self.identity.narrative

    @dialogue.setter
    def dialogue(self, value: str) -> None:
        self.identity.narrative = value

    @property
    def stable_portrait(self) -> str:
        return self.identity.stable_source

    @stable_portrait.setter
    def stable_portrait(self, value: str) -> None:
        self.identity.stable_source = value

    @property
    def state_portrait(self) -> str:
        return self.presence.state

    @state_portrait.setter
    def state_portrait(self, value: str) -> None:
        self.presence.state = value

    @property
    def instant_mood(self) -> str:
        return self.presence.instant_mood

    @instant_mood.setter
    def instant_mood(self, value: str) -> None:
        self.presence.instant_mood = value

    def render_interactor_block(self) -> str:
        return self.relational.render()

    def render_blocks(self) -> list[str]:
        from .render import render_persona_blocks

        return render_persona_blocks(self)
