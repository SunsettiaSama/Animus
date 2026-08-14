from worker.state.memory_distill.bundle import PortraitSourceBundle
from worker.state.memory_distill.chain import (
    CHAIN_ID,
    CHAIN_ROLE,
    MemoryDistillChain,
)
from worker.state.memory_distill.source import gather_portrait_source
from worker.state.memory_distill.writer import MemoryPortraitWriter

__all__ = [
    "CHAIN_ID",
    "CHAIN_ROLE",
    "MemoryDistillChain",
    "MemoryPortraitWriter",
    "PortraitSourceBundle",
    "gather_portrait_source",
]
"""memory_distill — first Agent State submodule and fallback derivation chain.

Periodically compresses Soul long-term memory + Worker mid-term summaries into
the ``memory_portrait`` slot. Until richer state chains exist, this is the
default (degraded) refresh path used at startup and after successful work.
"""

from worker.state.memory_distill.bundle import PortraitSourceBundle
from worker.state.memory_distill.chain import (
    CHAIN_ID,
    CHAIN_ROLE,
    MemoryDistillChain,
)
from worker.state.memory_distill.source import gather_portrait_source
from worker.state.memory_distill.writer import MemoryPortraitWriter

__all__ = [
    "CHAIN_ID",
    "CHAIN_ROLE",
    "MemoryDistillChain",
    "MemoryPortraitWriter",
    "PortraitSourceBundle",
    "gather_portrait_source",
]
