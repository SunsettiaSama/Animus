from __future__ import annotations

from agent.soul.memory.emergence.types import PointEmergenceResult
from agent.soul.memory.emergence.line_dedup import dedupe_memory_line_pairs


def test_dedupe_same_body_different_unit_ids():
    body = "阳光从我的发梢滑下，落在露米绒白的耳尖那粒冰晶上。小家伙正蜷成一团"
    lines = [
        f"[涌现的记忆] 冰晶虹光与森林密语：{body}",
        f"[涌现的记忆] 生灵递来的小小情书：{body}",
    ]
    out_lines, out_ids = dedupe_memory_line_pairs(lines, ["u1", "u2"])
    assert len(out_lines) == 1
    assert len(out_ids) == 1


def test_point_emergence_merged_pairs_dedupes_body():
    body = "阳光从我的发梢滑下，落在露米绒白的耳尖"
    result = PointEmergenceResult(
        session_id="s1",
        interactor_id="i1",
        precise_lines=[f"[涌现的记忆] 标题甲：{body}"],
        precise_unit_ids=["a"],
        associative_lines=[f"[涌现的记忆] 标题乙：{body}"],
        associative_unit_ids=["b"],
        associative_ready=True,
    )
    assert result.merged_lines() == [result.precise_lines[0]]
    assert result.merged_unit_ids() == ["a"]
