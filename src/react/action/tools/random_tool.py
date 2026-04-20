from __future__ import annotations

import random
import string
import uuid

from react.action.base import BaseAction


class RandomNumberAction(BaseAction):
    name: str = "random_number"
    description: str = "生成随机整数或随机小数。参数：min（最小值，默认1），max（最大值，默认100），decimal（是否生成小数，默认false）"

    def execute(self, min: int = 1, max: int = 100, decimal: bool = False, **kwargs) -> str:
        if int(min) > int(max):
            raise ValueError(f"min ({min}) 不能大于 max ({max})")
        if decimal:
            result = random.uniform(float(min), float(max))
            return f"随机小数（{min} ~ {max}）：{result:.4f}"
        result = random.randint(int(min), int(max))
        return f"随机整数（{min} ~ {max}）：{result}"


class RandomChoiceAction(BaseAction):
    name: str = "random_choice"
    description: str = "从选项列表中随机选取一个。参数：options（字符串，以逗号分隔的选项，如 '苹果,香蕉,橘子'）"

    def execute(self, options: str = "", **kwargs) -> str:
        if not options:
            raise ValueError("缺少参数 options")
        items = [o.strip() for o in options.split(",") if o.strip()]
        if not items:
            raise ValueError("options 不能为空")
        chosen = random.choice(items)
        return f"从 {items} 中随机选择：{chosen}"


class GenerateUUIDAction(BaseAction):
    name: str = "generate_uuid"
    description: str = "生成一个随机 UUID。无需参数。"

    def execute(self, **kwargs) -> str:
        return f"UUID：{uuid.uuid4()}"
