from __future__ import annotations

from infra.llm import BaseLLM

from agent.soul.ports import LLMServicePort


def resolve_module_llm(
    llm_service: LLMServicePort | None,
    aux_name: str,
    primary_llm: BaseLLM | None,
) -> BaseLLM | None:
    """向 infra 请求模块专用 LLM，未注册 aux 时回退主模型。"""
    if llm_service is not None:
        llm = llm_service.get_aux_llm(aux_name)
        if llm is not None:
            return llm
    return primary_llm
