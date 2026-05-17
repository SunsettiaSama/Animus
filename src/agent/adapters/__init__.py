"""Transport-facing glue between AppState and ``agent.react`` (HTTP/WebSocket)."""

from agent.adapters.fastapi_react import create_react_router
from agent.adapters.react_stream import (
    ChunkStreamComposer,
    ConversationWireComposer,
    ReactOutputMode,
    StepFlushComposer,
    composer_for_mode,
    coerce_output_mode,
)

__all__ = [
    "ChunkStreamComposer",
    "ConversationWireComposer",
    "ReactOutputMode",
    "StepFlushComposer",
    "composer_for_mode",
    "coerce_output_mode",
    "create_react_router",
]
