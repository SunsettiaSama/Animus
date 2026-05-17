from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable

from agent.flow.base.components.node_spec import NodeManifest
from agent.flow.base.plan_spec import ManifestPlanSpec

from .config import CodingConfig

LlmCallFn = Callable[[str, str], str]

# ── Planner system prompt ─────────────────────────────────────────────────────

_SYSTEM = """\
You are a coding task planner. Decompose a software development goal into a DAG
of coding nodes. Each node has a specific role and may depend on others.

Node roles:
  design     — Architecture, interfaces, data models (no implementation)
  implement  — Write the actual code for one module or component
  test       — Write tests for a specific implementation node
  review     — Review + improve a test or implement node
  integrate  — Wire multiple components into the final entry point

Rules:
  1. Start with design nodes (no dependencies).
  2. Each implement node should depend on at least one design node.
  3. Each test node should depend on the implement node it tests.
  4. A review node depends on the node it reviews.
  5. Finish with an integrate node if there are multiple implement nodes.
  6. Keep total node count ≤ {max_nodes}.
  7. task_id must be snake_case, unique, and descriptive.

Output ONLY a JSON array. No markdown fences, no explanation.
Schema per node:
  {{"task_id": str, "role": str, "description": str, "depends_on": [str]}}
"""

_USER = """\
Goal: {goal}
Language: {language}
{extra}

Produce the JSON node array now."""


# ── JSON 解析 ─────────────────────────────────────────────────────────────────

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")


def _extract_json(text: str) -> list[dict]:
    m = _JSON_ARRAY_RE.search(text)
    raw = m.group(0) if m else text.strip()
    return json.loads(raw)


def _nodes_to_manifests(nodes: list[dict], cfg: CodingConfig) -> list[NodeManifest]:
    seen: set[str] = set()
    manifests: list[NodeManifest] = []
    for n in nodes:
        tid = str(n["task_id"]).strip()
        if tid in seen:
            continue
        seen.add(tid)
        role = str(n.get("role", "implement")).strip().lower()
        manifests.append(
            NodeManifest(
                task_id=tid,
                description=str(n.get("description", tid)),
                depends_on=tuple(str(d) for d in n.get("depends_on", [])),
                tool_package=cfg.default_tool_package,
                max_steps=cfg.subagent_max_steps,
                system_note=cfg.node_system_note(role),
                tags={"coding_role": role},
            )
        )
    return manifests[:cfg.max_nodes]


# ── CodePlanner ───────────────────────────────────────────────────────────────

class CodePlanner:
    """BasePlanner 实现 — 调用 LLM 将编码目标分解为 ManifestPlanSpec。

    返回的 ManifestPlanSpec 节点中：
        tool_package  = cfg.default_tool_package（默认 ``\"code\"``，与 react BUILTIN_PACKAGES 一致）
        tags[\"coding_role\"] = design / implement / test / ...
        system_note   = 角色说明 + 目标语言（供 SubAgent 与 inline executor 对齐语义）
        depends_on    = 原始 DAG 依赖
        description   = 该节点的具体编码任务说明
    """

    def __init__(self, llm_call: LlmCallFn, cfg: CodingConfig) -> None:
        self._llm = llm_call
        self._cfg = cfg

    async def plan(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
        step_callback: Any = None,
    ) -> ManifestPlanSpec:
        loop = asyncio.get_running_loop()
        spec = await loop.run_in_executor(None, self._plan_sync, goal)
        return spec

    def _plan_sync(self, goal: str) -> ManifestPlanSpec:
        cfg = self._cfg
        extra = f"Extra context: {cfg.extra_context}" if cfg.extra_context else ""
        system = _SYSTEM.format(max_nodes=cfg.max_nodes)
        user = _USER.format(
            goal=goal,
            language=cfg.language,
            extra=extra,
        )
        response = self._llm(system, user)
        nodes = _extract_json(response)
        manifests = _nodes_to_manifests(nodes, cfg)

        if not manifests:
            manifests = [
                NodeManifest(
                    task_id="implement_main",
                    description=goal,
                    depends_on=(),
                    tool_package=cfg.default_tool_package,
                    max_steps=cfg.subagent_max_steps,
                    system_note=cfg.node_system_note("implement"),
                    tags={"coding_role": "implement"},
                )
            ]

        return ManifestPlanSpec(
            title=goal[:80],
            objective=goal,
            manifests=manifests,
        )
