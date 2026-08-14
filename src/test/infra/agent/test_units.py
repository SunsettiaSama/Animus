from __future__ import annotations

from dataclasses import dataclass

from infra.agent import ObservationUnit, ThoughtActionUnit, Timeline, Unit, UserUnit


@dataclass
class RhythmCardUnit(Unit):
    """测试用自定义 unit：证明导演节奏卡片可注入上下文。"""

    card: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "rhythm_card"
        if not self.source:
            self.source = "director"

    def render(self) -> str:
        text = self.card.strip()
        return f"[节奏卡片]\n{text}" if text else ""


def test_builtin_units_render():
    user = UserUnit(text="你好")
    assert "[用户输入]" in user.render()
    assert "你好" in user.render()

    ta = ThoughtActionUnit(
        thought="需要搜索",
        action="web_search",
        action_input={"q": "x"},
        output="稍等",
    )
    rendered = ta.render()
    assert "<T>需要搜索</T>" in rendered
    assert "web_search" in rendered
    assert "<O>稍等</O>" in rendered

    obs = ObservationUnit(observation="结果", tool="web_search", parent_id=ta.unit_id)
    assert "(web_search)" in obs.render()
    assert "结果" in obs.render()


def test_timeline_insertion_order_and_custom_unit():
    timeline = Timeline()
    timeline.add_user("第一句")
    timeline.inject(RhythmCardUnit(card="放慢节奏"))
    timeline.add_thought_action(thought="想", action="finish", action_input={"answer": "ok"})
    timeline.add_observation("done", tool="finish")

    text = timeline.render()
    assert text.index("[用户输入]") < text.index("[节奏卡片]")
    assert text.index("[节奏卡片]") < text.index("<T>想</T>")
    assert "放慢节奏" in text


def test_timeline_snapshot_is_independent_copy():
    timeline = Timeline()
    timeline.add_user("a")
    snapped = timeline.snapshot()
    timeline.add_user("b")
    assert "a" in snapped.render()
    assert "b" not in snapped.render()
    assert "b" in timeline.render()
