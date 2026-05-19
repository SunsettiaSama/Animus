"""虚拟层 ↔ 编排器 接口约定（re-export）。"""

from ..experience.virtual_codec import (
    VirtualUnitContext,
    VirtualUnitTrigger,
    read_virtual_context,
    stamp_virtual_context,
)

__all__ = [
    "VirtualUnitContext",
    "VirtualUnitTrigger",
    "read_virtual_context",
    "stamp_virtual_context",
]
