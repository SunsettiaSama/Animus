from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpeakSystemLayer:
    """静态规则层：角色设定与输出格式（compose 周期内不变）。"""

    role: str = ""
    output_format: str = ""
