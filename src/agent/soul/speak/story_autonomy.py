"""story_autonomy — 旧剧情机器运行时断供开关（single-stream R6.3 退役）。

剧情发起已归 life/story（storybus 常驻链，需求 §6 R6）。本开关在**运行时**
断供 speak 内部旧导演/编剧机器的三条供能路径：

1. 导演主动交接（``_on_director_character_handoff``：idle 主动开口的
   "决定说什么"）；
2. 编剧初始化（``_schedule_screenwriter_init``：写弧 + 开场大纲生成）；
3. 剧情池预热回填（``_story_pool_refill_async``：``pool-full-*`` 会话）。

默认开启（断供）。``ANIMUS_STORY_AUTONOMY=0`` 可临时恢复旧行为（应急/对比
观测用）。物理移除（目录搬迁与调用链拆除）归需求 Phase 4；本开关是逻辑
退役的落点——旧行为不再发生，但代码路径保留可回滚。
"""
from __future__ import annotations

import os

_ENV_KEY = "ANIMUS_STORY_AUTONOMY"
_OFF_VALUES = {"0", "false", "False", "no", "off"}


def story_autonomy_enabled() -> bool:
    """True = 新架构生效（旧剧情机器断供）。默认 True。"""
    raw = os.environ.get(_ENV_KEY, "1").strip()
    return raw not in _OFF_VALUES
