from __future__ import annotations

import base64
import hashlib

from react.action.base import BaseAction


class StringTransformAction(BaseAction):
    name: str = "string_transform"
    description: str = (
        "对文本进行转换操作。参数：text（文本），operation（操作类型）："
        "upper（转大写）、lower（转小写）、title（首字母大写）、"
        "reverse（反转）、strip（去除首尾空格）、count_chars（统计字符出现次数，需提供 char 参数）"
    )

    def execute(self, text: str = "", operation: str = "upper", char: str = "", **kwargs) -> str:
        if not text:
            raise ValueError("缺少参数 text")
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
            if not char:
                raise ValueError("count_chars 操作需要提供 char 参数")
            count = text.count(char)
            return f"字符 {char!r} 在文本中出现了 {count} 次"
        raise ValueError(f"不支持的操作: {operation!r}，可选: upper/lower/title/reverse/strip/count_chars")


class Base64Action(BaseAction):
    name: str = "base64"
    description: str = "Base64 编码或解码。参数：text（文本），mode（'encode' 或 'decode'，默认 'encode'）"

    def execute(self, text: str = "", mode: str = "encode", **kwargs) -> str:
        if not text:
            raise ValueError("缺少参数 text")
        if mode.lower() == "encode":
            encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
            return f"Base64 编码：{encoded}"
        if mode.lower() == "decode":
            decoded = base64.b64decode(text.encode("ascii")).decode("utf-8")
            return f"Base64 解码：{decoded}"
        raise ValueError(f"不支持的 mode: {mode!r}，可选: encode/decode")


class HashAction(BaseAction):
    name: str = "hash"
    description: str = "计算文本的哈希值。参数：text（文本），algorithm（算法，'md5'/'sha1'/'sha256'，默认 'sha256'）"

    def execute(self, text: str = "", algorithm: str = "sha256", **kwargs) -> str:
        if not text:
            raise ValueError("缺少参数 text")
        algo = algorithm.lower().strip()
        h = hashlib.new(algo, text.encode("utf-8"))
        return f"{algo.upper()} 哈希值：{h.hexdigest()}"
