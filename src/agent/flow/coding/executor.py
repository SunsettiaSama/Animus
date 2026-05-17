"""coding/executor.py — CodeNodeExecutor：ManifestExecutor 实现。

单轮模式（无工具）
    直接调用一次 LLM，返回生成结果。

工具增强模式（注入 CodingToolSuite）
    内嵌 mini-ReAct 循环：LLM 可按轮次调用工具（读文件、运行代码等），
    直至输出 FINAL_ANSWER 或达到 max_tool_iters 上限。

工具调用格式（LLM 约定输出）
    TOOL: <tool_name>
    ARGS:
    param1: value1
    param2: value2
    ---

    或者结束输出：
    FINAL_ANSWER:
    <实际代码或内容>
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from agent.flow.base.components.node_spec import NodeManifest

LlmCallFn = Callable[[str, str], str]


# ── 角色 → System prompt ───────────────────────────────────────────────────────

_SYSTEM_DESIGN = """\
You are a software architect. Produce a clear design artifact:
module structure, key interfaces, data models, and API contracts.
Output Markdown with code blocks for signatures.
Do NOT write full implementations — only contracts and structure.
"""

_SYSTEM_IMPLEMENT = """\
You are a senior software engineer. Implement the task described below.
Write complete, runnable code with no placeholders or TODOs.
Follow the design and upstream interfaces provided in the context.
Output only the code (with a brief one-line comment at the top of each file/section).
"""

_SYSTEM_TEST = """\
You are a QA engineer. Write a comprehensive test suite for the code provided.
Cover: happy path, edge cases, error conditions.
Use the standard test framework for the target language.
Output only the test code.
"""

_SYSTEM_REVIEW = """\
You are a code reviewer and refactoring expert.
Review the provided code for: correctness, clarity, performance, security, style.
Produce an improved version with inline review comments (# REVIEW: ...) explaining changes.
Output the improved code followed by a short review summary.
"""

_SYSTEM_INTEGRATE = """\
You are a software integrator. Combine the modules and components described below
into a cohesive, working whole. Resolve any interface mismatches and produce
the final integration code (entry point, wiring, configuration).
"""

_SYSTEM_FALLBACK = """\
You are a software engineer. Complete the coding task described below.
Write complete, correct, and well-structured code.
"""

_SYSTEM_BY_ROLE: dict[str, str] = {
    "code:design":     _SYSTEM_DESIGN,
    "code:implement":  _SYSTEM_IMPLEMENT,
    "code:test":       _SYSTEM_TEST,
    "code:review":     _SYSTEM_REVIEW,
    "code:integrate":  _SYSTEM_INTEGRATE,
}


def _coding_role_key(manifest: NodeManifest) -> str:
    """与 planner 产出的 tags[\"coding_role\"] 对齐；兼容旧版 ``tool_package=\"code:xxx\"``。"""
    tags = manifest.tags or {}
    role = str(tags.get("coding_role", "")).strip().lower()
    if not role:
        tp = manifest.tool_package or ""
        if isinstance(tp, str) and tp.startswith("code:") and tp != "code":
            role = tp[5:].strip().lower()
    if not role:
        role = "implement"
    return f"code:{role}"

# ── 工具增强版 system prompt 后缀 ──────────────────────────────────────────────

_TOOL_SUFFIX = """
## Tools Available
You have access to the following tools. Use them when you need to inspect files,
run code to verify correctness, or write outputs to disk.

{tool_list}

## Tool Call Format
When you want to call a tool, output EXACTLY this format (nothing before or after):

TOOL: <tool_name>
ARGS:
param1: value1
param2: value2
---

When you are done and have the final answer, output EXACTLY:

FINAL_ANSWER:
<your final code or content here>

You MUST end with FINAL_ANSWER. Iterate using tools as many times as needed first.
"""

# ── User prompt ────────────────────────────────────────────────────────────────

_USER_TMPL = """\
## Task
{description}

## Language
{language}
{context_section}"""

_CONTEXT_SECTION = """
## Upstream Context
{upstream}"""


def _build_user_prompt(
    description: str,
    language: str,
    upstream: dict[str, Any],
    extra: str = "",
) -> str:
    ctx = ""
    if upstream:
        parts = "\n\n".join(
            f"### [{dep}]\n{str(out)}" for dep, out in upstream.items() if out
        )
        ctx = _CONTEXT_SECTION.format(upstream=parts)
    base = _USER_TMPL.format(
        description=description,
        language=language,
        context_section=ctx,
    )
    return base + extra


# ── mini-ReAct 解析 ────────────────────────────────────────────────────────────

_TOOL_CALL_RE = re.compile(
    r"TOOL:\s*(?P<name>\w+)\s*\nARGS:\s*\n(?P<args>.*?)---",
    re.DOTALL,
)
_FINAL_ANSWER_RE = re.compile(
    r"FINAL_ANSWER:\s*\n(?P<answer>.*)",
    re.DOTALL,
)


def _parse_tool_call(text: str) -> tuple[str, dict[str, str]] | None:
    m = _TOOL_CALL_RE.search(text)
    if not m:
        return None
    name = m.group("name").strip()
    args: dict[str, str] = {}
    for line in m.group("args").splitlines():
        line = line.strip()
        if ":" in line:
            k, _, v = line.partition(":")
            args[k.strip()] = v.strip()
    return name, args


def _parse_final_answer(text: str) -> str | None:
    m = _FINAL_ANSWER_RE.search(text)
    return m.group("answer").strip() if m else None


def _append_observation(history: str, tool_name: str, observation: str) -> str:
    return history + f"\nOBSERVATION ({tool_name}):\n{observation}\n"


# ── CodeNodeExecutor ──────────────────────────────────────────────────────────

class CodeNodeExecutor:
    """ManifestExecutor 实现 — 以 LLM 驱动的代码生成节点执行体。

    无工具（默认）
        单轮 LLM 调用，prompt → 代码。

    有工具（注入 CodingToolSuite）
        mini-ReAct 循环：LLM → TOOL call → 观察 → LLM → ... → FINAL_ANSWER。

    节点角色由 ``manifest.tags[\"coding_role\"]`` 决定（或由旧版 ``tool_package=\"code:角色\"`` 推断）：
        design / implement / test / review / integrate
    """

    def __init__(
        self,
        llm_call: LlmCallFn,
        language: str = "python",
        tools: "Any | None" = None,   # CodingToolSuite | None
        max_tool_iters: int = 6,
    ) -> None:
        self._llm = llm_call
        self._language = language
        self._tools = tools
        self._max_iters = max_tool_iters

    def run(
        self,
        manifest: NodeManifest,
        inputs: Mapping[str, Any],
        ctx: Any = None,
    ) -> str:
        role_key = _coding_role_key(manifest)
        base_system = _SYSTEM_BY_ROLE.get(role_key, _SYSTEM_FALLBACK)

        if self._tools is not None:
            return self._run_with_tools(base_system, manifest, inputs)
        return self._run_single(base_system, manifest.description, dict(inputs))

    # ── 单轮模式 ──────────────────────────────────────────────────────────────

    def _run_single(
        self,
        system: str,
        description: str,
        upstream: dict[str, Any],
    ) -> str:
        user = _build_user_prompt(description, self._language, upstream)
        return self._llm(system, user)

    # ── 工具增强模式（mini-ReAct）────────────────────────────────────────────

    def _run_with_tools(
        self,
        base_system: str,
        manifest: NodeManifest,
        inputs: Mapping[str, Any],
    ) -> str:
        tool_list = self._tools.render_tool_list()
        system = base_system + _TOOL_SUFFIX.format(tool_list=tool_list)
        user = _build_user_prompt(
            manifest.description,
            self._language,
            dict(inputs),
        )

        conversation = user
        for _ in range(self._max_iters):
            response = self._llm(system, conversation)

            # 优先检查 FINAL_ANSWER
            answer = _parse_final_answer(response)
            if answer is not None:
                return answer

            # 检查工具调用
            call = _parse_tool_call(response)
            if call is None:
                # LLM 没有按格式输出 —— 把整个 response 作为最终结果
                return response.strip()

            tool_name, tool_args = call
            observation = self._tools.call(tool_name, **tool_args)
            conversation = response + _append_observation(
                "", tool_name, observation
            )

        # 超过迭代上限：让 LLM 给出最终答案
        response = self._llm(
            system,
            conversation + "\n\n[达到工具调用上限，请直接输出 FINAL_ANSWER]",
        )
        answer = _parse_final_answer(response)
        return answer if answer is not None else response.strip()
