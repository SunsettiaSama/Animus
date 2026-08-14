from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.soul.life.experience.domain.anchor_codec import (
    AnchorUnitContext,
    InteractionDirection,
    stamp_anchor_context,
)
from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.memory.graph.networks.types import ExperienceKind
from agent.soul.memory.graph.node.create.experience import ExperienceIngestResult
from agent.soul.memory.io.life.channel import LifeMemoryChannel
from agent.soul.memory.io.life.deps import LifeIODeps
from agent.soul.memory.io.life.mode import MemoryIngestMode
from agent.soul.memory.io.life.request import ExperienceIngestInbound
from agent.soul.memory.io.life.sleep_filter import (
    SleepFilterChannel,
    SleepFilterConfig,
    SleepFilterDecision,
)
from agent.soul.memory.sleep.service import SleepService
from agent.soul.memory.sleep.types import SleepConfig, SleepResult
from config.soul.memory.service_config import MemoryServiceConfig


def _unit(
    *,
    source: str = "user",
    action_kind: ExperienceActionKind = ExperienceActionKind.speaking,
    perception: str = "用户提到今天开会",
    narration: str = "你记录了一次会议安排",
    content: str = "好的，我会记住这次会议",
    salience: float = 0.5,
    evidence: dict | None = None,
    prior_thought: str = "",
) -> ExperienceUnit:
    return ExperienceUnit(
        situation=ExperienceSituation(
            session_id="tao",
            perception=perception,
            narration=narration,
            prior_thought=prior_thought,
        ),
        action=ExperienceAction(kind=action_kind, content=content),
        feeling=ExperienceFeeling(salience=salience, emotion_label="平静"),
        source=source,
        evidence=dict(evidence or {}),
    )


def test_sleep_filter_passes_anchored_user_experience():
    channel = SleepFilterChannel()
    unit = _unit()
    stamp_anchor_context(
        unit,
        AnchorUnitContext(
            direction=InteractionDirection.inbound,
            session_id="tao",
            interactor_id="user-1",
        ),
    )
    result = channel.screen(ExperienceIngestInbound(unit=unit, interactor_id="user-1"))
    assert result.decision is SleepFilterDecision.pass_
    assert result.allowed is True


def test_sleep_filter_rejects_unanchored_internal_hallucination():
    channel = SleepFilterChannel(
        SleepFilterConfig(reject_unanchored_internal_thought=True)
    )
    unit = _unit(
        source="heartbeat",
        action_kind=ExperienceActionKind.reasoning,
        perception="",
        narration="也许昨天发生了一场秘密会面",
        content="我猜对方其实在隐瞒什么",
        evidence={},
    )
    result = channel.screen(ExperienceIngestInbound(unit=unit))
    assert result.decision is SleepFilterDecision.reject
    assert result.reason == "unanchored_internal_hallucination"


def test_life_channel_reject_skips_create_nodes_and_rumination():
    rumination = MagicMock()
    deps = LifeIODeps(
        event=MagicMock(),
        social=MagicMock(),
        rumination=rumination,
        session_compression=MagicMock(),
        enqueue_write=lambda fn: fn(),
        agent_persona_narrative=lambda: "",
        llm=None,
        sleep_filter=SleepFilterChannel(),
    )
    channel = LifeMemoryChannel(deps)
    channel._formal = MagicMock()
    unit = _unit(
        source="system",
        action_kind=ExperienceActionKind.reasoning,
        perception="",
        narration="仿佛听见了并不存在的铃声",
        content="不确定这是不是真的",
        evidence={},
    )
    ack = channel.ingest_experience(ExperienceIngestInbound(unit=unit))
    assert ack.node_ids == []
    assert ack.mode is MemoryIngestMode.formal
    assert ack.route_reason == "unanchored_internal_hallucination"
    assert ack.network == ""
    channel._formal.create_nodes.assert_not_called()
    rumination.observe_node.assert_not_called()


def test_life_channel_pass_creates_nodes_and_observes_rumination():
    rumination = MagicMock()
    deps = LifeIODeps(
        event=MagicMock(),
        social=MagicMock(),
        rumination=rumination,
        session_compression=MagicMock(),
        enqueue_write=lambda fn: fn(),
        agent_persona_narrative=lambda: "persona",
        llm=None,
        sleep_filter=SleepFilterChannel(),
    )
    channel = LifeMemoryChannel(deps)
    node = SimpleNamespace(id="node-1")
    channel._formal = MagicMock()
    channel._formal.create_nodes.return_value = ExperienceIngestResult(
        network=ExperienceKind.event,
        reason="routed",
        nodes=[node],
    )
    unit = _unit(
        source="user",
        evidence={"user_text": "今天开会吗？"},
    )
    ack = channel.ingest_experience(
        ExperienceIngestInbound(unit=unit, interactor_id="user-1")
    )
    assert ack.node_ids == ["node-1"]
    assert ack.route_reason == "routed"
    channel._formal.create_nodes.assert_called_once()
    rumination.observe_node.assert_called_once_with("node-1")


def test_existing_sleep_service_still_runs_consolidation_steps():
    event = MagicMock()
    social = MagicMock()
    emergence = MagicMock()
    rumination = MagicMock()
    buffer = MagicMock()
    buffer.decay_and_prune.return_value = 2
    buffer.__len__ = MagicMock(return_value=3)
    rumination.buffer = buffer
    event.forget_scan.return_value = ["e1"]
    social.forget_scan.return_value = ["s1"]
    rumination.consolidate_from_sleep.return_value = (1, ["e1"])
    service = SleepService(
        event,
        social,
        emergence,
        rumination,
        MemoryServiceConfig(),
        sleep_cfg=SleepConfig(),
    )
    result = service.run(tick_id="t1", dry_run=False)
    assert isinstance(result, SleepResult)
    assert result.forgotten_ids == ["e1", "s1"]
    assert result.cluster_rebuilt is True
    assert result.rumination_fed == 1
    assert result.buffer_pruned == 2
    assert result.buffer_size == 3
    event.forget_scan.assert_called_once()
    social.forget_scan.assert_called_once()
    emergence.spread.schedule_cluster_rebuild.assert_called_once()
    rumination.consolidate_from_sleep.assert_called_once()
    buffer.decay_and_prune.assert_called_once()
