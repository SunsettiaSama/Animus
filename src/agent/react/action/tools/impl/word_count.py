from __future__ import annotations

import re
from typing import ClassVar

from pydantic import BaseModel, Field

from ....action.base import BaseAction


class WordCountArgs(BaseModel):
    text: str = Field(..., min_length=1, description="要统计的文本")


class WordCountAction(BaseAction):
    name: str = "word_count"
    description: str = "统计文本的字符数、词数、句子数。参数：text（要统计的文本）"
    args_model: ClassVar[type[BaseModel]] = WordCountArgs

    def execute(self, text: str, **kwargs) -> str:
        chars_total = len(text)
        chars_no_space = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        words = len(re.findall(r"\b\w+\b", text))
        sentences = len(re.findall(r"[.!?。！？]+", text)) or 1
        lines = text.count("\n") + 1
        return (
            f"文本统计结果：\n"
            f"  总字符数（含空格）：{chars_total}\n"
            f"  有效字符数（不含空格）：{chars_no_space}\n"
            f"  中文字符数：{chinese_chars}\n"
            f"  英文单词数：{words}\n"
            f"  句子数：{sentences}\n"
            f"  行数：{lines}"
        )
