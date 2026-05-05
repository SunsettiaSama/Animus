from __future__ import annotations

import random
import uuid
from typing import ClassVar

from pydantic import BaseModel, Field, model_validator

from ....action.base import BaseAction


class RandomNumberArgs(BaseModel):
    min: int = Field(1, description="最小值")
    max: int = Field(100, description="最大值")
    decimal: bool = Field(False, description="是否生成小数")

    @model_validator(mode="after")
    def check_range(self) -> "RandomNumberArgs":
        if self.min > self.max:
            raise ValueError(f"min ({self.min}) 不能大于 max ({self.max})")
        return self


class RandomNumberAction(BaseAction):
    name: str = "random_number"
    description: str = (
        "生成随机整数或随机小数。"
        "参数：min（最小值，默认1），max（最大值，默认100），decimal（是否生成小数，默认false）"
    )
    args_model: ClassVar[type[BaseModel]] = RandomNumberArgs

    def execute(self, min: int = 1, max: int = 100, decimal: bool = False, **kwargs) -> str:
        if decimal:
            result = random.uniform(float(min), float(max))
            return f"随机小数（{min} ~ {max}）：{result:.4f}"
        result = random.randint(int(min), int(max))
        return f"随机整数（{min} ~ {max}）：{result}"


class RandomChoiceArgs(BaseModel):
    options: str = Field(..., min_length=1, description="以逗号分隔的选项，如 '苹果,香蕉,橘子'")

    @model_validator(mode="after")
    def check_items(self) -> "RandomChoiceArgs":
        items = [o.strip() for o in self.options.split(",") if o.strip()]
        if not items:
            raise ValueError("options 拆分后不能为空，请提供至少一个有效选项")
        return self


class RandomChoiceAction(BaseAction):
    name: str = "random_choice"
    description: str = (
        "从选项列表中随机选取一个。"
        "参数：options（字符串，以逗号分隔的选项，如 '苹果,香蕉,橘子'）"
    )
    args_model: ClassVar[type[BaseModel]] = RandomChoiceArgs

    def execute(self, options: str, **kwargs) -> str:
        items = [o.strip() for o in options.split(",") if o.strip()]
        chosen = random.choice(items)
        return f"从 {items} 中随机选择：{chosen}"


class GenerateUUIDArgs(BaseModel):
    pass


class GenerateUUIDAction(BaseAction):
    name: str = "generate_uuid"
    description: str = "生成一个随机 UUID。无需参数。"
    args_model: ClassVar[type[BaseModel]] = GenerateUUIDArgs

    def execute(self, **kwargs) -> str:
        return f"UUID：{uuid.uuid4()}"
