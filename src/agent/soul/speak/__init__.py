from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, tuple[str, str]] = {
    "SpeakPromptBundle": ("agent.soul.speak.orchestrator", "SpeakPromptBundle"),
    "SpeakOrchestrator": ("agent.soul.speak.orchestrator", "SpeakOrchestrator"),
    "SpeakReplyStyle": ("agent.soul.speak.orchestrator.blocks.system", "SpeakReplyStyle"),
    "SpeakContextDistiller": ("agent.soul.speak.orchestrator.blocks.guidance", "SpeakContextDistiller"),
    "SpeakOutputFormat": ("agent.soul.speak.orchestrator.blocks.system", "SpeakOutputFormat"),
    "SpeakDriveBridge": ("agent.soul.speak.drive", "SpeakDriveBridge"),
    "SpeakDriveResult": ("agent.soul.speak.drive", "SpeakDriveResult"),
    "SpeakDriveSnapshot": ("agent.soul.speak.drive", "SpeakDriveSnapshot"),
    "SpeakAction": ("agent.soul.speak.io", "SpeakAction"),
    "SpeakAnswer": ("agent.soul.speak.io", "SpeakAnswer"),
    "SpeakDeliverResult": ("agent.soul.speak.io", "SpeakDeliverResult"),
    "SpeakDialogueBridge": ("agent.soul.speak.io", "SpeakDialogueBridge"),
    "SpeakExchange": ("agent.soul.speak.io", "SpeakExchange"),
    "SpeakIngestResult": ("agent.soul.speak.io", "SpeakIngestResult"),
    "SpeakOutboundRouter": ("agent.soul.speak.io", "SpeakOutboundRouter"),
    "SpeakPresenceOutbound": ("agent.soul.speak.io", "SpeakPresenceOutbound"),
    "SpeakQuestion": ("agent.soul.speak.io", "SpeakQuestion"),
    "SpeakRequest": ("agent.soul.speak.io", "SpeakRequest"),
    "SpeakHandler": ("agent.soul.speak.io.handler", "SpeakHandler"),
    "SpeakLLMEngine": ("agent.soul.speak.llm", "SpeakLLMEngine"),
    "SpeakLLMResult": ("agent.soul.speak.llm", "SpeakLLMResult"),
    "SpeakDrivePort": ("agent.soul.speak.ports", "SpeakDrivePort"),
    "SpeakInboundPort": ("agent.soul.speak.ports", "SpeakInboundPort"),
    "SpeakLLMPort": ("agent.soul.speak.ports", "SpeakLLMPort"),
    "SpeakOrchestratorPort": ("agent.soul.speak.ports", "SpeakOrchestratorPort"),
    "SpeakOutboundPort": ("agent.soul.speak.ports", "SpeakOutboundPort"),
    "SpeakStreamPort": ("agent.soul.speak.ports", "SpeakStreamPort"),
    "SpeakToolPort": ("agent.soul.speak.ports", "SpeakToolPort"),
    "SpeakService": ("agent.soul.speak.service", "SpeakService"),
    "SpeakTurnResult": ("agent.soul.speak.service", "SpeakTurnResult"),
    "ResolvedFeeling": ("agent.soul.speak.session", "ResolvedFeeling"),
    "SpeakFeelingChunk": ("agent.soul.speak.session", "SpeakFeelingChunk"),
    "SpeakSessionRegistry": ("agent.soul.speak.session", "SpeakSessionRegistry"),
    "SpeakSubjectiveChunk": ("agent.soul.speak.session", "SpeakSubjectiveChunk"),
    "SpeakTurnChunk": ("agent.soul.speak.session", "SpeakTurnChunk"),
    "TopicShiftSemanticBoundary": ("agent.soul.speak.session", "TopicShiftSemanticBoundary"),
    "resolve_feeling": ("agent.soul.speak.session", "resolve_feeling"),
    "resolve_subjective": ("agent.soul.speak.session", "resolve_subjective"),
    "SPEAK_PARSE_FIELDS": ("agent.soul.speak.io.outbound.stream", "SPEAK_PARSE_FIELDS"),
    "SpeakAgentOutput": ("agent.soul.speak.io.outbound.stream", "SpeakAgentOutput"),
    "SpeakStreamEvent": ("agent.soul.speak.io.outbound.stream", "SpeakStreamEvent"),
    "SpeakStreamPipeline": ("agent.soul.speak.io.outbound.stream", "SpeakStreamPipeline"),
    "parse_agent_output": ("agent.soul.speak.io.outbound.stream", "parse_agent_output"),
    "build_anchor_request": ("agent.soul.speak.tools.anchor", "build_anchor_request"),
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> Any:
    spec = _LAZY.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(spec[0])
    return getattr(mod, spec[1])
