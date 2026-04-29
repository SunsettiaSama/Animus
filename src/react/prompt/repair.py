from __future__ import annotations

from react.prompt.parser import ParseResult, parse_llm_output, ParseQuality

# ── Repair prompt template ────────────────────────────────────────────────────

_REPAIR_TEMPLATE = """\
You are a format-repair assistant for a ReAct-style language model agent.

The agent must output its response in this EXACT format:
---
Thought: <reasoning about what to do>
Action: <tool_name>
Action Input: {{"key": "value"}}
---

If the agent wants to give a final answer, it uses:
---
Thought: <reasoning>
Action: finish
Action Input: {{"answer": "<final answer text>"}}
---

## Problem
The following output could not be parsed correctly.
Diagnosis: {diagnosis}

## Original (broken) output
{raw}

## Available tools
{tool_list}

## Your task
Rewrite the broken output strictly following the format above.
- Keep the original intent and reasoning.
- Do NOT add explanations — output ONLY the corrected ReAct block.
- The Action must be one of the available tools listed above, or "finish".
- Action Input must be valid JSON.

---
以下是中文说明（同上）：
你是一个 ReAct 格式修复助手。
请将上面的"破损输出"重写为标准 ReAct 格式，保留原始意图，直接输出修复后内容，不加任何解释。
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

    Returns the repaired text if the result re-parses to CLEAN or LENIENT
    quality, or None if the repair LLM's output is also unparseable.

    Intentionally does NOT catch exceptions — a hard failure in the repair
    LLM (e.g. network error) should propagate so the caller can decide
    whether to fall through to Layer 0.
    """
    prompt = build_repair_prompt(raw, diagnosis, tool_names)
    repaired = repair_llm.generate(prompt)

    if not repaired or not repaired.strip():
        return None

    # Verify the repaired text is actually parseable before returning it.
    check = parse_llm_output(repaired, tool_names=frozenset(tool_names))
    if check.quality == ParseQuality.FAILED and not check.is_finish:
        return None

    return repaired
