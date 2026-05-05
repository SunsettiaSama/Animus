from __future__ import annotations

import base64
import hashlib
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, model_validator

from ....action.base import BaseAction

_TRANSFORM_OPS = Literal["upper", "lower", "title", "reverse", "strip", "count_chars"]


class StringTransformArgs(BaseModel):
    text: str = Field(..., min_length=1, description="要处理的文本")
    operation: _TRANSFORM_OPS = Field("upper", description="操作类型")
    char: str = Field("", description="count_chars 操作所需的目标字符")

    @model_validator(mode="after")
    def check_count_chars(self) -> "StringTransformArgs":
        if self.operation == "count_chars" and not self.char:
            raise ValueError("count_chars 操作需要提供 char 参数")
        return self


class StringTransformAction(BaseAction):
    name: str = "string_transform"
    description: str = (
        "对文本进行转换操作。参数：text（文本），operation（操作类型）："
        "upper（转大写）、lower（转小写）、title（首字母大写）、"
        "reverse（反转）、strip（去除首尾空格）、count_chars（统计字符出现次数，需提供 char 参数）"
    )
    args_model: ClassVar[type[BaseModel]] = StringTransformArgs

    def execute(self, text: str, operation: str = "upper", char: str = "", **kwargs) -> str:
        op = operation.lower().strip()
        if op == "upper":
            return f"大写：{text.upper()}"
        if op == "lower":
            return f"小写：{text.lower()}"
        if op == "title":
            return f"首字母大写：{text.title()}"
        if op == "reverse":
            return f"反转：{text[::-1]}"
        if op == "strip":
            return f"去空格：{text.strip()!r}"
        if op == "count_chars":
            count = text.count(char)
            return f"字符 {char!r} 在文本中出现了 {count} 次"
        raise ValueError(f"不支持的操作: {operation!r}")


class Base64Args(BaseModel):
    text: str = Field(..., min_length=1, description="待编码或解码的文本")
    mode: Literal["encode", "decode"] = Field("encode", description="'encode' 或 'decode'")


class Base64Action(BaseAction):
    name: str = "base64"
    description: str = (
        "Base64 编码或解码。"
        "参数：text（文本），mode（'encode' 或 'decode'，默认 'encode'）"
    )
    args_model: ClassVar[type[BaseModel]] = Base64Args

    def execute(self, text: str, mode: str = "encode", **kwargs) -> str:
        if mode.lower() == "encode":
            encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
            return f"Base64 编码：{encoded}"
        decoded = base64.b64decode(text.encode("ascii")).decode("utf-8")
        return f"Base64 解码：{decoded}"


class HashArgs(BaseModel):
    text: str = Field(..., min_length=1, description="要计算哈希的文本")
    algorithm: Literal["md5", "sha1", "sha256"] = Field("sha256", description="哈希算法")


class HashAction(BaseAction):
    name: str = "hash"
    description: str = (
        "计算文本的哈希值。"
        "参数：text（文本），algorithm（算法，'md5'/'sha1'/'sha256'，默认 'sha256'）"
    )
    args_model: ClassVar[type[BaseModel]] = HashArgs

    def execute(self, text: str, algorithm: str = "sha256", **kwargs) -> str:
        algo = algorithm.lower().strip()
        h = hashlib.new(algo, text.encode("utf-8"))
        return f"{algo.upper()} 哈希值：{h.hexdigest()}"
