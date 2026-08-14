from __future__ import annotations

import re
from typing import Protocol

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class TokenizerPort(Protocol):
    def tokenize(self, text: str) -> list[str]: ...


class SimpleTokenizer:
    """中英简易分词：词块 + 中文字 bigram，无外部依赖。"""

    def tokenize(self, text: str) -> list[str]:
        raw = text.strip().lower()
        if not raw:
            return []
        tokens: list[str] = []
        for match in _TOKEN_RE.finditer(raw):
            piece = match.group(0)
            if not piece:
                continue
            if _is_cjk_run(piece):
                tokens.extend(piece)
                if len(piece) >= 2:
                    tokens.extend(piece[i : i + 2] for i in range(len(piece) - 1))
            else:
                tokens.append(piece)
        return tokens


def _is_cjk_run(text: str) -> bool:
    return all("\u4e00" <= ch <= "\u9fff" for ch in text)
