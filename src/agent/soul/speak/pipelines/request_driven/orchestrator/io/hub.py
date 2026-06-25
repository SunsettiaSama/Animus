from __future__ import annotations

from .inbound.guidance import InboundGuidanceGateway
from .inbound.persona import InboundPersonaGateway
from .inbound.scene import InboundSceneGateway
from .outbound.guidance import OutboundGuidanceGateway
from .outbound.persona import OutboundPersonaGateway
from .outbound.scene import OutboundSceneGateway


class OrchestratorInboundHub:
    def __init__(
        self,
        guidance: InboundGuidanceGateway,
        persona: InboundPersonaGateway,
        scene: InboundSceneGateway,
    ) -> None:
        self.guidance = guidance
        self.persona = persona
        self.scene = scene


class OrchestratorOutboundHub:
    def __init__(
        self,
        guidance: OutboundGuidanceGateway,
        persona: OutboundPersonaGateway,
        scene: OutboundSceneGateway,
    ) -> None:
        self.guidance = guidance
        self.persona = persona
        self.scene = scene


class OrchestratorIOHub:
    """Orchestrator 出入站总线（对齐 speak.io 顶层抽象）。"""

    def __init__(
        self,
        inbound: OrchestratorInboundHub,
        outbound: OrchestratorOutboundHub,
    ) -> None:
        self.inbound = inbound
        self.outbound = outbound

    @classmethod
    def from_services(
        cls,
        *,
        guidance_control,
        persona_compose,
        scene_compose,
    ) -> OrchestratorIOHub:
        return cls(
            inbound=OrchestratorInboundHub(
                guidance=InboundGuidanceGateway(guidance_control),
                persona=InboundPersonaGateway(persona_compose),
                scene=InboundSceneGateway(scene_compose),
            ),
            outbound=OrchestratorOutboundHub(
                guidance=OutboundGuidanceGateway(guidance_control),
                persona=OutboundPersonaGateway(persona_compose),
                scene=OutboundSceneGateway(scene_compose),
            ),
        )

    @classmethod
    def from_control_service(cls, control) -> OrchestratorIOHub:
        from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.persona import PersonaComposeService
        from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.scene import SceneComposeService

        placeholder_persona = PersonaComposeService(
            persona=_MissingPersonaPort(),
            presence=_MissingPresencePort(),
        )
        placeholder_scene = SceneComposeService()
        return cls.from_services(
            guidance_control=control,
            persona_compose=placeholder_persona,
            scene_compose=placeholder_scene,
        )


class _MissingPersonaPort:
    def get_persona_snapshot(self, *, session_id: str = "tao") -> dict:
        raise RuntimeError("PersonaComposeService 未绑定 persona 端口")


class _MissingPresencePort:
    def snapshot(self, session_id: str):
        raise RuntimeError("PersonaComposeService 未绑定 presence 端口")

