from __future__ import annotations

from storyview.engine import StoryviewNarrativeEngine


class StoryWorldContextBridge:
    """对接 soul.life.StoryWorldContextSupplier，向虚拟叙事注入故事观背景。"""

    def __init__(self, engine: StoryviewNarrativeEngine) -> None:
        self._engine = engine

    def background(
        self,
        purpose,
        *,
        query: str = "",
    ) -> str:
        purpose_value = getattr(purpose, "value", str(purpose))
        return self._engine.render_background(query=query, purpose=purpose_value)
