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

# ── Section boundary helpers ──────────────────────────────────────────────────

# Listed most-specific first so "Action Input" is checked before "Action".
# "answer" is included so that a bare "Answer:" label used by some models
# is treated as a section boundary (stops Thought extraction before it).
_ALL_SECTION_KEYWORDS = (
    "action[ _]?input|actioninput",
    "thought",
    "action",
    "observation",
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
    r"\n+(?:Thought|Action|Observation)[ \t]*[:：].*$",
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


# ── ParseQuality ──────────────────────────────────────────────────────────────

class ParseQuality(Enum):
    CLEAN            = "clean"            # all fields extracted via standard patterns
    LENIENT          = "lenient"          # action inferred via fallback heuristics
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


# ── diagnose ──────────────────────────────────────────────────────────────────

def diagnose(result: ParseResult) -> str:
    """Return a human-readable description of what went wrong during parsing.

    Used to construct the repair prompt for Layer 2.
    """
    issues: list[str] = []

    if not result.thought:
        issues.append("missing Thought field")

    if not result.action:
        issues.append("missing Action field — no tool name could be extracted")
    elif result.quality == ParseQuality.LENIENT:
        issues.append(
            f"Action field inferred via heuristic (found '{result.action}' "
            "from context, not from a labeled 'Action:' line)"
        )

    if result.quality == ParseQuality.FINISH_DEGRADED:
        issues.append(
            "finish action detected but Action Input could not be parsed as valid JSON — "
            "the answer was recovered from Thought or raw output; "
            'please rewrite with a proper JSON object: Action Input: {"answer": "..."}'
        )

    if not result.is_finish and not result.action_input:
        issues.append(
            "missing or unparseable Action Input — "
            "expected a JSON object like {\"query\": \"...\"}"
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
    Defensive three-quality ReAct output parser.

    Layer 1 — field extraction:
      Flexible regex matching for Thought / Action / Action Input.
      Handles case variants, markdown wrappers, alternative spellings,
      and ASCII / CJK separators.

    Layer 1b — lenient inference (LENIENT quality):
      When no labeled Action field is found, attempts heuristic inference
      from verb patterns and bare tool-name lines.

    Layer 2 — finish detection + answer recovery:
      When a finish action is identified, prefer the structured answer
      from the parsed Action Input over the full raw text.  Falls back
      through three levels:
        (a) action_input["answer"]  — LLM followed the format correctly
        (b) thought                 — LLM reasoned but skipped Action Input
        (c) raw                     — last resort; full LLM output

    JSON extraction uses a three-pass strategy:
      code-fence stripping → direct parse → blob scan with narrowing.

    Quality scoring:
      CLEAN   — standard patterns matched
      LENIENT — action inferred via heuristics
      FAILED  — action empty and not a finish step (triggers upper-layer repair)
    """

    def parse(
        self,
        text: str,
        tool_names: frozenset[str] | None = None,
    ) -> ParseResult:
        thought_m = _RE_THOUGHT.search(text)
        action_m  = _RE_ACTION.search(text)
        input_m   = _RE_INPUT.search(text)

        thought = thought_m.group(1).strip() if thought_m else ""
        action  = action_m.group(1).strip()  if action_m  else ""

        quality = ParseQuality.CLEAN

        # ── Layer 1b: lenient action inference ───────────────────────────────
        if not action and tool_names:
            inferred = _infer_action(text, tool_names)
            if inferred:
                action  = inferred
                quality = ParseQuality.LENIENT

        # ── JSON extraction ───────────────────────────────────────────────────
        if input_m:
            action_input = _extract_json(input_m.group(1)) or {}
        else:
            action_input = {}

        # ── Action name normalisation ─────────────────────────────────────────
        # Collapse whitespace/dashes to underscore; strip leading/trailing ones.
        action_norm = re.sub(r"[\s\-]+", "_", action.lower()).strip("_")

        # ── Finish detection ──────────────────────────────────────────────────
        if action_norm in _FINISH_ACTIONS:
            # (a) LLM provided a structured answer in Action Input
            if "answer" in action_input:
                return ParseResult(
                    thought=thought,
                    action="finish",
                    action_input=action_input,
                    raw=text,
                    is_finish=True,
                    quality=quality,
                )

            # (b) No structured Action Input at all — try scanning full text
            recovered = _extract_json(text)
            if recovered and "answer" in recovered:
                return ParseResult(
                    thought=thought,
                    action="finish",
                    action_input=recovered,
                    raw=text,
                    is_finish=True,
                    quality=quality,
                )

            # (c) Fall back: check Answer: label first, then thought, then raw text.
            # All sub-paths here are structurally degraded — the Action Input JSON
            # could not be recovered, so quality is marked FINISH_DEGRADED to let
            # the upper-layer repair chain know it should attempt a correction.
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
            )

        # ── No action label — implicit finish ─────────────────────────────────
        # LLM skipped the ReAct structure entirely and wrote the answer inline,
        # or used an "Answer:" label instead of the standard "Action: finish".
        # Prefer the content after "Answer:" if present; fall back to thought,
        # then the full raw text as the answer payload.
        if not action:
            answer_m = _RE_ANSWER.search(text)
            if answer_m:
                answer_text = answer_m.group(1).strip()
            elif thought:
                answer_text = _clean_finish_answer(thought) or thought
            else:
                answer_text = _clean_finish_answer(text) or text
            return ParseResult(
                thought=thought,
                action="finish",
                action_input={"answer": answer_text},
                raw=text,
                is_finish=True,
                quality=ParseQuality.FAILED,
            )

        # ── Regular tool call ─────────────────────────────────────────────────
        return ParseResult(
            thought=thought,
            action=action,
            action_input=action_input,
            raw=text,
            is_finish=False,
            quality=quality,
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
