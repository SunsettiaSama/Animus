"""
Approximate BPE token counter â€?no external dependencies.

Calibrated against cl100k_base (GPT-3.5 / GPT-4 tokenizer) for typical
Chinese + English + JSON content.  Typical error margin: Â±15 %.

Accuracy is sufficient for:
  - relative comparisons between runs (drift detection)
  - enforcing hard token-budget thresholds with a safety margin
  - unit-test assertions on token counts being "non-zero"

It is NOT intended as a replacement for tiktoken when exact billing figures
are required.  Use the real tokenizer for that purpose.
"""
from __future__ import annotations

import re

# CJK Unified Ideographs + common CJK symbol/punctuation blocks.
# Each matched character is counted as ~2 tokens because cl100k_base
# typically encodes each 3-byte UTF-8 CJK char as 2 byte-pair tokens.
_CJK = re.compile(
    r"["
    r"\u2e80-\u2eff"   # CJK Radicals Supplement
    r"\u2f00-\u2fdf"   # Kangxi Radicals
    r"\u3000-\u303f"   # CJK Symbols & Punctuation
    r"\u3040-\u309f"   # Hiragana
    r"\u30a0-\u30ff"   # Katakana
    r"\u3100-\u312f"   # Bopomofo
    r"\u3200-\u32ff"   # Enclosed CJK
    r"\u3400-\u4dbf"   # CJK Extension A
    r"\u4e00-\u9fff"   # CJK Unified Ideographs (main block)
    r"\uf900-\ufaff"   # CJK Compatibility Ideographs
    r"\ufe30-\ufe4f"   # CJK Compatibility Forms
    r"\uff00-\uffef"   # Halfwidth & Fullwidth Forms
    r"]"
)

# Calibration constant: ASCII alphanumeric runs average ~3.5 chars / token
# in cl100k_base (common English words are 1 token, longer ones split).
_ASCII_CHARS_PER_TOKEN: float = 3.5


def count_tokens(text: str, encoding: str = "") -> int:  # noqa: ARG001
    """
    Return approximate token count for *text*.

    The ``encoding`` parameter is accepted for API compatibility with
    tiktoken-based callers but is ignored â€?the same algorithm is used
    regardless of model family.
    """
    if not text:
        return 0

    n = 0
    i = 0
    length = len(text)

    while i < length:
        ch = text[i]

        if _CJK.match(ch):
            n += 2
            i += 1

        elif ch.isalpha() or ch.isdigit() or ch == "_":
            j = i + 1
            while j < length and (text[j].isalpha() or text[j].isdigit() or text[j] == "_"):
                j += 1
            run = j - i
            n += max(1, round(run / _ASCII_CHARS_PER_TOKEN))
            i = j

        elif ch in (" ", "\t", "\n", "\r"):
            i += 1  # whitespace is absorbed into adjacent tokens

        else:
            n += 1  # punctuation, braces, quotes, etc.
            i += 1

    return max(1, n)
