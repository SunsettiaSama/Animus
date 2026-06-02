from __future__ import annotations

import re


def calc_brew_delay_ms(
    text: str,
    *,
    ms_per_char: float = 12.0,
    base_ms: int = 180,
    max_ms: int = 900,
) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    other = max(0, len(stripped) - cjk)
    units = cjk + int(other * 0.45)
    delay = base_ms + int(units * ms_per_char)
    return min(max(delay, base_ms), max_ms)
