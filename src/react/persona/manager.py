from __future__ import annotations

from config.react.persona_config import PersonaConfig
from react.memory.memory import Step
from react.persona.block import ChronicleBlock, ProfileBlock
from react.persona.chronicle import PersonaChronicle
from react.persona.profile import PersonaProfile
from react.persona.store import PersonaStore


class PersonaManager:
    def __init__(self, cfg: PersonaConfig) -> None:
        self._cfg = cfg
        self._store = PersonaStore(cfg.persona_dir)
        self._profile = self._store.load_profile()
        self._chronicle = self._store.load_chronicle(
            cfg.max_chronicle_entries, cfg.max_chronicle_entry_chars
        )

    @property
    def profile(self) -> PersonaProfile:
        return self._profile

    @property
    def chronicle(self) -> PersonaChronicle:
        return self._chronicle

    def profile_block(self) -> ProfileBlock:
        return ProfileBlock(self._profile, max_chars=self._cfg.max_profile_chars)

    def chronicle_block(self, recent: int | None = None) -> ChronicleBlock:
        n = recent if recent is not None else self._cfg.chronicle_recent_in_prompt
        return ChronicleBlock(
            self._chronicle,
            recent=n,
            max_render_chars=self._cfg.max_chronicle_render_chars,
        )

    def evolve(self, question: str, answer: str, steps: list[Step]) -> None:
        if not self._cfg.chronicle_enabled:
            return
        narrative = self._build_narrative(question, answer, steps)
        self._chronicle.append(narrative)
        self._store.save_chronicle(self._chronicle)

    def save_profile(self) -> None:
        self._store.save_profile(self._profile)

    def _build_narrative(self, question: str, answer: str, steps: list[Step]) -> str:
        name = self._profile.name
        actions = list(dict.fromkeys(s.action for s in steps))

        answer_excerpt = answer[:100] + "…" if len(answer) > 100 else answer

        if actions:
            action_text = "、".join(actions)
            return (
                f"面对「{question}」，{name}先后运用了{action_text}等方式展开推理，"
                f"最终得出结论：{answer_excerpt}"
            )
        return (
            f"面对「{question}」，{name}经过审慎思考，"
            f"直接作答：{answer_excerpt}"
        )
