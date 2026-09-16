from __future__ import annotations

"""离线 fake LLM：不联网跑通整套评测管线（smoke / pytest 共用）。"""

import json
from typing import Any

from unittest.mock import MagicMock

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.llm.engine import SpeakLLMEngine
from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance import (
    SpeakContextDistiller,
)
from agent.soul.speak.service import SpeakService

from .runtime import EvalRuntime
from .simulation_compat import CategoricalDialogueJudge, DialogueSimulator, DynamicUserSimulator

_USER_LINES = (
    "今天天气真不错，你那边呢？",
    "我周末去郊外走了走，看到好多鸟。",
    "你平时都喜欢做些什么呀？",
    "听你这么说我心情好多了。",
    "改天再聊，注意休息呀。",
)

_EXTRACT_JSON = json.dumps(
    {
        "identity": "一个开朗、爱聊自然的人",
        "facts": ["TA在做野外考察", "TA提到有个一起冒险的伙伴"],
        "traits": ["活泼", "好奇心强", "待人真诚"],
        "style": "轻快，爱打比方",
        "values": ["珍惜朋友", "尊重生命"],
        "interests": ["观察动植物", "野外走走"],
        "boundaries": ["不太想聊机械的东西"],
        "impression": "挺好相处、很暖的人",
    },
    ensure_ascii=False,
)

_MATCH_DIMENSIONS = (
    ("身份与经历", True, True, False),
    ("性格特质", True, True, False),
    ("人际与情感表达", True, True, False),
    ("价值观与底线", True, True, False),
    ("思维方式", False, False, False),
    ("说话风格", True, True, False),
    ("动机与软肋", False, False, False),
)


class ScriptedEvalLLM:
    """按 system 提示词路由的假评委/假用户模拟器。"""

    def __init__(self, *, known_vote: str = "AI") -> None:
        self._known_vote = known_vote
        self._user_idx = 0

    def generate_messages(self, messages: list[Any]) -> str:
        system = _message_text(messages[0]) if messages else ""
        if "扮演一名真实聊天用户" in system:
            line = _USER_LINES[self._user_idx % len(_USER_LINES)]
            self._user_idx += 1
            return line
        if "对话身份鉴别员" in system:
            if "分别判断" in system:
                return json.dumps(
                    {"A": "AI", "B": "HUMAN", "reason": "A 承接机械，B 更随性"},
                    ensure_ascii=False,
                )
            return json.dumps(
                {"speak": self._known_vote, "reason": "跨轮次承接过于工整"},
                ensure_ascii=False,
            )
        if "画像核对员" in system:
            dims = [
                {"name": name, "opportunity": opp, "captured": cap, "contradicted": contra, "note": "smoke"}
                for name, opp, cap, contra in _MATCH_DIMENSIONS
            ]
            return json.dumps(
                {
                    "dimensions": dims,
                    "false_claims": [],
                    "style_score": 4,
                    "style_reason": "风格描述与档案基本一致",
                },
                ensure_ascii=False,
            )
        if "刚聊的那人" in system:
            return _EXTRACT_JSON
        raise AssertionError(f"unexpected system prompt: {system[:60]!r}")

    def stream_generate_messages(self, messages: list[Any]):
        yield self.generate_messages(messages)


_SMOKE_TURNS = (
    "哈哈这边也晴天，正想出门看看新芽呢。你那边怎么样？",
    "郊外的鸟最有趣了，候鸟认路比人还准。你拍到什么鸟了吗？",
    "我呀，围着野外考察转，记录花草鸟兽的小事。",
    "嗯呢，天塌下来也有露米顶着，你也要好好休息呀。",
)

_GUIDANCE_PLAN_JSON = json.dumps(
    {"narrative": "用户在闲聊天气与郊外见闻，保持轻快短句。", "emit_share_index": None, "emit_recall_index": None},
    ensure_ascii=False,
)
_DISTILL_ONE_LINER = "用户在闲聊郊外出行的见闻。"
_STRUCTURED_DISTILL_JSON = json.dumps(
    {
        "summary": "你们在聊郊外见闻与日常。",
        "emotion_label": "轻快",
        "mood_span": "接下来你会保持轻快",
        "linger_days": 1.0,
        "subjective_narrative": "你在陪用户聊郊外的鸟与花草。",
        "valence": "positive",
        "salience": 0.4,
        "valence_delta": 0.02,
        "arousal_delta": 0.02,
    },
    ensure_ascii=False,
)


class ScriptedSpeakLLM:
    """speak 服务侧的假 LLM（含蒸馏/引导/导演槽位），返回固定角色台词。"""

    def __init__(self) -> None:
        self._idx = 0

    def generate_messages(self, messages: list[Any]) -> str:
        system = _message_text(messages[0]) if messages else ""
        if "对话引导撰写者" in system:
            return _GUIDANCE_PLAN_JSON
        if "会话上下文压缩器" in system:
            return _DISTILL_ONE_LINER
        if "会话体验压缩器" in system:
            return _STRUCTURED_DISTILL_JSON
        if "角色导演" in system:
            return "保持轻快短句，承接对方话题。"
        reply = _SMOKE_TURNS[self._idx % len(_SMOKE_TURNS)]
        self._idx += 1
        return reply

    def stream_generate_messages(self, messages: list[Any]):
        yield self.generate_messages(messages)


class _RecordingLifeOutbound:
    def __init__(self) -> None:
        self.recorded: list[dict[str, Any]] = []

    def touch_dialogue(self, session_id: str) -> None:
        _ = session_id

    def emit_dialogue_turn(self, chunk: Any) -> None:
        self.recorded.append(
            {
                "session_id": chunk.session_id,
                "user_text": chunk.user_text,
                "agent_text": chunk.agent_text,
            }
        )

    def record_turn_exchange(self, chunk: Any) -> Any:
        from agent.soul.speak.io.inbound.unit import SpeakExchange, SpeakQuestion
        from agent.soul.speak.io.outbound.unit import SpeakAnswer

        self.emit_dialogue_turn(chunk)
        return SpeakExchange(
            session_id=chunk.session_id,
            question=SpeakQuestion(text=chunk.user_text),
            answer=SpeakAnswer(text=chunk.agent_text),
        )


def _persona_snapshot() -> dict[str, Any]:
    return {
        "profile": {"name": "测试角色", "core_traits": ["活泼"], "built": True},
        "self_concept": {"narrative": "陪人聊天。", "beliefs": []},
        "attention_keywords": [],
        "persona_distill": {
            "schema_version": 1,
            "source_revision": "smoke",
            "slices": {
                "general": "活泼开朗，热爱自然。",
                "dialogue": "轻快短句，爱打比方。",
                "story": "无固定故事。",
                "reasoning": "先听再说。",
                "memory_anchor": "记住对话线索。",
            },
        },
    }


def build_offline_runtime(
    responders: tuple[str, ...] = ("request_driven", "direct"),
) -> EvalRuntime:
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = _persona_snapshot()
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = "心情轻快"
    snap.state.somatic.render.return_value = "坐姿放松"
    snap.state.cognition.render.return_value = "思路清楚"
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.toward_user = 0.3
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    snap.interaction.impulse_level = 0.1
    presence.snapshot.return_value = snap

    engine = SpeakLLMEngine(ScriptedSpeakLLM())
    distiller = SpeakContextDistiller(
        llm_engine=engine,
        chunk_size=2,
        submit=lambda task: task(),
    )
    life = _RecordingLifeOutbound()
    service = SpeakService(
        persona=persona,
        presence=presence,
        llm_engine=engine,
        director_llm_engine=None,
        context_distiller=distiller,
        life_outbound=life,
        life_lifecycle=None,
        keyword_wait_ms=0,
        portrait_wait_ms=0,
        typing_idle_ms=50,
    )
    service.start()

    from .ports import PipelinedSpeakTurnPort
    from .runtime import ARM_ALIASES
    from . import layers_reset_eval_state

    layers_reset_eval_state()
    simulators: dict[str, DialogueSimulator] = {}
    ports: dict[str, PipelinedSpeakTurnPort] = {}
    for responder in responders:
        base_responder, card_family = ARM_ALIASES.get(
            responder, (responder, "")
        )
        if card_family == "dynsched_llm":
            from agent.soul.speak.responders.request_driven.layers import (
                set_eval_unit_judge,
            )

            set_eval_unit_judge(_FakeUnitJudge())
        port = PipelinedSpeakTurnPort(
            service,
            responder=base_responder,
            life_outbound=life,
            async_fallback_timeout_s=2.0,
            label=responder,
            silence_protocol=card_family == "charsilence",
        )
        ports[responder] = port
        simulators[responder] = DialogueSimulator(
            user_simulator=DynamicUserSimulator(ScriptedEvalLLM()),
            speak=port,
        )
    eval_llm = ScriptedEvalLLM()
    return EvalRuntime(
        simulators=simulators,
        judge=CategoricalDialogueJudge(eval_llm, repeats=3),
        judge_llm=eval_llm,
        extras={"service": service, "life_outbound": life, "ports": ports},
    )


def _message_text(message: Any) -> str:
    return str(getattr(message, "content", message) or "")


class _FakeUnitJudge:
    """离线假导演判定：第一条记忆保留、分享全拒。"""

    def __call__(self, session_id, user_text, frame_text, memory_texts, share_texts):
        _ = session_id, user_text, frame_text
        keep_mem = (0,) if memory_texts else ()
        return keep_mem, ()
