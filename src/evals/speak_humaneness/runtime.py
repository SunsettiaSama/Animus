from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from agent.soul.presence import PresenceService
from agent.soul.speak.llm.director_engine import SpeakDirectorLLMEngine
from agent.soul.speak.llm.engine import SpeakLLMEngine
from agent.soul.speak.service import SpeakService
from agent.soul.speak.io.inbound.unit import SpeakExchange, SpeakQuestion
from agent.soul.speak.io.outbound.unit import SpeakAnswer
from agent.soul.speak.session import SpeakTurnChunk
from agent.soul.speak.responders.request_driven.layers import (
    set_eval_unit_judge as layers_set_eval_unit_judge,
)
from config.llm_core.config import LLMConfig
from infra.llm import LLM

from .persona_target import DEFAULT_PERSONA_DIR, FilePersona
from .ports import PipelinedSpeakTurnPort
from .simulation_compat import (
    CategoricalDialogueJudge,
    DialogueSimulator,
    DynamicUserSimulator,
)
from .think import StripsThinkLLM
from .unit_judge import LLMUnitJudge
from .portrait import RawLogger

RESPONDER_REQUEST_DRIVEN = "request_driven"
RESPONDER_DIRECT = "direct"
RESPONDER_RHYTHM = "rhythm"
SUPPORTED_RESPONDERS = (
    RESPONDER_REQUEST_DRIVEN,
    RESPONDER_DIRECT,
    RESPONDER_RHYTHM,
)

# 消融臂/设计臂别名 → (真实 responder, 卡片族策略)。
# rd_dir_only     = 三角色管线，提示词里只有导演/节奏卡片（剧情卡片被滤掉）
# rd_writer_only  = 三角色管线，提示词里只有编剧/剧情卡片（导演卡片被滤掉）
# rd_dynsched     = 阈值版导演调度（已被证伪，留作对照）
# rd_dynsched_llm = 导演 LLM 调度 v1：节奏卡出清，判定只见对话近况（原"宁缺毋滥"prompt）
# rd_softplot     = 软约束剧情：节奏卡出清 + 剧情卡软约束措辞 + "对方在剧情中的位置"
# direct_silence  = 直通 + 角色自主：沉默权（只回「……」）+ 自预约下一拍存入上下文
# rd_combo        = 软约束剧情 + 导演LLM调度（v1 判定）组合
# rd_combo_v2     = 软约束剧情 + 新导演（v2：喂剧情材料对齐 + 中性权衡 prompt）组合
ARM_ALIASES: dict[str, tuple[str, str]] = {
    "rd_dir_only": (RESPONDER_REQUEST_DRIVEN, "director"),
    "rd_writer_only": (RESPONDER_REQUEST_DRIVEN, "writer"),
    "rd_dynsched": (RESPONDER_REQUEST_DRIVEN, "dynsched"),
    "rd_dynsched_llm": (RESPONDER_REQUEST_DRIVEN, "dynsched_llm"),
    "rd_softplot": (RESPONDER_REQUEST_DRIVEN, "softplot"),
    "direct_silence": (RESPONDER_DIRECT, "charsilence"),
    "rd_combo": (RESPONDER_REQUEST_DRIVEN, "combo"),
    "rd_combo_v2": (RESPONDER_REQUEST_DRIVEN, "combo_v2"),
}
SUPPORTED_RUN_LABELS = tuple(SUPPORTED_RESPONDERS + tuple(ARM_ALIASES))


class RecordingLifeOutbound:
    """记录异步交付的对话拍，供空回复兜底与画像参考。"""

    def __init__(self) -> None:
        self.recorded: list[dict[str, Any]] = []

    def touch_dialogue(self, session_id: str) -> None:
        _ = session_id

    def emit_dialogue_turn(self, chunk: SpeakTurnChunk) -> None:
        self.recorded.append(
            {
                "session_id": chunk.session_id,
                "user_text": chunk.user_text,
                "agent_text": chunk.agent_text,
            }
        )

    def record_turn_exchange(self, chunk: SpeakTurnChunk) -> SpeakExchange:
        self.emit_dialogue_turn(chunk)
        return SpeakExchange(
            session_id=chunk.session_id,
            question=SpeakQuestion(text=chunk.user_text),
            answer=SpeakAnswer(text=chunk.agent_text),
        )


@dataclass
class EvalRuntime:
    """runner 依赖的评测组件集合；live 与 offline fake 各自装配。"""

    simulators: dict[str, DialogueSimulator]
    judge: CategoricalDialogueJudge
    judge_llm: Any
    raw_log: RawLogger | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def close(self) -> None:
        close = getattr(self.extras.get("service"), "stop", None)
        if callable(close):
            close()
        layers_set_eval_unit_judge(None)


def _role_config(base: LLMConfig, *, temperature: float, max_tokens: int) -> LLMConfig:
    return replace(base, temperature=temperature, max_tokens=max_tokens)


class LiveSpeakHumanenessRuntime:
    """不开完整 Soul 服务，直接装配 SpeakService（真实人格档案 + 真实 presence）。"""

    def __init__(
        self,
        *,
        llm_config_path: str,
        responders: tuple[str, ...] = (RESPONDER_REQUEST_DRIVEN, RESPONDER_DIRECT),
        judge_llm_config_path: str | None = None,
        judge_repeats: int = 3,
        seed: int = 20260915,
        persona_dir: Any = DEFAULT_PERSONA_DIR,
    ) -> None:
        if not responders:
            raise ValueError("responders must not be empty")
        unknown = [item for item in responders if item not in SUPPORTED_RUN_LABELS]
        if unknown:
            raise ValueError(f"unsupported responders: {unknown}")
        base = LLMConfig.from_yaml(llm_config_path)
        judge_base = LLMConfig.from_yaml(judge_llm_config_path or llm_config_path)
        speak_llm = LLM(_role_config(base, temperature=0.8, max_tokens=768))
        director_llm = LLM(_role_config(base, temperature=0.3, max_tokens=512))
        # 模拟器/评委是推理模型（MiniMax-M3 会吐 <think>），预算放大且出口统一剥思考块
        simulator_llm = StripsThinkLLM(
            LLM(_role_config(base, temperature=0.9, max_tokens=512))
        )
        judge_llm = StripsThinkLLM(
            LLM(_role_config(judge_base, temperature=0.2, max_tokens=3072))
        )

        persona = FilePersona(persona_dir)
        life = RecordingLifeOutbound()
        service = SpeakService(
            persona=persona,
            presence=PresenceService(),
            llm_engine=SpeakLLMEngine(speak_llm),
            director_llm_engine=SpeakDirectorLLMEngine(director_llm),
            life_outbound=life,
            life_lifecycle=None,
            keyword_wait_ms=0,
            portrait_wait_ms=0,
            typing_idle_ms=50,
        )
        service.start()

        simulators: dict[str, DialogueSimulator] = {}
        ports: dict[str, PipelinedSpeakTurnPort] = {}
        unit_judges: dict[str, LLMUnitJudge] = {}
        for responder in responders:
            base_responder, card_family = ARM_ALIASES.get(
                responder, (responder, "")
            )
            if card_family in ("dynsched_llm", "combo", "combo_v2"):
                variant = "v2" if card_family == "combo_v2" else "v1"
                judge_key = f"{base_responder}:{variant}"
                if judge_key not in unit_judges:
                    unit_judges[judge_key] = LLMUnitJudge(
                        LLM(_role_config(base, temperature=0.2, max_tokens=1024)),
                        variant=variant,
                    )
                layers_set_eval_unit_judge(unit_judges[judge_key].judge)
            port = PipelinedSpeakTurnPort(
                service,
                responder=base_responder,
                life_outbound=life,
                label=responder,
                silence_protocol=card_family == "charsilence",
            )
            ports[responder] = port
            simulators[responder] = DialogueSimulator(
                user_simulator=DynamicUserSimulator(simulator_llm),
                speak=port,
            )
        self.ground_truth = persona.ground_truth
        self.eval_runtime = EvalRuntime(
            simulators=simulators,
            judge=CategoricalDialogueJudge(judge_llm, repeats=judge_repeats, seed=seed),
            judge_llm=judge_llm,
            extras={
                "service": service,
                "life_outbound": life,
                "ports": ports,
            },
        )

    def close(self) -> None:
        self.eval_runtime.close()
