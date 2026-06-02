"""主画像 vs 子画像（蒸馏切片）边界。"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

# 子画像（persona_distill.slices）面向「扮演该角色的 LLM 服务」注入，按下游分片。
# Speak 仅允许使用 dialogue 切片，不得注入 built_profile / self_concept 全文。
SLICE_ROLE_LLM_TARGETS: dict[str, str] = {
    "general": "通用身份名片（角色 LLM）",
    "dialogue": "即时对话 Speak（角色 LLM）",
    "story": "行为与叙事演化（角色 LLM）",
    "reasoning": "推理与决策（角色 LLM）",
    "memory_anchor": "记忆压缩锚定（角色 LLM）",
}

_MAIN_PORTRAIT_WARNING = (
    "[persona] 正在拉取主画像（built_profile / self_concept），非蒸馏子画像；"
    "若用于 Speak 对话注入，行为可能不符合预期。"
    "Speak 应仅使用 persona_distill.slices.dialogue。"
)


def warn_main_portrait_usage(caller: str) -> None:
    """主画像被用于角色向 LLM 注入时打终端可见告警。"""
    msg = f"{_MAIN_PORTRAIT_WARNING} caller={caller}"
    logger.warning(msg)
    print(msg, file=sys.stderr, flush=True)
