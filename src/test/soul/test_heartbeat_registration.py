"""wake registration 契约测试：注册 API / target 解析 / 通用执行 / 装配。

验收 PRD（wake-registration-prd）：heartbeat 零模块知识，12 个默认项
经注册契约执行，心脏跳动。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.soul.heartbeat.orchestrate.orchestrator import HeartbeatOrchestrator
from agent.soul.heartbeat.schedule import (
    ChecklistItem,
    ChecklistRegistry,
    HeartbeatContext,
    resolve_target,
)

DEFAULT_IDS = {
    "life-plan-landmark", "life-trigger-landmark", "life-surprise",
    "life-scheduler-digest", "story-tick", "memory-wander", "memory-forget",
    "memory-sleep", "presence-wake-up", "presence-expectation-scan",
    "presence-external-scan", "persona-monthly-drift",
    "scheduler-daily-planner-review-ensure",
}


# ── 注册 API ────────────────────────────────────────────────────────────────

def _item(id="x", target=lambda p, c: {"ok": 1}, **kw):
    return ChecklistItem(id=id, domain="test", action="act", target=target, **kw)


def test_register_and_overwrite_same_id():
    reg = ChecklistRegistry()
    reg.register(_item(id="a"))
    reg.register(_item(id="a", target=lambda p, c: {"v": 2}))
    assert len(reg.all()) == 1
    assert reg.all()[0].payload == {}  # 覆盖生效（新实例）


def test_register_rejects_missing_target():
    with pytest.raises(ValueError, match="target"):
        ChecklistRegistry().register(
            ChecklistItem(id="bad", domain="t", action="a", target=None)
        )


def test_off_hours_items_filter():
    reg = ChecklistRegistry()
    reg.register(_item(id="normal"))
    reg.register(_item(id="night", run_outside_active_hours=True))
    assert [i.id for i in reg.off_hours_items()] == ["night"]


# ── target 解析三形态 ───────────────────────────────────────────────────────

def test_resolve_callable():
    fn = lambda payload, ctx: 1
    assert resolve_target(fn, None) is fn


def test_resolve_package_string():
    import math

    assert resolve_target("math:sqrt", None) is math.sqrt


def test_resolve_soul_entry_string():
    ctx = SimpleNamespace(soul=SimpleNamespace(run_presence_wake=lambda **kw: {"ok": True}))
    fn = resolve_target("soul:run_presence_wake", ctx)
    assert fn(session_id="t") == {"ok": True}


def test_resolve_rejects_garbage():
    with pytest.raises(ValueError):
        resolve_target("no-separator", None)
    with pytest.raises(ValueError):
        resolve_target(123, None)  # type: ignore[arg-type]


# ── 通用执行 + heavy 分流 + 避让 ────────────────────────────────────────────

def _orch(soul=None, items=()):
    orch = HeartbeatOrchestrator(soul=soul)
    orch.checklist.register_all(list(items))
    return orch


def test_execute_item_calls_registered_target_with_payload_and_ctx():
    seen = {}

    def target(payload, ctx):
        seen["payload"], seen["ctx"] = payload, ctx
        return {"did": True}

    soul = SimpleNamespace()
    orch = _orch(soul, [_item(id="t1", target=target, payload={"k": 1})])
    result = orch.execute_item(orch.checklist.all()[0])
    assert result.ok and result.detail == {"did": True}
    assert seen["payload"] == {"k": 1}
    assert isinstance(seen["ctx"], HeartbeatContext)
    assert seen["ctx"].soul is soul


def test_heavy_item_enqueued_to_worker():
    class _Worker:
        def __init__(self):
            self.q = []

        def enqueue(self, item):
            self.q.append(item)
            return True

    w = _Worker()
    soul = SimpleNamespace()
    orch = _orch(soul, [_item(id="heavy1", heavy=True)])
    orch.set_worker(w)
    results = orch.run_due()
    assert len(results) == 1 and results[0].async_enqueued
    assert [i.id for i in w.q] == ["heavy1"]


def test_avoid_when_speaking_skips_target():
    called = []

    orch = _orch(
        SimpleNamespace(),
        [_item(id="sleepy", target=lambda p, c: called.append(1) or {}, avoid_when_speaking=True)],
    )
    orch.set_vitals_provider(lambda: SimpleNamespace(speaking=True))
    result = orch.execute_item(orch.checklist.all()[0])
    assert result.ok and result.detail == {"skipped": "soul speaking"}
    assert called == []


# ── 装配：12 个默认项 + 心脏跳动 ────────────────────────────────────────────

def test_register_default_wake_items_registers_twelve_ids(soul_service):
    from agent.soul.wiring.heartbeat import register_default_wake_items

    soul_service.start()
    try:
        n = register_default_wake_items(soul_service.heartbeat, soul_service)
        assert n == 0  # 已注册（_ensure_heartbeat 时装配过），不重复覆盖
        ids = {i.id for i in soul_service.heartbeat.orchestrator.checklist.all()}
        assert ids == DEFAULT_IDS
        # 契约面：每项都有 target/heavy 声明
        for item in soul_service.heartbeat.orchestrator.checklist.all():
            assert item.target, f"{item.id} 缺 target"
            assert isinstance(item.heavy, bool)
    finally:
        soul_service.stop()


def test_heart_beats_one_tick(soul_service):
    """验收：真 SoulService 上心脏跳动一次，注册项经契约执行。"""
    soul_service.start()
    try:
        assert soul_service.heartbeat is not None
        result = soul_service.force_heartbeat_tick()
        assert result.outcome == "ok"
        assert soul_service.heartbeat.orchestrator.checklist.all()
    finally:
        soul_service.stop()


def test_heartbeat_package_has_no_domain_knowledge():
    """验收：心跳包内不得出现业务实现知识。"""
    import pathlib

    root = pathlib.Path("src/agent/soul/heartbeat")
    # 词表取"实现归位"的显著标志；module 的 presence 醒睡门控是 agent 级
    # 语义、evolution.py 是 bridge 端口胶水，均为设计内保留
    banned = ("execute_plan_landmark", "ensure_story_runtime",
              "RUN_MONTHLY_DRIFT", "FORGET_SCAN", "EvolutionCapture",
              "beats_from_dicts")
    hits = []
    for p in root.rglob("*.py"):
        if "__pycache__" in str(p):
            continue
        rel = p.relative_to(root).as_posix()
        if rel in ("bridge.py", "__init__.py"):
            # 契约叶与 facade 转发表允许出现符号名（协议面，非实现知识）
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for word in banned:
            if word in text:
                hits.append(f"{p.name}:{word}")
    assert hits == [], f"心跳包泄漏模块知识: {hits}"


# ── 第二批迁移：submit_heavy / 每日 planner-review 激活 / story 演化收编 ──

def test_submit_heavy_routes_transient_item_to_worker():
    class _Worker:
        """建模真实 SoulEvolutionWorker 的 pending 去重语义。"""

        def __init__(self):
            self.q = []
            self.pending = set()

        def enqueue(self, item):
            if item.id in self.pending:
                return False
            self.pending.add(item.id)
            self.q.append(item)
            return True

    w = _Worker()
    orch = HeartbeatOrchestrator(soul=SimpleNamespace())
    orch.set_worker(w)
    transient = _item(id="one-off", heavy=True)
    assert orch.submit_heavy(transient) is True
    assert [i.id for i in w.q] == ["one-off"]
    # pending 去重：同 id 再提交被拒（真实 worker 执行完成才释放 pending）
    assert orch.submit_heavy(transient) is False


def test_scheduler_ensure_daily_agents_entry():
    from runtime.scheduler.heartbeat import ensure_daily_agents_entry

    class _Engine:
        def __init__(self):
            self.calls = []

        def schedule_daily_planner(self, hour=8):
            self.calls.append(("planner", hour))

        def schedule_daily_review(self, hour=22):
            self.calls.append(("review", hour))

    engine = _Engine()
    ctx = SimpleNamespace(soul=None, scheduler_engine=engine)
    assert ensure_daily_agents_entry({}, ctx) == {"ensured": True}
    assert engine.calls == [("planner", 8), ("review", 22)]
    # engine 未绑定 → skip
    assert ensure_daily_agents_entry({}, SimpleNamespace(soul=None, scheduler_engine=None)) == {
        "skipped": "no scheduler engine"
    }


def test_story_maybe_submit_evolve_gates():
    from agent.soul.wiring.story import StoryRuntime

    class _Orch:
        def __init__(self):
            self.submitted = []

        def submit_heavy(self, item):
            self.submitted.append(item)
            return True

    runtime = StoryRuntime.__new__(StoryRuntime)  # 绕过重装配，只测门逻辑
    runtime._evolve_inflight = False
    runtime._soul = lambda: object()
    runtime.pool = SimpleNamespace(has_capacity=lambda: True)
    orch = _Orch()
    assert runtime.maybe_submit_evolve(orch) is True
    assert [i.id for i in orch.submitted] == ["story-evolve"]

    # 容量不足 → 不提交
    runtime.pool = SimpleNamespace(has_capacity=lambda: False)
    assert runtime.maybe_submit_evolve(orch) is False
    # inflight → 不提交
    runtime.pool = SimpleNamespace(has_capacity=lambda: True)
    runtime._evolve_inflight = True
    assert runtime.maybe_submit_evolve(orch) is False
    # soul 失联 → 不提交
    runtime._evolve_inflight = False
    runtime._soul = lambda: None
    assert runtime.maybe_submit_evolve(orch) is False
