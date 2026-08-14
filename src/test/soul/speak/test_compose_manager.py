from __future__ import annotations

from random import Random

from agent.soul.speak.responders.request_driven.orchestrator.compose_manager import (
    ComposeManager,
    ComposeManagerConfig,
    ComposeManagerGateway,
)
from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.ports.memory import (
    MemoryUnit,
)


class _Mem:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def search_related(self, session_id, query_text, *, limit, hint="related"):
        self.calls.append((hint, query_text))
        base = [
            MemoryUnit(unit_id="a", text="春天去过海边"),
            MemoryUnit(unit_id="b", text="喜欢喝热茶"),
            MemoryUnit(unit_id="c", text="昨天加班到很晚"),
        ]
        return base[:limit]


def test_init_and_context_for_role_g2_user_only():
    rng = Random(0)
    mgr = ComposeManager(
        ComposeManagerConfig(enabled=True, rng_seed=0, bm25_min_score=0.0),
        memory_search=_Mem(),
        rng=rng,
    )
    view = mgr.init_session("s1", query_text="分享海边")
    assert view.session_id == "s1"
    mgr.on_user_ingress("s1", "今天想喝茶")
    role_view = mgr.context_for_role("s1", user_text="今天想喝茶")
    assert role_view.meta.get("g2_user_only") is True
    assert isinstance(role_view.memory_texts, tuple)


def test_compress_only_user_agent_every_k():
    mgr = ComposeManager(
        ComposeManagerConfig(enabled=True, compress_chunk_size=2, rng_seed=1),
        memory_search=_Mem(),
        rng=Random(1),
    )
    mgr.init_session("s2")
    assert mgr.on_turn_complete("s2", "你好", "嗨") is None
    summary = mgr.on_turn_complete("s2", "在吗", "在的")
    assert summary is not None
    distilled, working = mgr._trajectory.snapshot_texts("s2")
    assert len(distilled) == 1
    assert working == []


def test_compress_summary_flows_into_staging_buffer():
    mgr = ComposeManager(
        ComposeManagerConfig(enabled=True, compress_chunk_size=2, rng_seed=3),
        memory_search=_Mem(),
        rng=Random(3),
    )
    mgr.init_session("s5")
    mgr.on_turn_complete("s5", "用户甲", "回复甲")
    summary = mgr.on_turn_complete("s5", "用户乙", "回复乙")
    assert summary is not None
    staged = mgr._staging.items("s5")
    traj = [item for item in staged if item.kind == "trajectory"]
    assert len(traj) == 1
    assert traj[0].unit.text == summary
    assert traj[0].unit.source == "trajectory_compress"


def test_retrieve_90_10_with_seeded_rng():
    mem = _Mem()
    # force random branch: normal_ratio=0 so always random
    mgr = ComposeManager(
        ComposeManagerConfig(
            enabled=True,
            retrieve_normal_ratio=0.0,
            rng_seed=7,
        ),
        memory_search=mem,
        rng=Random(7),
    )
    mgr.init_session("s3", query_text="茶")
    hits_view = mgr.context_for_role("s3", user_text="热茶")
    assert len(hits_view.memory_texts) == 1


def test_gateway_falls_back_when_disabled():
    gw = ComposeManagerGateway(ComposeManager(ComposeManagerConfig(enabled=False)))
    called = {"legacy": 0}

    def legacy():
        called["legacy"] += 1
        return "legacy"

    out = gw.run_or_legacy("x", lambda: "new", legacy)
    assert out == "legacy"
    assert called["legacy"] == 1


def test_director_has_own_retrieve_and_sees_role_hits():
    mgr = ComposeManager(
        ComposeManagerConfig(enabled=True, rng_seed=2),
        memory_search=_Mem(),
        rng=Random(2),
    )
    mgr.init_session("s4", query_text="海边")
    dview = mgr.context_for_director("s4", user_text="还记得海边吗")
    assert dview.session_id == "s4"
    assert dview.meta.get("source") == "compose_manager.director_own_retrieve"
    assert dview.meta.get("role_hits_visible") is True
    assert isinstance(dview.director_memory_ids, tuple)
    assert isinstance(dview.role_memory_ids, tuple)


def test_director_intervene_inject_and_limit():
    from agent.soul.speak.responders.request_driven.orchestrator.compose_manager import (
        DirectorMemoryIntervention,
    )

    mgr = ComposeManager(
        ComposeManagerConfig(
            enabled=True,
            rng_seed=5,
            director_memory_intervene_max=1,
        ),
        memory_search=_Mem(),
        rng=Random(5),
    )
    mgr.init_session("s6", query_text="茶")
    mgr.on_user_ingress("s6", "续聊")
    first = mgr.apply_director_memory_intervention(
        "s6",
        DirectorMemoryIntervention(action="inject", text="导演塞入的一条"),
    )
    assert first["applied"] is True
    second = mgr.apply_director_memory_intervention(
        "s6",
        DirectorMemoryIntervention(action="inject", text="第二条应被拒"),
    )
    assert second["applied"] is False
    assert second["reason"] == "intervene_limit"
    staged = mgr._staging.items("s6")
    assert any(item.kind == "director_inject" for item in staged)


def test_persona_and_system_never_enter_staging_or_match():
    from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.domain.utterance import (
        filter_utterance_units,
    )

    noisy = [
        MemoryUnit(unit_id="p1", text="我是温柔的人", source="persona"),
        MemoryUnit(unit_id="p2", text="画像片段", source="interactor_portrait"),
        MemoryUnit(unit_id="s1", text="你是助手", source="system_prompt"),
        MemoryUnit(unit_id="ok", text="昨天一起喝了茶", source="recall_candidate"),
    ]
    kept = filter_utterance_units(noisy)
    assert [u.unit_id for u in kept] == ["ok"]

    mgr = ComposeManager(
        ComposeManagerConfig(enabled=True, rng_seed=9, retrieve_normal_ratio=1.0),
        memory_search=_Mem(),
        rng=Random(9),
    )
    mgr.init_session("s8")
    mgr._staging.ingest_units("s8", noisy, kind="persona")
    staged_ids = {item.unit.unit_id for item in mgr._staging.items("s8")}
    assert "p1" not in staged_ids
    assert "p2" not in staged_ids
    assert "s1" not in staged_ids
    # kind=persona 整批会被滤掉；用 utterance kind 再灌一次有效条目
    mgr._staging.ingest_units(
        "s8",
        [MemoryUnit(unit_id="ok2", text="海边散步", source="utterance")],
        kind="related",
    )
    hits = mgr.retrieve_for_role("s8", user_text="海边")
    assert all(hit.unit.source not in {"persona", "system_prompt", "interactor_portrait"} for hit in hits)


def test_director_intervene_remove():
    from agent.soul.speak.responders.request_driven.orchestrator.compose_manager import (
        DirectorMemoryIntervention,
    )

    mgr = ComposeManager(
        ComposeManagerConfig(enabled=True, rng_seed=6, director_memory_intervene_max=1),
        memory_search=_Mem(),
        rng=Random(6),
    )
    mgr.init_session("s7", query_text="茶")
    mgr.on_user_ingress("s7", "续")
    before_ids = {item.unit.unit_id for item in mgr._staging.items("s7")}
    assert before_ids
    target = next(iter(before_ids))
    result = mgr.apply_director_memory_intervention(
        "s7",
        DirectorMemoryIntervention(action="remove", unit_id=target),
    )
    assert result["applied"] is True
    after_ids = {item.unit.unit_id for item in mgr._staging.items("s7")}
    assert target not in after_ids


def test_ingest_units_from_memory_pull():
    mgr = ComposeManager(
        ComposeManagerConfig(enabled=True, rng_seed=9),
        memory_search=_Mem(),
        rng=Random(9),
    )
    mgr.init_session("s9", query_text="茶")
    mgr.ingest_units(
        "s9",
        [
            MemoryUnit(unit_id="pull-1", text="海边日落", source="memory_pull"),
            MemoryUnit(unit_id="pull-2", text="热茶续杯", source="memory_pull"),
        ],
        kind="memory_pull",
    )
    staged = mgr._staging.items("s9")
    pull_ids = {item.unit.unit_id for item in staged if item.kind == "memory_pull"}
    assert pull_ids == {"pull-1", "pull-2"}


def test_units_from_search_hits_keeps_concrete_memory():
    from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.ports.adapters import (
        units_from_search_hits,
    )

    units = units_from_search_hits(
        [
            {
                "id": "u1",
                "focus": "海边",
                "fact": "春天去过海边",
                "final_score": 0.9,
                "source": "hybrid",
            },
            {
                "id": "u2",
                "focus": "画像",
                "fact": "应被丢弃",
                "source": "persona",
            },
        ],
        limit=5,
    )
    assert len(units) == 1
    assert units[0].unit_id == "u1"
    assert "海边" in units[0].text
