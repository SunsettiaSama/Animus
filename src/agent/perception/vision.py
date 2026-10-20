# -*- coding: utf-8 -*-
"""高成本视觉模型翻译器（占位实现）。

当前"事件→流畅自然语言"由多模态大模型完成：输入结构化事件 JSON +
现场摘要（可选画面截帧 image_b64），输出严格 JSON 的叙事包。
后续专用翻译器上线后本类退役，协议不变。

无模型/调用失败/解析失败时，逐级回退到 ``RuleNarrator``，保证
感知总线永不因翻译端故障而断流。
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from agent.perception.narrate import RuleNarrator
from agent.perception.protocol import (
    GamePerceptionEvent,
    PerceptionPacket,
    PerceptionScene,
)

if TYPE_CHECKING:
    from infra.llm import BaseLLM

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是「感知协议层」的翻译器：把游戏世界里发生的一件事，翻译成给一位"
    "生活在该世界中的角色（守灯人）所感知的自然语言记录。\n"
    "要求：\n"
    "1. 一到两句流畅的中文，第三人称描述世界与旅者（玩家），不出现任何系统术语或英文标识；\n"
    "2. 只使用输入 JSON 与画面中给出的事实，禁止编造；\n"
    "3. 带一点身体性的感受（震动、火光、风声），但不夸张；\n"
    "4. 只输出严格 JSON：{\"narrative\": str, \"emotion_label\": str(<=4字), "
    "\"salience\": 0~1, \"valence_delta\": -1~1, \"arousal_delta\": -1~1}。"
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class VisionNarrator:
    """多模态 LLM 翻译器（高成本，占位）。"""

    def __init__(
        self,
        llm: BaseLLM,
        *,
        fallback: RuleNarrator | None = None,
        model_name: str = "",
    ) -> None:
        self._llm = llm
        self._fallback = fallback or RuleNarrator()
        self._model_name = model_name or getattr(llm, "model_name", "") or "vision"

    @property
    def name(self) -> str:
        return f"vision:{self._model_name}"

    def translate(
        self,
        event: GamePerceptionEvent,
        scene: PerceptionScene | None = None,
    ) -> PerceptionPacket:
        baseline = self._fallback.translate(event, scene)
        try:
            raw = self._llm.generate_messages(self._build_messages(event, scene))
            fields = _parse_fields(str(raw))
            if not fields.get("narrative", "").strip():
                raise ValueError("视觉模型未返回 narrative")
            return PerceptionPacket(
                event=event,
                narrative=str(fields["narrative"]).strip(),
                salience=_clamp_float(fields.get("salience"), baseline.salience, 0.0, 1.0),
                emotion_label=str(fields.get("emotion_label", "") or baseline.emotion_label)[:8],
                valence_delta=_clamp_float(fields.get("valence_delta"), baseline.valence_delta, -1.0, 1.0),
                arousal_delta=_clamp_float(fields.get("arousal_delta"), baseline.arousal_delta, -1.0, 1.0),
                scene_text=baseline.scene_text,
                translator=self.name,
            )
        except Exception as exc:  # noqa: BLE001 — 翻译端故障回退规则叙事，不断流
            logger.warning("[感知协议层] 视觉翻译失败，回退规则叙事：%s", exc)
            return PerceptionPacket(
                event=event,
                narrative=baseline.narrative,
                salience=baseline.salience,
                emotion_label=baseline.emotion_label,
                valence_delta=baseline.valence_delta,
                arousal_delta=baseline.arousal_delta,
                scene_text=baseline.scene_text,
                translator=f"{self.name}(fallback:rule)",
            )

    def _build_messages(self, event: GamePerceptionEvent, scene: PerceptionScene | None) -> list:
        from langchain_core.messages import HumanMessage, SystemMessage

        parts: list[dict] = []
        prompt_lines = ["把下面这则游戏事件翻译成叙事记录。"]
        prompt_lines.append("事件 JSON：")
        prompt_lines.append(json.dumps(event.to_dict(), ensure_ascii=False))
        if scene is not None:
            prompt_lines.append(f"现场摘要：{scene.summary()}")
        parts.append({"type": "text", "text": "\n".join(prompt_lines)})
        if event.image_b64:
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{event.image_b64}"},
            })
        return [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=parts),
        ]


def _parse_fields(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    match = _JSON_RE.search(text)
    if match is None:
        return {"narrative": text}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"narrative": text}
    return data if isinstance(data, dict) else {"narrative": text}


def _clamp_float(value: object, default: float, lo: float, hi: float) -> float:
    try:
        num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, num))


def load_vision_narrator(
    *,
    config_path: str | None = None,
) -> VisionNarrator | None:
    """从 config/llm_core/vision.yaml 装配视觉翻译器；未配置/未启用返回 None。"""
    from config import paths
    from config.llm_core.vision_config import VisionLLMConfig
    from infra.llm.llm import LLM

    cfg = VisionLLMConfig.from_yaml(config_path or paths.vision_model_yaml)
    if not cfg.ready:
        return None
    from config.llm_core.config import LLMConfig

    llm_cfg = LLMConfig(
        model=cfg.model,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        backend=cfg.backend,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
        system_prompt=cfg.system_prompt,
    )
    return VisionNarrator(LLM(llm_cfg), model_name=cfg.model)
