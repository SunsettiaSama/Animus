from __future__ import annotations

"""叙事编剧（Screenwriter）

职责备注（受众拆分）：
- 给角色看：plot_arc.summary（完整故事线）/ units（可执行步骤）。
- 给内部场记：plot_flow —— chronicle / focus_now / next_push / beats。
- 书写材料：命运骰、角色面板、场景/世界观、记忆池、分享队列、抽词种子；
  与用户交互记录优先：写交互如何发生、对角色后续故事线的影响，不写角色台词。
- 记忆与分享：由编剧写入 plot_flow 材料调度。
- 给用户看：opening —— 开场旁白，唯一占用 outline 投递渠道；先写大纲，再并行写旁白与初始 unit。
- 附带：presence_card / narrative_card。
- 轮询：用户↔角色往来满 3 轮或剧情 unit 总数超过 5 时唤醒编剧，对齐后续剧情 unit。
- 大纲/unit：ScreenwriterAgent 多步查阅材料后交稿；大纲须客观、冷静、真实。
"""

from .agent import ScreenwriterAgent, ScreenwriterAgentResult
from .interaction_mode import (
    InteractionMode,
    interaction_annotation_block,
    resolve_interaction_mode,
)
from .materials import WritingMaterials, build_writing_materials
from .scene_seed import DEFAULT_SCENE_SEED_K, build_init_scene_seeds, is_usable_scene_seed
from .writer import Screenwriter

__all__ = [
    "Screenwriter",
    "ScreenwriterAgent",
    "ScreenwriterAgentResult",
    "WritingMaterials",
    "build_writing_materials",
    "InteractionMode",
    "interaction_annotation_block",
    "resolve_interaction_mode",
    "DEFAULT_SCENE_SEED_K",
    "build_init_scene_seeds",
    "is_usable_scene_seed",
]
