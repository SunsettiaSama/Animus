from __future__ import annotations

from dataclasses import dataclass

_IDENTITY_HEADER = "【自叙·你是谁】"


@dataclass
class PersonaIdentityBlock:
    """稳定人格 + 自叙蒸馏：你是谁、你是怎样的人。"""

    narrative: str = ""
    stable_source: str = ""

    def render(self) -> str:
        body = self.narrative.strip()
        if not body:
            return ""
        if body.startswith(_IDENTITY_HEADER):
            return body
        return f"{_IDENTITY_HEADER}\n{body}"
