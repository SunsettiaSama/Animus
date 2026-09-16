"""speak 拟人度三维评测：画像匹配 × 图灵盲测 × 行为统计。

- 画像匹配：盲聊后让用户模拟器以"网友"视角反推画像，与真实人格档案逐维核对
  （机会感知 recall + precision + 风格贴合），测"是个什么样的人"。
- 图灵盲测：复用 test.workbench.speak_turing 的分类评委（known_user / blind_both），
  测"像不像人"。
- 行为统计：纯确定性 transcript 指标（空回复、机器人腔、复读、反问比、句长方差），
  测过程量，不花评委的钱。
"""

from .behavior import BehaviorStats, behavior_naturalness, behavior_stats
from .persona_target import FilePersona, PersonaGroundTruth
from .portrait import PortraitExtraction, PortraitMatch, extract_portrait, match_portrait
from .report import build_summary, write_report, write_summary
from .runner import CASE_VERSION, CaseRecord, run_eval


def layers_reset_eval_state() -> None:
    """清掉注入到生产 layers.py 的模块级评测状态（判定钩子/自预约存档）。"""
    from agent.soul.speak.responders.request_driven.layers import (
        EVAL_CHAR_BOOKINGS,
        set_eval_unit_judge,
    )

    set_eval_unit_judge(None)
    EVAL_CHAR_BOOKINGS.clear()


__all__ = [
    "BehaviorStats",
    "CASE_VERSION",
    "CaseRecord",
    "FilePersona",
    "PersonaGroundTruth",
    "PortraitExtraction",
    "PortraitMatch",
    "behavior_naturalness",
    "behavior_stats",
    "build_summary",
    "extract_portrait",
    "layers_reset_eval_state",
    "match_portrait",
    "run_eval",
    "write_report",
    "write_summary",
]
