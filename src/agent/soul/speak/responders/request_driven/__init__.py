from .runner import RequestDrivenPipelineRunner

__all__ = [
    "RequestDrivenPipelineRunner",
    "SpeakRole",
    "build_role_prompt",
    "interpret_role_output",
    "parse_role_blocks",
    "timeline_to_delivery_plan",
    "timeline_to_outbound_request",
]


def __getattr__(name: str):
    if name == "SpeakRole":
        from .responder import SpeakRole

        return SpeakRole
    if name == "build_role_prompt":
        from .prompt import build_role_prompt

        return build_role_prompt
    if name == "interpret_role_output":
        from .interpreter import interpret_role_output

        return interpret_role_output
    if name == "parse_role_blocks":
        from .protocol import parse_role_blocks

        return parse_role_blocks
    if name == "timeline_to_delivery_plan":
        from .delivery_bridge import timeline_to_delivery_plan

        return timeline_to_delivery_plan
    if name == "timeline_to_outbound_request":
        from .delivery_bridge import timeline_to_outbound_request

        return timeline_to_outbound_request
    if name in ("CharacterRuntime", "CharacterReplyRequest", "CharacterAgentHost"):
        from . import character as _character

        return getattr(_character, name)
    if name in ("DirectorCoordinator", "DirectorLLMCaller"):
        from . import directors as _directors

        return getattr(_directors, name)
    if name == "Screenwriter":
        from .screenwriter import Screenwriter

        return Screenwriter
    if name in ("ComposeManager", "ComposeManagerConfig", "ComposeManagerGateway"):
        from . import composer as _composer

        return getattr(_composer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
