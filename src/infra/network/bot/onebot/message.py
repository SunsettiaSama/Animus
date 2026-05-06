from __future__ import annotations


class Message:
    """Fluent builder for OneBot 11 message segment arrays."""

    def __init__(self) -> None:
        self._segments: list[dict] = []

    # ── Segment builders ──────────────────────────────────────────────────────

    def text(self, s: str) -> Message:
        self._segments.append({"type": "text", "data": {"text": s}})
        return self

    def at(self, qq: int | str) -> Message:
        self._segments.append({"type": "at", "data": {"qq": str(qq)}})
        return self

    def image(self, file: str) -> Message:
        self._segments.append({"type": "image", "data": {"file": file}})
        return self

    def reply(self, msg_id: int) -> Message:
        self._segments.append({"type": "reply", "data": {"id": str(msg_id)}})
        return self

    def face(self, face_id: int) -> Message:
        self._segments.append({"type": "face", "data": {"id": str(face_id)}})
        return self

    # ── Export ────────────────────────────────────────────────────────────────

    def to_array(self) -> list[dict]:
        return list(self._segments)

    @property
    def plain_text(self) -> str:
        return "".join(
            seg["data"].get("text", "")
            for seg in self._segments
            if seg.get("type") == "text"
        )

    def __str__(self) -> str:
        return self.plain_text

    # ── Factory helpers ───────────────────────────────────────────────────────

    @classmethod
    def of(cls, text: str) -> Message:
        return cls().text(text)

    @classmethod
    def from_array(cls, arr: list[dict]) -> Message:
        m = cls()
        m._segments = list(arr)
        return m
