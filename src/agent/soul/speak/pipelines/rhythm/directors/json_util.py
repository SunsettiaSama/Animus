from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(raw: str, *, director: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise ValueError(f"{director}: empty LLM output")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError(f"{director}: no JSON object in output: {raw!r}")
    payload = json.loads(match.group())
    if not isinstance(payload, dict):
        raise ValueError(f"{director}: JSON root must be object")
    return payload
