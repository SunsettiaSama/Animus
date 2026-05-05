from __future__ import annotations

import difflib
import json
import re
from typing import ClassVar

from pydantic import BaseModel, Field

from ....action.base import BaseAction


class JsonQueryArgs(BaseModel):
    data: str = Field(..., min_length=1, description="JSON 字符串")
    path: str = Field(..., min_length=1, description="JSONPath 表达式，如 '$.store.book[*].title'")


class JsonQueryAction(BaseAction):
    name: str = "json_query"
    description: str = (
        "使用 JSONPath 查询 JSON 数据，提取指定路径的值。"
        "参数：data（JSON 字符串），path（JSONPath 表达式，如 '$.store.book[*].title'）"
    )
    args_model: ClassVar[type[BaseModel]] = JsonQueryArgs

    def execute(self, data: str, path: str, **kwargs) -> str:
        from jsonpath_ng import parse as jsonpath_parse

        parsed_data = json.loads(data)
        expr = jsonpath_parse(path)
        matches = [match.value for match in expr.find(parsed_data)]
        if not matches:
            return f"JSONPath {path!r} 未匹配到任何结果。"
        if len(matches) == 1:
            return json.dumps(matches[0], ensure_ascii=False, indent=2)
        return json.dumps(matches, ensure_ascii=False, indent=2)


class RegexExtractArgs(BaseModel):
    text: str = Field(..., min_length=1, description="待匹配的文本")
    pattern: str = Field(..., min_length=1, description="正则表达式模式")
    flags: str = Field("", description="正则标志：i（忽略大小写）、m（多行）、s（点匹配换行），可组合，如 'im'")
    max_matches: int = Field(20, ge=1, le=200, description="最大返回匹配数，默认 20")


class RegexExtractAction(BaseAction):
    name: str = "regex_extract"
    description: str = (
        "使用正则表达式从文本中提取所有匹配项。"
        "参数：text（文本），pattern（正则表达式），flags（标志：i/m/s，可组合），max_matches（最大匹配数，默认 20）"
    )
    args_model: ClassVar[type[BaseModel]] = RegexExtractArgs

    def execute(self, text: str, pattern: str, flags: str = "", max_matches: int = 20, **kwargs) -> str:
        flag_bits = 0
        flags_lower = flags.lower()
        if "i" in flags_lower:
            flag_bits |= re.IGNORECASE
        if "m" in flags_lower:
            flag_bits |= re.MULTILINE
        if "s" in flags_lower:
            flag_bits |= re.DOTALL

        compiled = re.compile(pattern, flag_bits)
        matches = compiled.findall(text)
        if not matches:
            return f"正则 {pattern!r} 未在文本中找到匹配项。"

        total = len(matches)
        shown = matches[:max_matches]
        lines = [f"共找到 {total} 个匹配项（显示前 {len(shown)} 个）："]
        for i, m in enumerate(shown, 1):
            if isinstance(m, tuple):
                lines.append(f"{i}. 分组: {list(m)}")
            else:
                lines.append(f"{i}. {m!r}")
        return "\n".join(lines)


class TextDiffArgs(BaseModel):
    text_a: str = Field(..., description="原始文本（旧版本）")
    text_b: str = Field(..., description="修改后文本（新版本）")
    context_lines: int = Field(3, ge=0, le=10, description="差异上下文行数，默认 3")


class TextDiffAction(BaseAction):
    name: str = "text_diff"
    description: str = (
        "对比两段文本，输出 unified diff 格式的差异。"
        "参数：text_a（旧文本），text_b（新文本），context_lines（上下文行数，默认 3）"
    )
    args_model: ClassVar[type[BaseModel]] = TextDiffArgs

    def execute(self, text_a: str, text_b: str, context_lines: int = 3, **kwargs) -> str:
        lines_a = text_a.splitlines(keepends=True)
        lines_b = text_b.splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            lines_a, lines_b,
            fromfile="text_a", tofile="text_b",
            n=context_lines,
        ))
        if not diff:
            return "两段文本完全相同，无差异。"
        return "".join(diff)
