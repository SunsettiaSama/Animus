from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CharacterMemoryBuffer:
    """角色线程记忆 buffer。

    占位：后续完善。需要打通记忆（Life / Compose staging）到角色线程的链路。
    当前不检索、不写入、不向角色提示词注入正文。
    """

    session_id: str = ""
    texts: tuple[str, ...] = ()
    unit_ids: tuple[str, ...] = ()
    linked: bool = False
    reason: str = "占位：后续完善；需要打通记忆到角色线程的链路"
    meta: dict[str, Any] = field(default_factory=dict)

    def bind_session(self, session_id: str) -> None:
        sid = str(session_id or "").strip()
        if sid:
            self.session_id = sid

    def inject_texts(self) -> tuple[str, ...]:
        """链路打通后由此取出本轮可注入正文。未打通则空。"""
        if not self.linked:
            return ()
        return tuple(t.strip() for t in self.texts if str(t).strip())

    def note(self) -> str:
        return f"character_memory_buffer:{self.reason}"

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "linked": self.linked,
            "count": len(self.texts),
            "reason": self.reason,
        }
