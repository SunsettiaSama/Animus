"""vitals 系统测试：探针容错 → 折叠正确 → 策略纯函数 → 行为接线。

全部假件、秒级；与 survival（线程存活）/ integration（真 SoulService）互补。
"""

from __future__ import annotations

from types import SimpleNamespace

from agent.soul.heartbeat.inject_mailbox import HeartbeatInjectMailbox
from agent.soul.heartbeat.policy import (
    FAILING_THRESHOLD,
    judge_liveness,
    may_sleep,
    should_offer_inject,
)
from agent.soul.heartbeat.probe import (
    EvolutionWorkerProbe,
    HeartbeatSelfProbe,
    PresenceProbe,
    SoulProbe,
    SpeakProbe,
)
from agent.soul.heartbeat.runtime.core_service import HeartbeatCoreService
from agent.soul.heartbeat.runtime.module import HeartbeatModule
from agent.soul.heartbeat.tick_log import HeartbeatTickResult
from agent.soul.heartbeat.vitals import VitalsBuilder
from agent.soul.heartbeat.vitals.snapshot import SoulVitals


def _vitals(**overrides) -> SoulVitals:
    base = dict(
        ts="2026-09-22T00:00:00+00:00",
        speaking=False,
        typing=False,
        awake=True,
        evolving=False,
        heartbeat_failures=0,
        thread_alive=True,
        inject_pending=False,
        unknown_parts=(),
    )
    base.update(overrides)
    return SoulVitals(**base)


# ── L1 探针：绝不抛异常 ──────────────────────────────────────────────────────

def test_probe_swallows_exception_and_marks_unknown():
    class _Boom(SoulProbe):
        name = "boom"

        def _sample(self):
            raise RuntimeError("部位炸了")

    reading = _Boom().sample()
    assert reading.ok is False
    assert reading.name == "boom"


def test_speak_probe_reads_aggregate_ports():
    soul = SimpleNamespace(speak=SimpleNamespace(any_busy=lambda: True, any_typing=lambda: False))
    reading = SpeakProbe(soul).sample()
    assert reading.ok is True
    assert reading.fields == {"speaking": True, "typing": False}


def test_probes_mark_unwired_parts_unknown():
    empty = VitalsBuilder.default(soul=None, worker=None, core=None)
    snap = empty.snapshot()
    assert set(snap.unknown_parts) == {"speak", "presence", "evolution_worker", "heartbeat"}
    # 部位缺失不产生假值以外的污染：默认值即"安静"事实
    assert snap.speaking is False and snap.thread_alive is True


def test_worker_probe_evolving_requires_running_and_work():
    idle = EvolutionWorkerProbe(
        SimpleNamespace(status=lambda: {"state": "running", "queued": 0, "pending_item_ids": []})
    )
    busy = EvolutionWorkerProbe(
        SimpleNamespace(status=lambda: {"state": "running", "queued": 1, "pending_item_ids": []})
    )
    assert idle.sample().fields["evolving"] is False
    assert busy.sample().fields["evolving"] is True


def test_self_probe_reads_core_health_ports():
    mailbox = HeartbeatInjectMailbox()
    mailbox.offer("待注入")
    core = SimpleNamespace(
        consecutive_failures=2,
        is_running=True,
        mailbox=mailbox,
        deferred_pending=False,
    )
    fields = HeartbeatSelfProbe(core).sample().fields
    assert fields["consecutive_failures"] == 2
    assert fields["thread_alive"] is True
    assert fields["inject_pending"] is True


# ── L2 折叠：读数 → 变量 ────────────────────────────────────────────────────

def test_builder_folds_readings_and_unknowns():
    builder = VitalsBuilder()
    builder.register(SpeakProbe(SimpleNamespace(
        speak=SimpleNamespace(any_busy=lambda: True, any_typing=lambda: True)
    )))
    builder.register(PresenceProbe(SimpleNamespace(presence=SimpleNamespace(is_awake=lambda: False))))

    class _BoomEvolution(SoulProbe):
        name = "evolution_worker"

        def _sample(self):
            raise RuntimeError("worker 失联")

    builder.register(_BoomEvolution())

    snap = builder.snapshot()
    assert snap.speaking is True and snap.typing is True
    assert snap.awake is False
    assert snap.unknown_parts == ("evolution_worker",)


# ── L3 策略：纯函数 ─────────────────────────────────────────────────────────

def test_inject_policy_defers_while_speaking():
    assert should_offer_inject(_vitals(speaking=True)) == (False, "soul speaking")
    assert should_offer_inject(_vitals(speaking=False)) == (True, "")
    assert should_offer_inject(None) == (True, "")  # 体征不可得 → 放行


def test_sleep_policy_defers_while_speaking():
    assert may_sleep(_vitals(speaking=True)) == (False, "soul speaking")
    assert may_sleep(_vitals(speaking=False)) == (True, "")
    assert may_sleep(None) == (True, "")


def test_liveness_thresholds():
    assert judge_liveness(_vitals()) == "ok"
    assert judge_liveness(_vitals(heartbeat_failures=1)) == "degraded"
    assert judge_liveness(_vitals(thread_alive=False)) == "degraded"
    assert judge_liveness(_vitals(heartbeat_failures=FAILING_THRESHOLD)) == "failing"
    assert judge_liveness(_vitals(unknown_parts=("heartbeat",))) == "degraded"
    assert judge_liveness(None) == "degraded"


# ── 行为接线 ─────────────────────────────────────────────────────────────────

class _OkHeartbeat:
    """module 替身：带可注入 vitals。"""

    def __init__(self, cfg, vitals=None):
        self._cfg = cfg
        self._soul = None
        self._vitals_value = vitals

    def vitals(self):
        if self._vitals_value is None:
            raise RuntimeError("无体征")
        return self._vitals_value

    def tick(self):
        return HeartbeatTickResult(outcome="ok", reason="test", detail_for_inject="待注入摘要")


def _always_open_cfg(**overrides):
    base = dict(poll_interval_sec=5, active_hours_start="", active_hours_end="")
    base.update(overrides)
    from agent.soul.heartbeat.config import SoulHeartbeatConfig

    return SoulHeartbeatConfig(**base)


def test_core_iteration_defers_inject_while_speaking():
    hb = _OkHeartbeat(_always_open_cfg(), vitals=_vitals(speaking=True))
    core = HeartbeatCoreService(hb, register_global_mailbox=False)
    core._iteration()
    assert core.mailbox.take_for_prompt() is None      # 未注入
    assert core.deferred_pending is True               # 暂存待下轮


def test_core_iteration_injects_when_idle():
    hb = _OkHeartbeat(_always_open_cfg(), vitals=_vitals(speaking=False))
    core = HeartbeatCoreService(hb, register_global_mailbox=False)
    core._iteration()
    assert core.mailbox.take_for_prompt() == "待注入摘要"


def test_core_iteration_survives_vitals_failure():
    hb = _OkHeartbeat(_always_open_cfg(), vitals=None)  # vitals() 抛异常
    core = HeartbeatCoreService(hb, register_global_mailbox=False)
    core._iteration()  # 体征读失败 → 按无体征放行，不炸
    assert core.mailbox.take_for_prompt() == "待注入摘要"


def test_module_vitals_and_orchestrator_sleep_avoidance(tmp_path):
    module = HeartbeatModule(
        cfg=_always_open_cfg(),
        log_dir=str(tmp_path),
        llm_cfg_path="config/llm_core/config.yaml",
    )
    # soul 假件：presence 睡着→醒着说话中，验证入睡避让
    calls = []
    soul = SimpleNamespace(
        is_running=True,
        presence=SimpleNamespace(is_awake=lambda: True),
        run_presence_wake=lambda: calls.append("wake"),
        run_presence_sleep=lambda: calls.append("sleep"),
        speak=SimpleNamespace(any_busy=lambda: True, any_typing=lambda: False),
        config=SimpleNamespace(),
    )
    module.set_soul_service(soul)

    snap = module.vitals()
    assert snap.speaking is True          # speak 探针读到 any_busy
    assert snap.unknown_parts == ("heartbeat",)  # core 尚未回填

    # 活跃时段外 + speaking → 不允许入睡（冻结时段判定，保证确定性）
    module._in_active_hours = lambda: False
    module.tick()
    assert calls == []                    # sleep 被避让，wake 也没发生（已醒）

    # core 回填后 self 探针可读
    core = HeartbeatCoreService(module, register_global_mailbox=False)
    module.attach_core_service(core)
    snap = module.vitals()
    assert snap.unknown_parts == ()
    assert snap.thread_alive is False     # core 未 start（构造即探，不启线程）
