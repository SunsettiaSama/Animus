from __future__ import annotations

from agent.react.prompt.block import PromptBlock
from .concept import BeliefStrength, SelfConcept

_STRENGTH_LABEL = {
    BeliefStrength.emerging:    "",           # emerging 不显示标签，减少噪音
    BeliefStrength.established: "（已确立）",
    BeliefStrength.core:        "（核心）",
}


class SelfConceptBlock(PromptBlock):
    """将 SelfConcept 渲染为 prompt 可注入的文本块。

    渲染策略
    --------
    - narrative 是主体，优先展示
    - 只注入 established 及以上的信念（emerging 太不稳定，不值得影响行为）
    - 最多注入 top_k 条，避免 prompt 膨胀
    """

    def __init__(
        self,
        concept: SelfConcept,
        top_k: int = 2,
        min_strength: BeliefStrength = BeliefStrength.established,
        max_chars: int = 500,
    ) -> None:
        self._concept = concept
        self._top_k = top_k
        self._min_strength = min_strength
        self._max_chars = max_chars

    def render(self) -> str | None:
        if self._concept.is_empty():
            return None

        text = self._concept.render_for_role_llm(
            top_k=self._top_k,
            min_strength=self._min_strength,
            warn_main_portrait=True,
            caller="SelfConceptBlock",
        )
        if not text:
            return None
        text = f"---\n{text}"
        if self._max_chars > 0 and len(text) > self._max_chars:
            text = text[: self._max_chars]
        return text
