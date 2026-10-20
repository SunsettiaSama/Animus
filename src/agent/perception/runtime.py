# -*- coding: utf-8 -*-
"""进程内嵌装配：感知协议层 ⇄ soul（lite / full 两种形态）。

lite：PresenceService + LifeExperienceStack + 真 SpeakService（SpeakLLMEngine
可接脚本 LLM 或真模型）——离线可跑、可测试，NPC 台词与 life 入账走的是
**生产同一批组件**，只省去 Memory/Persona/Heartbeat 等重型基建。

full：SoulService（webui 生产形态）。写入走 ``ingest_game_perception``，
读取走 ``attach_game_event_briefs`` + ``register_speak_context_provider``
（见 ``attach_full_soul``）。
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agent.perception.bus import PerceptionBus
from agent.perception.protocol import (
    GameEventKind,
    GamePerceptionEvent,
    PerceptionPacket,
    PerceptionScene,
    PerceptionTranslator,
)
from agent.perception.speak_provider import GameContextProvider

logger = logging.getLogger(__name__)


# ── 守灯人 · 烛：lite 模式的静态人格切片 ─────────────────────────────────────

_LAMPKEEPER_DIALOGUE = (
    "你是守灯人·烛，常年守在幽暗矿脉入口的那盏灯台旁。你说话慢、句子短，"
    "像添灯芯一样一个字一个字往外给。你见过很多旅者经过，不惊讶、不多问，"
    "但记得每一张脸和他们的伤痕。你关心火、路和活着回来的人，别的都不急。"
)


def lampkeeper_persona_snapshot() -> dict:
    from agent.soul.persona.distill.schema import PERSONA_DISTILL_SCHEMA_VERSION

    return {
        "profile": {"name": "守灯人·烛", "core_traits": ["沉静", "守夜", "记性好"], "built": True, "built_at": "perception"},
        "self_concept": {"narrative": "我是守灯人，守着矿脉入口的火。", "beliefs": []},
        "attention_keywords": [],
        "persona_distill": {
            "schema_version": PERSONA_DISTILL_SCHEMA_VERSION,
            "source_revision": "perception|lampkeeper",
            "distilled_at": "2026-01-01T00:00:00+00:00",
            "source_snapshot": "【规范化人格画像】\n你是守灯人·烛。\n",
            "slices": {
                "general": "守灯人·烛：沉静、守夜",
                "dialogue": _LAMPKEEPER_DIALOGUE,
                "story": "守灯人守着矿脉的火，看旅者来了又走。",
                "reasoning": "先看火，再看人",
                "memory_anchor": "你习惯把每个路过的旅者记在心里。",
                "director": "守灯人·烛：慢而稳，短句，不催促。",
            },
        },
    }


# ── 离线脚本 LLM（测试/演示；上下文关键词分流） ─────────────────────────────

class ScriptedNpcLLM:
    """离线占位大脑：按提示词里的游戏线索给出守灯人口吻的台词。"""

    _CUES = [
        (("魔像", "击败"), "矿脉深处的魔像……它的震波曾是这洞里最沉的心跳。它睡了，火都稳了些。"),
        (("星核守望者", "守望者"), "守望者守着圣殿那么多年，也该有人上去跟它说句话了。"),
        (("星门", "星辉", "通关"), "星门开了啊。风从高处下来了……你去过的地方，比我的灯照得到的远得多。"),
        (("陨落", "倒下"), "灯台的火记得你倒下的次数，也记得你每一次回来。歇口气再走。"),
        (("灯台", "点亮"), "这点火不算什么。但路黑的时候，它够用了。"),
        (("疾行之靴", "冲刺"), "脚步声变了——快得像矿道里的风。是那双靴子吧。"),
        (("星羽", "二段跳"), "你身上落了星羽的灰。高处的风，是不是凉的？"),
        (("受伤", "生命只剩"), "血渗进矿渣里了。慢些走，洞里的东西不追悔恨，只追血味。"),
    ]
    _DEFAULTS = [
        "风把矿尘吹起来了。……你有话想说？我听着。",
        "火还稳。你放心去。",
        "（他拨了拨灯芯，没有立刻说话。）……路上看见什么，回来说给我听。",
    ]

    def __init__(self) -> None:
        self._turn = 0

    def _reply(self, context_text: str) -> str:
        for keys, line in self._CUES:
            if any(k in context_text for k in keys):
                return line
        line = self._DEFAULTS[self._turn % len(self._DEFAULTS)]
        self._turn += 1
        return line

    def generate_messages(self, messages) -> str:
        context_text = "".join(
            str(getattr(m, "content", "") or "") for m in messages
        )
        # speak 管线主协议是成对 <speak> 标签（见角色系统提示词）
        return f"<speak>{self._reply(context_text)}</speak>"

    def stream_generate_messages(self, messages):
        yield from self.generate_messages(messages)


# ── speak → life 出站：NPC 对话记入真实生命经验 ─────────────────────────────

class LifeStackSpeakOutbound:
    """SpeakLifeOutboundBridge 实现：对话轮次 → LifeExperienceStack。"""

    def __init__(self, stack, *, salience: float = 0.35) -> None:
        self._stack = stack
        self._salience = salience

    def touch_dialogue(self, session_id: str) -> None:
        _ = session_id

    def emit_dialogue_turn(self, chunk) -> None:
        from agent.soul.speak.session import feeling_self_narration, resolve_feeling

        resolved = resolve_feeling(chunk)
        self._stack.record_dialogue_turn(
            session_id=chunk.session_id,
            user_text=chunk.user_text,
            agent_text=chunk.agent_text,
            salience=resolved.salience,
            salience_note=feeling_self_narration(chunk.feeling),
            emotion_label=resolved.emotion_label,
            valence_delta=resolved.valence_delta,
            arousal_delta=resolved.arousal_delta,
            proactive_intent_id=chunk.proactive_intent_id,
            activated_memory_ids=list(chunk.activated_memory_ids),
        )

    def record_turn_exchange(self, chunk):
        from agent.soul.speak.io.inbound.unit import SpeakAnswer, SpeakExchange, SpeakQuestion
        from agent.soul.speak.session import resolve_subjective

        self.emit_dialogue_turn(chunk)
        return SpeakExchange(
            session_id=chunk.session_id,
            question=SpeakQuestion(text=chunk.user_text),
            answer=SpeakAnswer(text=chunk.agent_text),
            subjective=resolve_subjective(chunk),
            feeling=chunk.feeling,
        )


# ── lite 运行时 ──────────────────────────────────────────────────────────────

@dataclass
class LiteSoulRuntime:
    """离线可跑的最小 soul：真 Presence/Life/Speak 组件 + 可换 LLM。"""

    presence: object
    stack: object                    # LifeExperienceStack
    speak: object                    # SpeakService
    bus: PerceptionBus
    npc_name: str = "守灯人"
    session_id: str = "starfall-npc"
    channel_id: str = "starfall"

    def speak_turn(self, session_id: str, user_text: str) -> str:
        result = self.speak.run_turn(session_id, user_text, stream=False)
        return str(getattr(result, "answer", "") or "")

    def life_sink(self, packet: PerceptionPacket):
        return self.stack.ingest_game_beat(
            packet.to_beat(session_id=self.session_id, channel_id=self.channel_id)
        )


def build_lite_runtime(
    life_dir: str | Path,
    *,
    llm=None,
    translator: PerceptionTranslator | None = None,
    session_id: str = "starfall-npc",
    channel_id: str = "starfall",
    npc_name: str = "守灯人",
) -> LiteSoulRuntime:
    """组装 lite 运行时（默认脚本 LLM，可传入真 BaseLLM）。"""
    from agent.soul.life.experience import LifeExperienceStack
    from agent.soul.life.virtual.chronicle import VirtualChronicleStore
    from agent.soul.presence.service import PresenceService
    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from agent.soul.speak.responders.request_driven.orchestrator import SpeakOrchestrator
    from agent.soul.speak.service import SpeakService

    life_path = str(Path(life_dir))
    presence = PresenceService(life_dir=life_path)
    stack = LifeExperienceStack(
        life_path,
        virtual_chronicle=VirtualChronicleStore(life_path),
    )
    stack.bind_presence(presence)

    class _PersonaPort:
        def __init__(self, snapshot: dict) -> None:
            self._snapshot = snapshot

        def get_persona_snapshot(self, session_id: str = "", **kwargs) -> dict:
            _ = session_id, kwargs
            return self._snapshot

    persona = _PersonaPort(lampkeeper_persona_snapshot())
    engine = SpeakLLMEngine(llm or ScriptedNpcLLM())
    speak = SpeakService(
        persona=persona,
        presence=presence,
        llm_engine=engine,
        orchestrator=SpeakOrchestrator(persona, presence),
        life_outbound=LifeStackSpeakOutbound(stack),
        life_lifecycle=None,
        keyword_wait_ms=0,
        portrait_wait_ms=0,
    )

    runtime = LiteSoulRuntime(
        presence=presence,
        stack=stack,
        speak=speak,
        bus=None,  # type: ignore[arg-type] — 下面装配
        npc_name=npc_name,
        session_id=session_id,
        channel_id=channel_id,
    )
    runtime.bus = PerceptionBus(translator, life_sink=runtime.life_sink)
    bus = runtime.bus
    # speak 侧读取：life 事件口（游戏亲历）+ 环境材料 provider
    speak.attach_life_event_port(bus.game_event_briefs)
    speak.register_context_provider(GameContextProvider(bus.store, world_name="星陨之痕"))
    return runtime


# ── full SoulService 适配 ────────────────────────────────────────────────────

def attach_full_soul(
    soul,
    bus: PerceptionBus,
    *,
    session_id: str = "starfall-npc",
    channel_id: str = "starfall",
) -> Callable[[str, str], str]:
    """把感知总线挂到生产 SoulService 上；返回 speak_turn 适配器。"""
    soul.attach_game_event_briefs(bus.game_event_briefs)
    soul.register_speak_context_provider(GameContextProvider(bus.store, world_name="星陨之痕"))

    def life_sink(packet: PerceptionPacket):
        return soul.ingest_game_perception(
            packet.to_beat(session_id=session_id, channel_id=channel_id)
        )

    bus.bind_life_sink(life_sink)

    def speak_turn(sid: str, user_text: str) -> str:
        result = soul.speak_run_turn(sid, user_text, stream=False)
        return str(getattr(result, "answer", "") or "")

    return speak_turn


# ── e2e 驱动：bridge 消息 → 感知总线 → NPC 应答 ─────────────────────────────

@dataclass
class BridgeRunSummary:
    events: Counter = field(default_factory=Counter)
    packets: list[str] = field(default_factory=list)
    npc_lines: list[str] = field(default_factory=list)
    reactive_lines: list[str] = field(default_factory=list)
    errors: int = 0


def drive_bridge(
    *,
    bridge,
    bus: PerceptionBus,
    npc_bridge,
    on_packet: Callable[[PerceptionPacket], None] | None = None,
    reactive_kinds: frozenset[str] = frozenset({GameEventKind.boss_defeated.value}),
    reactive_cooldown_sec: float = 8.0,
) -> BridgeRunSummary:
    """消费 harness 消息流直到 done：事件入总线、npc_talk 应答、大事件主动一句。"""
    import time

    summary = BridgeRunSummary()
    scene: PerceptionScene | None = None
    last_reactive = 0.0

    if not bridge.running:
        bridge.start()

    def publish_event(msg: dict) -> PerceptionPacket:
        event = GamePerceptionEvent.from_dict(msg)
        packet = bus.publish_event(event, scene)
        summary.events[event.kind.value] += 1
        summary.packets.append(packet.narrative)
        if on_packet is not None:
            try:
                on_packet(packet)
            except Exception:  # noqa: BLE001
                pass
        return packet

    for msg in bridge.messages():
        mtype = str(msg.get("type", ""))
        if mtype == "scene":
            scene = PerceptionScene.from_dict(msg)
            bus.publish_scene(scene)
            continue
        elif mtype == "npc_wait":
            continue
        elif mtype == "done":
            summary.errors = int(msg.get("errors", 0) or 0)
            break
        elif mtype != "event":
            continue

        kind = str(msg.get("kind", ""))
        if kind == GameEventKind.npc_talk.value:
            publish_event(msg)
            line = npc_bridge.handle_talk(dict(msg.get("detail") or {}))
            if not line:
                line = "……（他沉默着，往火里添了一根灯芯。）"
            summary.npc_lines.append(line)
            bridge.send_npc_line(npc_bridge.npc_name, line)
            publish_event({
                "kind": GameEventKind.npc_line.value,
                "ts": "",  # bus 打点
                "detail": {"npc_name": npc_bridge.npc_name, "text": line},
            })
        elif kind in reactive_kinds and (time.monotonic() - last_reactive) >= reactive_cooldown_sec:
            packet = publish_event(msg)
            remark = npc_bridge.reactive_remark(packet)
            if remark:
                last_reactive = time.monotonic()
                summary.reactive_lines.append(remark)
                bridge.send_npc_line(npc_bridge.npc_name, remark, mode="toast")
        else:
            publish_event(msg)
    return summary
