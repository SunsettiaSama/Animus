from __future__ import annotations

from storyview import NarrativeBrief, StoryWorldview, StoryviewNarrativeEngine
from storyview.bridge import StoryWorldContextBridge


def test_default_worldview_renders():
    wv = StoryWorldview.default()
    text = wv.render()
    assert "虚实交界" in text
    assert "不可违背" in text


def test_engine_background_without_llm():
    engine = StoryviewNarrativeEngine(llm=None)
    bg = engine.render_background(query="雨夜窗前")
    assert "虚实交界" in bg
    assert "雨夜窗前" in bg


def test_engine_fallback_narrate():
    engine = StoryviewNarrativeEngine(llm=None)
    beat = engine.narrate(NarrativeBrief(hint="整理旧笔记"))
    assert "整理旧笔记" in beat.text
    assert beat.emotion_label


def test_bridge_implements_background_supplier():
    engine = StoryviewNarrativeEngine(llm=None)
    bridge = StoryWorldContextBridge(engine)

    class _Purpose:
        value = "fill"

    text = bridge.background(_Purpose(), query="午后")
    assert "午后" in text
