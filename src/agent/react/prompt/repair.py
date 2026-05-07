from __future__ import annotations

from ..prompt.parser import ParseResult, parse_llm_output, ParseQuality

# ── Repair prompt template ────────────────────────────────────────────────────

_REPAIR_TEMPLATE = """\
You are a format-repair assistant for a ReAct-style language model agent.

The agent must output its response using EXACTLY these XML tags:
---
<T>reasoning about what to do</T>
<A>[{{"action": "<tool_name>", "args": {{"key": "value"}}}}]</A>
<O>optional message to the user</O>
---

To call multiple tools in parallel, list them in the <A> array:
---
<T>reasoning</T>
<A>[
  {{"action": "tool_a", "args": {{"key": "value"}}}},
  {{"action": "tool_b", "args": {{"key": "value"}}}}
]</A>
---

If the agent wants to give a final answer, it uses finish and MUST include <O>:
---
<T>reasoning</T>
<A>[{{"action": "finish", "args": {{"answer": "<final answer text>"}}}}]</A>
<O>final answer visible to the user</O>
---

## Problem
The following output could not be parsed correctly.
Diagnosis: {diagnosis}

## Original (broken) output
{raw}

## Available tools
{tool_list}

## Your task
Rewrite the broken output strictly following the XML format above.
- Keep the original intent and reasoning.
- Do NOT add explanations — output ONLY the corrected block.
- The action inside <A> must be one of the available tools listed above, or "finish".
- The <A> value must be a valid JSON array.
- <O> is optional on intermediate steps; required when action is "finish".

---
以下是中文说明（同上）：
你是一个 ReAct 格式修复助手。
请将上面的"破损输出"重写为标准 XML 标签格式（<T><A><O>），保留原始意图，直接输出修复后内容，不加任何解释。
"""


def build_repair_prompt(
    raw: str,
    diagnosis: str,
    tool_names: list[str],
) -> str:
    """Construct a bilingual repair prompt for the repair LLM."""
    tool_list = ", ".join(tool_names) if tool_names else "(none registered)"
    return _REPAIR_TEMPLATE.format(
        diagnosis=diagnosis,
        raw=raw.strip(),
        tool_list=tool_list,
    )


def repair(
    repair_llm,
    raw: str,
    diagnosis: str,
    tool_names: list[str],
) -> str | None:
    """
    Call repair_llm to fix a malformed ReAct output.

    Returns the repaired text if the result re-parses to anything other than
    FAILED quality, or None if the repair LLM's output is still unparseable.

    FAILED is always rejected regardless of is_finish — a FAILED result means
    the parser found no structured action at all, which is never acceptable.

    Intentionally does NOT catch exceptions — a hard failure in the repair
    LLM (e.g. network error) should propagate so the caller can decide
    whether to fall through to Layer 4.
    """
    prompt = build_repair_prompt(raw, diagnosis, tool_names)
    repaired = repair_llm.generate(prompt)

    if not repaired or not repaired.strip():
        return None

    # Verify the repaired text is actually parseable before returning it.
    check = parse_llm_output(repaired, tool_names=frozenset(tool_names))
    if check.quality == ParseQuality.FAILED:
        return None

    return repaired
