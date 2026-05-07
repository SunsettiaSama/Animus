from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from enum import Enum

from langchain_core.output_parsers import BaseOutputParser


# ── Finish-action keyword set ─────────────────────────────────────────────────

_FINISH_ACTIONS: frozenset[str] = frozenset({
    "finish",
    "final_answer",
    "final answer",
    "finalanswer",
    "done",
})

# ── XML tag patterns (Priority 0) ─────────────────────────────────────────────

_RE_T = re.compile(r"<T>(.*?)</T>", re.DOTALL | re.IGNORECASE)
_RE_A = re.compile(r"<A>(.*?)</A>", re.DOTALL | re.IGNORECASE)
_RE_O = re.compile(r"<O>(.*?)</O>", re.DOTALL | re.IGNORECASE)

# ── Section boundary helpers ──────────────────────────────────────────────────

# Listed most-specific first so "Action Input" is checked before "Action".
# "answer" is included so that a bare "Answer:" label used by some models
# is treated as a section boundary (stops Thought extraction before it).
_ALL_SECTION_KEYWORDS = (
    "action[ _]?input|actioninput",
    "thought",
    "action",
    "observation",
    "output",
    "answer",
)
_ALL_KW_PAT = "|".join(_ALL_SECTION_KEYWORDS)

# Optional markdown bold/italic wrapping: **, *, __, _
_MD = r"[\*_]{0,2}"

# Accepted field separators: ASCII colon, CJK fullwidth colon, equals sign
_SEP = r"[ \t]*[:：=][ \t]*"

# Pattern that marks the start of any labeled section (used as lookahead stop).
_SECTION_ANCHOR = rf"(?:^|\n)[ \t]*{_MD}(?:{_ALL_KW_PAT}){_MD}{_SEP}"


def _field_re(*keywords: str) -> re.Pattern[str]:
    alts = "|".join(re.escape(k) for k in keywords)
    return re.compile(
        rf"(?:^|\n)[ \t]*{_MD}(?:{alts}){_MD}{_SEP}(.*?)(?={_SECTION_ANCHOR}|\Z)",
        re.IGNORECASE | re.DOTALL,
    )


# ── Compiled field patterns ───────────────────────────────────────────────────

_RE_THOUGHT = _field_re("Thought")
_RE_OUTPUT  = _field_re("Output")
_RE_ACTION  = _field_re("Action")
_RE_INPUT   = _field_re(
    "Action Input", "Action_Input", "ActionInput", "action_input",
)
_RE_ANSWER  = _field_re("Answer")

# ── Layer 1 lenient action inference patterns ─────────────────────────────────
# Matches phrases like "I'll use web_search", "Using web_search", "调用 web_search".
_RE_LENIENT_VERB = re.compile(
    r"(?:using|use|call(?:ing)?|invoke|invoking|调用|使用)\s+([\w_]+)",
    re.IGNORECASE,
)

# ── Finish answer cleanup ─────────────────────────────────────────────────────

# Strips "I now know the final answer" / "我现在知道最终答案了" reasoning preambles
# from the start of a fallback answer, and drops trailing ReAct structure markers.
_RE_REASONING_PREAMBLE = re.compile(
    r"^(?:"
    r"I(?:'ve| have)? (?:now )?(?:know|found|determined|concluded)[^.!?]*[.!?]\s*"
    r"|我(?:现在)?(?:知道|找到|确定|得出)[^。！？]*[。！？]\s*"
    r")+",
    re.IGNORECASE,
)
_RE_TRAILING_MARKERS = re.compile(
    r"\n+(?:Thought|Action|Observation|Output)[ \t]*[:：].*$",
    re.IGNORECASE | re.DOTALL,
)


def _clean_finish_answer(text: str) -> str:
    """Strip LLM reasoning boilerplate from a fallback finish answer."""
    text = _RE_REASONING_PREAMBLE.sub("", text).strip()
    text = _RE_TRAILING_MARKERS.sub("", text).strip()
    return text


# ── JSON extraction ───────────────────────────────────────────────────────────

_RE_CODE_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.DOTALL)


def _extract_json(text: str) -> dict | None:
    """
    Progressively attempt to extract a JSON object from *text*.

    Pass 1 — code fence: strip ```json ... ``` and parse the inner content.
    Pass 2 — direct parse: try json.loads on the stripped text.
    Pass 3 — blob scan: find the span from the first '{' to the last '}' and
              then narrow inward until a valid JSON object is found.

    Returns None when no valid object is found so callers can distinguish
    between "empty JSON" and "no JSON at all".
    """
    text = text.strip()
    if not text:
        return None

    fence = _RE_CODE_FENCE.search(text)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        blob = text[start : end + 1]
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            for candidate_end in (m.start() for m in re.finditer(r"\}", blob)):
                try:
                    return json.loads(blob[: candidate_end + 1])
                except json.JSONDecodeError:
                    continue

        # Pass 4: ast.literal_eval — handles Python-style dicts with single quotes
        # that json.loads rejects (e.g. {'answer': 'text'} from some LLM outputs).
        try:
            val = ast.literal_eval(blob)
            if isinstance(val, dict):
                return val
        except (ValueError, SyntaxError):
            pass

    return None


def _extract_json_array(text: str) -> list | None:
    """
    Progressively attempt to extract a JSON array from *text*.

    Mirrors the strategy of _extract_json but targets '[' / ']' boundaries
    instead of '{' / '}', since Output: sections produce arrays not dicts.

    Returns None when no valid array is found.
    """
    text = text.strip()
    if not text:
        return None

    # Pass 1 — code fence
    fence = _RE_CODE_FENCE.search(text)
    if fence:
        inner = fence.group(1).strip()
        try:
            val = json.loads(inner)
            if isinstance(val, list):
                return val
        except json.JSONDecodeError:
            pass

    # Pass 2 — direct parse
    try:
        val = json.loads(text)
        if isinstance(val, list):
            return val
    except json.JSONDecodeError:
        pass

    # Pass 3 — blob scan from first '[' to last ']'
    start = text.find("[")
    end   = text.rfind("]")
    if start != -1 and end > start:
        blob = text[start : end + 1]
        try:
            val = json.loads(blob)
            if isinstance(val, list):
                return val
        except json.JSONDecodeError:
            for candidate_end in (m.start() for m in re.finditer(r"\]", blob)):
                try:
                    val = json.loads(blob[: candidate_end + 1])
                    if isinstance(val, list):
                        return val
                except json.JSONDecodeError:
                    continue

        # Pass 4: ast.literal_eval for Python-style lists
        try:
            val = ast.literal_eval(blob)
            if isinstance(val, list):
                return val
        except (ValueError, SyntaxError):
            pass

    return None


def _normalise_call(item: object) -> dict | None:
    """Normalise a single element from an Output array into {action, args}.

    Accepts:
      {"action": "...", "args": {...}}
      {"action": "...", "arguments": {...}}
      {"action": "...", "input": {...}}
      {"name": "...", "args": {...}}   (some model variants)
    Returns None for unrecognisable shapes.
    """
    if not isinstance(item, dict):
        return None
    action = item.get("action") or item.get("name") or item.get("tool")
    if not isinstance(action, str) or not action:
        return None
    args = (
        item.get("args")
        or item.get("arguments")
        or item.get("input")
        or item.get("action_input")
        or {}
    )
    if not isinstance(args, dict):
        args = {}
    return {"action": action.strip(), "args": args}


# ── ParseQuality ──────────────────────────────────────────────────────────────

class ParseQuality(Enum):
    CLEAN            = "clean"            # Output:[...] or <T><A> format extracted cleanly
    LENIENT          = "lenient"          # fell back to legacy Action:/Action Input: format
    FINISH_DEGRADED  = "finish_degraded"  # finish detected but answer fell back to thought/raw
    FAILED           = "failed"           # action is empty and this is not a finish step


# ── ParseResult ───────────────────────────────────────────────────────────────

@dataclass
class ParseResult:
    thought: str
    action: str
    action_input: dict
    raw: str
    is_finish: bool
    quality: ParseQuality = field(default=ParseQuality.CLEAN)
    calls: list[dict] | None = None   # [{"action": str, "args": dict}, ...]; set when Output: found
    output: str = ""                   # <O> tag content; the sole user-visible output


# ── diagnose ──────────────────────────────────────────────────────────────────

def diagnose(result: ParseResult) -> str:
    """Return a human-readable description of what went wrong during parsing.

    Used to construct the repair prompt for Layer 2.
    """
    issues: list[str] = []

    if not result.thought:
        issues.append("missing <T> thought field")

    if not result.action:
        issues.append(
            "missing <A> action field — no tool name could be extracted. "
            'Use: <A>[{"action": "tool_name", "args": {...}}]</A>'
        )
    elif result.quality == ParseQuality.LENIENT:
        issues.append(
            f"used deprecated Action:/Action Input: format (found '{result.action}'); "
            'please rewrite using: <A>[{"action": "tool_name", "args": {...}}]</A>'
        )

    if result.quality == ParseQuality.FINISH_DEGRADED:
        issues.append(
            "finish action detected but <A> args could not be parsed as valid JSON — "
            "the answer was recovered from <T> or raw output; "
            'please rewrite with: <A>[{"action": "finish", "args": {"answer": "..."}}]</A>'
            ' and optionally <O>your answer</O>'
        )

    if not result.is_finish and not result.action_input:
        issues.append(
            "missing or unparseable args — "
            'expected: <A>[{"action": "tool", "args": {"key": "value"}}]</A>'
        )

    if not issues:
        return "output appears structurally correct"

    return "; ".join(issues)


# ── Layer 1 lenient action inference ─────────────────────────────────────────

def _infer_action(text: str, tool_names: frozenset[str]) -> str:
    """
    Try to extract an action name without a labeled 'Action:' field.

    Strategy 1: verb pattern — "I'll use <tool>", "Using <tool>", "调用 <tool>".
    Strategy 2: first token on the first non-empty line matches a known tool name.

    Returns the inferred action name, or "" if nothing matched.
    """
    # Strategy 1: verb heuristic
    m = _RE_LENIENT_VERB.search(text)
    if m:
        candidate = m.group(1).strip().lower()
        if candidate in tool_names:
            return candidate

    # Strategy 2: first line is a bare known tool name
    for line in text.splitlines():
        token = line.strip().lower().rstrip(":")
        if token and token in tool_names:
            return token
        if token:  # first non-empty line tried; stop after one attempt
            break

    return ""


# ── Parser ────────────────────────────────────────────────────────────────────

class ReActOutputParser(BaseOutputParser[ParseResult]):
    """
    Defensive three-quality ReAct output parser supporting the new XML tag
    format (<T><A><O>), the Output:[{action,args}] array format, and the
    legacy Action:/Action Input: format.

    Priority order:
      0. <T>...</T> + <A>...</A> — preferred XML format; quality = CLEAN
      1. Output: [...] — legacy array format; quality = CLEAN
      2. Action: / Action Input: — deprecated fallback; quality = LENIENT
         (triggers L2 nudge to adopt the new format)
      3. Implicit finish — no structured action found; quality = FAILED
         Only triggers is_finish=True when <O> content or Answer: label exists.

    Parallel calls: when <A> or Output: contains multiple elements, all are
    returned in ParseResult.calls; result.action / result.action_input reflect
    the first element for backward-compatible callers.
    """

    def parse(
        self,
        text: str,
        tool_names: frozenset[str] | None = None,
    ) -> ParseResult:

        # ── Priority 0: new XML <T><A><O> format ──────────────────────────────
        t_m = _RE_T.search(text)
        a_m = _RE_A.search(text)
        o_m = _RE_O.search(text)
        output_content = o_m.group(1).strip() if o_m else ""

        if a_m:
            thought = t_m.group(1).strip() if t_m else ""
            raw_a = a_m.group(1).strip()
            items = _extract_json_array(raw_a)
            if items:
                calls = [c for c in (_normalise_call(i) for i in items) if c is not None]
                if calls:
                    first = calls[0]
                    action_norm = re.sub(r"[\s\-]+", "_", first["action"].lower()).strip("_")

                    if action_norm in _FINISH_ACTIONS:
                        finish_args = first["args"]
                        if "answer" not in finish_args:
                            answer_text = output_content or _clean_finish_answer(thought) or thought or text
                            finish_args = {"answer": answer_text}
                            quality = ParseQuality.FINISH_DEGRADED
                        else:
                            quality = ParseQuality.CLEAN
                        return ParseResult(
                            thought=thought,
                            action="finish",
                            action_input=finish_args,
                            raw=text,
                            is_finish=True,
                            quality=quality,
                            calls=calls,
                            output=output_content,
                        )

                    return ParseResult(
                        thought=thought,
                        action=first["action"],
                        action_input=first["args"],
                        raw=text,
                        is_finish=False,
                        quality=ParseQuality.CLEAN,
                        calls=calls,
                        output=output_content,
                    )

        # ── Priority 1: legacy Output: [...] format ────────────────────────────
        thought_m = _RE_THOUGHT.search(text)
        thought = thought_m.group(1).strip() if thought_m else ""

        output_m = _RE_OUTPUT.search(text)
        if output_m:
            raw_output = output_m.group(1).strip()
            items = _extract_json_array(raw_output)
            if items:
                calls = [c for c in (_normalise_call(i) for i in items) if c is not None]
                if calls:
                    first = calls[0]
                    action_norm = re.sub(r"[\s\-]+", "_", first["action"].lower()).strip("_")

                    if action_norm in _FINISH_ACTIONS:
                        finish_args = first["args"]
                        if "answer" not in finish_args:
                            answer_text = output_content or _clean_finish_answer(thought) or thought or text
                            finish_args = {"answer": answer_text}
                            quality = ParseQuality.FINISH_DEGRADED
                        else:
                            quality = ParseQuality.CLEAN
                        return ParseResult(
                            thought=thought,
                            action="finish",
                            action_input=finish_args,
                            raw=text,
                            is_finish=True,
                            quality=quality,
                            calls=calls,
                            output=output_content,
                        )

                    return ParseResult(
                        thought=thought,
                        action=first["action"],
                        action_input=first["args"],
                        raw=text,
                        is_finish=False,
                        quality=ParseQuality.CLEAN,
                        calls=calls,
                        output=output_content,
                    )

        # ── Priority 2: legacy Action: / Action Input: format (LENIENT) ───────
        action_m = _RE_ACTION.search(text)
        input_m  = _RE_INPUT.search(text)

        action = action_m.group(1).strip() if action_m else ""

        # Layer 1b: lenient action inference
        quality = ParseQuality.LENIENT
        if not action and tool_names:
            inferred = _infer_action(text, tool_names)
            if inferred:
                action = inferred

        if input_m:
            action_input = _extract_json(input_m.group(1)) or {}
        else:
            action_input = {}

        action_norm = re.sub(r"[\s\-]+", "_", action.lower()).strip("_")

        # ── Finish detection (legacy path) ────────────────────────────────────
        if action_norm in _FINISH_ACTIONS:
            if "answer" in action_input:
                return ParseResult(
                    thought=thought,
                    action="finish",
                    action_input=action_input,
                    raw=text,
                    is_finish=True,
                    quality=quality,
                    calls=None,
                    output=output_content,
                )

            recovered = _extract_json(text)
            if recovered and "answer" in recovered:
                return ParseResult(
                    thought=thought,
                    action="finish",
                    action_input=recovered,
                    raw=text,
                    is_finish=True,
                    quality=quality,
                    calls=None,
                    output=output_content,
                )

            answer_label_m = _RE_ANSWER.search(text)
            if answer_label_m:
                answer = answer_label_m.group(1).strip()
            else:
                answer = _clean_finish_answer(thought) if thought else _clean_finish_answer(text)
                if not answer:
                    answer = thought or text
            return ParseResult(
                thought=thought,
                action="finish",
                action_input={"answer": answer},
                raw=text,
                is_finish=True,
                quality=ParseQuality.FINISH_DEGRADED,
                calls=None,
                output=output_content,
            )

        # ── No action label — implicit finish (FAILED) ────────────────────────
        # Only treat as finished when there is an explicit user-visible signal:
        # an <O> tag or an Answer: label. Otherwise keep FAILED+is_finish=False
        # so the escalation chain (L2/L3) can attempt recovery.
        if not action:
            answer_m = _RE_ANSWER.search(text)
            if output_content:
                # <O> present — treat as finish with <O> as the answer
                return ParseResult(
                    thought=thought,
                    action="finish",
                    action_input={"answer": output_content},
                    raw=text,
                    is_finish=True,
                    quality=ParseQuality.FAILED,
                    calls=None,
                    output=output_content,
                )
            if answer_m:
                answer_text = answer_m.group(1).strip()
                return ParseResult(
                    thought=thought,
                    action="finish",
                    action_input={"answer": answer_text},
                    raw=text,
                    is_finish=True,
                    quality=ParseQuality.FAILED,
                    calls=None,
                    output=output_content,
                )
            # No explicit signal — keep as FAILED without is_finish so L2/L3 can retry
            return ParseResult(
                thought=thought,
                action="",
                action_input={},
                raw=text,
                is_finish=False,
                quality=ParseQuality.FAILED,
                calls=None,
                output=output_content,
            )

        # ── Regular tool call (legacy single-action) ──────────────────────────
        return ParseResult(
            thought=thought,
            action=action,
            action_input=action_input,
            raw=text,
            is_finish=False,
            quality=quality,
            calls=None,
            output=output_content,
        )

    @property
    def _type(self) -> str:
        return "react_output_parser"


_parser = ReActOutputParser()


def parse_llm_output(
    text: str,
    tool_names: frozenset[str] | None = None,
) -> ParseResult:
    return _parser.parse(text, tool_names=tool_names)
