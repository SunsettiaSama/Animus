"""R6 回放框架保护：模式甲微剧本端到端（生产装配 + 观测 + 判定报告）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from memory_growth_replay import (  # noqa: E402
    ReplaySession,
    ReplayTurn,
    build_final_report,
    run_replay,
)


def _mini_scenarios() -> list[ReplaySession]:
    return [
        ReplaySession("rpt-s1", [
            ReplayTurn("我领养了一只猫叫团子", 0.8, promote=True, annotate=True),
            ReplayTurn("周末去了海边", 0.3),
        ]),
        ReplaySession("rpt-s2", [
            ReplayTurn("我养的猫叫什么来着", 0.5, probe_anchors=["团子"]),
        ]),
    ]


def test_replay_end_to_end_produces_funnel_and_ground_truth(tmp_path):
    from memory_growth_replay import ReplayFakeLLM

    ground_truth = run_replay(
        workspace=tmp_path, llm=ReplayFakeLLM(), scenarios=_mini_scenarios()
    )

    # ground truth：跨会话探针必须可判定
    assert ground_truth["probes"] == 1
    assert ground_truth["hit_rate_any"] is not None

    # 判定报告：漏斗与 Q1-Q8 齐全
    out_dir = tmp_path / "report_out"
    report_path = build_final_report(tmp_path, out_dir, ground_truth)
    md = report_path.read_text(encoding="utf-8")
    for section in ("擢升漏斗 F1–F7", "成长五维", "设计合理性判定 Q1–Q8", "跨会话 ground-truth 命中"):
        assert section in md
    metrics = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
    funnel = metrics["funnel"]
    assert funnel["F1_units_created"] == 2
    assert funnel["F2_annotated_promote"] == 1
    assert funnel["F4_nodes_created_from_units"] >= 1, "擢升单元应落图"
    assert metrics["questions"]["Q4_cross_session_recall"]["answer"] is True

    # 事件流水：全部核心事件类型在场
    events = [
        json.loads(line)
        for line in (tmp_path / "telemetry" / "memory_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    kinds = {e["event"] for e in events}
    for expected in (
        "unit_created", "unit_annotated", "promote_submitted", "node_created",
        "retrieval_performed", "session_closed", "snapshot_taken",
    ):
        assert expected in kinds, f"事件 {expected} 缺失"
    # 快照落盘
    assert list((tmp_path / "telemetry" / "snapshots").glob("*_growth_snapshot.json"))


def test_replay_fake_llm_archive_chooses_first_candidate():
    from memory_growth_replay import ReplayFakeLLM

    user_prompt = (
        "体验 id：u1\n来源：interaction\n写入类型：事件事实\n体验原文：\n用户：领养了猫\n\n"
        "语义候选父节点：\n1. id=node-9 score=0.500 [factual] 焦点 | 内容\n\n输出 JSON："
    )
    out = ReplayFakeLLM().generate_messages(
        [type("M", (), {"content": "你是记忆归档系统"})(), type("M", (), {"content": user_prompt})()]
    )
    payload = json.loads(out)
    assert payload["parent_node_id"] == "node-9"
