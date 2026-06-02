from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PersonaRelationalBlock:
    """对话者（用户）画像：由 memory 拉取，经 persona 域注入 prompt。"""

    interactor_portrait: str = ""

    def render(self) -> str:
        return self.interactor_portrait.strip()
