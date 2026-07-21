from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage


class InfraLLMAdapter:
    """把项目 OpenAILLM 适配成 demo 的 TextGenerator（system+user）。"""

    def __init__(self, inner) -> None:
        self._inner = inner

    def generate(self, *, system: str, user: str) -> str:
        messages = [
            SystemMessage(content=system),
            HumanMessage(content=user),
        ]
        return str(self._inner.generate_messages(messages)).strip()


def load_openai_adapter(config_path: str) -> InfraLLMAdapter:
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"LLM config not found: {config_path}")

    from config.llm_core.config import LLMConfig
    from infra.llm.llm import OpenAILLM

    cfg = LLMConfig.from_yaml(str(path))
    return InfraLLMAdapter(OpenAILLM(cfg))
