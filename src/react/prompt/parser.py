from __future__ import annotations

import json
import re
from dataclasses import dataclass

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
_ALL_SECTION_KEYWORDS = (
    "action[ _]?input|actioninput",
    "thought",
    "action",
    "observation",
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

    return None


# ── ParseResult ───────────────────────────────────────────────────────────────

@dataclass
class ParseResult:
    thought: str
    action: str
    action_input: dict
    raw: str
    is_finish: bool


# ── Parser ────────────────────────────────────────────────────────────────────

class ReActOutputParser(BaseOutputParser[ParseResult]):
    """
    Defensive two-layer ReAct output parser.

    Layer 1 — field extraction:
      Flexible regex matching for Thought / Action / Action Input.
      Handles case variants, markdown wrappers, alternative spellings,
      and ASCII / CJK separators.

    Layer 2 — finish detection + answer recovery:
      When a finish action is identified, prefer the structured answer
      from the parsed Action Input over the full raw text.  Falls back
      through three levels:
        (a) action_input["answer"]  — LLM followed the format correctly
        (b) thought                 — LLM reasoned but skipped Action Input
        (c) raw                     — last resort; full LLM output

    JSON extraction uses a three-pass strategy:
      code-fence stripping → direct parse → blob scan with narrowing.
    """

    def parse(self, text: str) -> ParseResult:
        thought_m = _RE_THOUGHT.search(text)
        action_m  = _RE_ACTION.search(text)
        input_m   = _RE_INPUT.search(text)

        thought = thought_m.group(1).strip() if thought_m else ""
        action  = action_m.group(1).strip()  if action_m  else ""

        # ── JSON extraction ───────────────────────────────────────────────────
        if input_m:
            action_input = _extract_json(input_m.group(1)) or {}
        else:
            # No labeled Action Input — scan whole text as a recovery attempt.
            # Only accept the result if action will be finish (tool calls need
            # precisely-labeled inputs; accepting arbitrary JSON would risk
            # injecting garbage args into a real tool).
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
                )

            # (c) Fall back to thought content, then raw text
            answer = thought or text
            return ParseResult(
                thought=thought,
                action="finish",
                action_input={"answer": answer},
                raw=text,
                is_finish=True,
            )

        # ── No action label — implicit finish ─────────────────────────────────
        # LLM skipped the ReAct structure entirely and wrote the answer inline.
        if not action:
            return ParseResult(
                thought=thought,
                action="finish",
                action_input={"answer": text},
                raw=text,
                is_finish=True,
            )

        # ── Regular tool call ─────────────────────────────────────────────────
        return ParseResult(
            thought=thought,
            action=action,
            action_input=action_input,
            raw=text,
            is_finish=False,
        )

    @property
    def _type(self) -> str:
        return "react_output_parser"


_parser = ReActOutputParser()


def parse_llm_output(text: str) -> ParseResult:
    return _parser.parse(text)
