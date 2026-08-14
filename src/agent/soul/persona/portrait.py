"""主画像 vs 子画像（蒸馏切片）边界。"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

# 子画像（persona_distill.slices）按下游分片。
# Speak 角色仅允许 dialogue；Speak 导演仅允许 director；不得注入主画像全文。
SLICE_ROLE_LLM_TARGETS: dict[str, str] = {
    "general": "通用身份名片（角色 LLM）",
    "dialogue": "即时对话 Speak（角色 LLM）",
    "story": "行为与叙事演化（角色 LLM）",
    "reasoning": "推理与决策（角色 LLM）",
    "memory_anchor": "记忆压缩锚定（角色 LLM）",
}

SLICE_DIRECTOR_LLM_TARGETS: dict[str, str] = {
    "director": "对话导演 Speak（导演 LLM，精简行为指引）",
}

_MAIN_PORTRAIT_WARNING = (
    "[persona] main portrait requested (built_profile / self_concept), not a distilled slice; "
    "Speak dialogue injection should use persona_distill.slices.dialogue only."
)


def warn_main_portrait_usage(caller: str) -> None:
    """主画像被用于角色向 LLM 注入时打终端可见告警。"""
    msg = f"{_MAIN_PORTRAIT_WARNING} caller={caller}"
    logger.warning(msg)
    print(msg, file=sys.stderr, flush=True)
