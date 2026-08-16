from __future__ import annotations

from agent.soul.speak.responders.request_driven.orchestrator.blocks.memory.page_temp import (
    PageTempMemoryRing,
)


def test_page_temp_keeps_at_most_two_generations() -> None:
    ring = PageTempMemoryRing(max_generations=2)
    sid = "live:ch1"

    ring.enter_page(sid, page_key="a", lines=["A1"])
    ring.enter_page(sid, page_key="b", lines=["B1"])
    assert [g.page_key for g in ring.generations(sid)] == ["a", "b"]

    ring.enter_page(sid, page_key="c", lines=["C1"])
    gens = ring.generations(sid)
    assert [g.page_key for g in gens] == ["b", "c"]
    texts = [u.text for u in ring.all_units(sid)]
    assert "A1" not in texts
    assert "B1" in texts
    assert "C1" in texts


def test_reenter_same_page_replaces_that_generation() -> None:
    ring = PageTempMemoryRing(max_generations=2)
    sid = "live:ch1"

    ring.enter_page(sid, page_key="a", lines=["old-a"])
    ring.enter_page(sid, page_key="b", lines=["b"])
    ring.enter_page(sid, page_key="a", lines=["new-a"])

    gens = ring.generations(sid)
    assert [g.page_key for g in gens] == ["b", "a"]
    texts = [u.text for u in ring.all_units(sid)]
    assert "old-a" not in texts
    assert "new-a" in texts
    assert "b" in texts


def test_units_marked_page_temp() -> None:
    ring = PageTempMemoryRing(max_generations=2)
    gen = ring.enter_page("live:x", page_key="p1", lines=["hello"])
    assert len(gen.units) == 1
    assert gen.units[0].source == "page_temp"
    assert gen.units[0].text == "hello"
    assert "page_temp:" in gen.units[0].unit_id
