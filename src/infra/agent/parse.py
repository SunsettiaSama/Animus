"""最小 <T>/<A>/<O>/finish 解析；返回 ParseResult，不 raise。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_RE_T = re.compile(r"<T>(.*?)</T>", re.DOTALL | re.IGNORECASE)
_RE_A = re.compile(r"<A>(.*?)</A>", re.DOTALL | re.IGNORECASE)
_RE_O = re.compile(r"<O>(.*?)</O>", re.DOTALL | re.IGNORECASE)

_FINISH_ACTIONS: frozenset[str] = frozenset({
    "finish",
    "final_answer",
    "final answer",
    "finalanswer",
    "done",
})


@dataclass
class ParseResult:
    ok: bool
    thought: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)
    output: str = ""
    is_finish: bool = False
    answer: str = ""
    error: str = ""
    action: str = ""
    action_input: dict[str, Any] = field(default_factory=dict)


def _normalize_calls(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip()
        args = item.get("args")
        if not isinstance(args, dict):
            args = item.get("action_input")
        if not isinstance(args, dict):
            args = {}
        if not action:
            continue
        out.append({"action": action, "args": dict(args)})
    return out


def parse_tao_output(text: str) -> ParseResult:
    raw = str(text or "")
    thought_m = _RE_T.search(raw)
    action_m = _RE_A.search(raw)
    output_m = _RE_O.search(raw)

    thought = thought_m.group(1).strip() if thought_m else ""
    output = output_m.group(1).strip() if output_m else ""

    if action_m is None:
        return ParseResult(
            ok=False,
            thought=thought,
            output=output,
            error="missing <A> tag",
        )

    action_body = action_m.group(1).strip()
    parsed_json: Any = None
    try:
        parsed_json = json.loads(action_body)
    except json.JSONDecodeError:
        return ParseResult(
            ok=False,
            thought=thought,
            output=output,
            error="invalid <A> JSON",
        )

    calls = _normalize_calls(parsed_json)
    if not calls:
        return ParseResult(
            ok=False,
            thought=thought,
            output=output,
            error="empty or invalid action calls",
        )

    first = calls[0]
    action = str(first["action"])
    action_input = dict(first["args"])
    is_finish = action.lower() in _FINISH_ACTIONS
    answer = ""
    if is_finish:
        answer = str(action_input.get("answer") or output or "").strip()
        if not answer and thought:
            answer = thought

    return ParseResult(
        ok=True,
        thought=thought,
        calls=calls,
        output=output,
        is_finish=is_finish,
        answer=answer,
        action=action,
        action_input=action_input,
    )
