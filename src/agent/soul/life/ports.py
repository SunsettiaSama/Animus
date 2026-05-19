from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .anchor.chronicle.entry import AnchorChronicleEntry
    from .virtual.chronicle.entry import VirtualChronicleEntry


class AnchorChroniclePort(Protocol):
    """锚点层 Chronicle 写入端口。"""

    def append(self, entry: AnchorChronicleEntry) -> None: ...

    def retract_by_experience_ids(self, experience_ids: set[str]) -> int: ...


class VirtualChroniclePort(Protocol):
    """虚拟层 Chronicle 写入端口。"""

    def append(self, entry: VirtualChronicleEntry) -> None: ...

    def retract_by_experience_ids(self, experience_ids: set[str]) -> int: ...


RealityChroniclePort = AnchorChroniclePort
