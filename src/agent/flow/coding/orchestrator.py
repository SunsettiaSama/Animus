from __future__ import annotations

import asyncio
import time
from typing import Any

from agent.flow.base.components.node_spec import NodeManifest
from agent.flow.base.components.runtime import NodeResult
from agent.flow.base.dag_orchestrator import DagOrchestrator
from agent.flow.base.defaults import SubAgentManifestExecutor
from agent.flow.base.plan_spec import ManifestPlanSpec
from agent.flow.base.registry import get_registry
from agent.flow.base.types import NodeStatus

from .config import CodingConfig
from .executor import CodeNodeExecutor, LlmCallFn
from .planner import CodePlanner
from .replanner import CodeReplanner
from .result import CodeResult
from .tools import CodingToolSuite


class CodeOrchestrator(DagOrchestrator):
    """基于 base.DagOrchestrator 的代码生成 DAG 编排器。

    与父类的差别
    -----------
    · 覆写 _dispatch_atomic：不经 RunnableNode / NodeRuntimeManager，在线程池里直接执行。

    两种执行后端（与 base 对齐）
    -----------------------------
    · **React 工具链**（``CodingConfig.use_react_action=True`` 且无 ``CodingToolSuite``）：
      使用 :class:`SubAgentManifestExecutor`，与 ``register_defaults`` 下 DagOrchestrator
      相同 — ``NodeManifest.tool_package`` 引用 ``agent.react.action.manager`` 里的包名
      （默认 ``\"code\"`` → ``python_run`` / ``file_read`` / ``file_write`` 等）。

    · **内联**（``use_react_action=False`` 或显式传入 ``tools=...``）：
      :class:`CodeNodeExecutor`（纯 LLM 或 mini-ReAct + :class:`CodingToolSuite`）。

    Planner 产出的节点始终使用 ``cfg.default_tool_package``（默认 ``\"code\"``）作为
    ``tool_package``，角色放在 ``tags[\"coding_role\"]``，与 base 文档中
    ``NodeManifest.tool_package`` 语义一致。

    使用示例
    --------
    内联 LLM（单测 / 无需真实 SubAgent）::

        orch = CodeOrchestrator(my_llm, CodingConfig(use_react_action=False))

    与 base 相同 — react Action + 配置文件 LLM::

        orch = CodeOrchestrator(
            my_llm,
            CodingConfig(
                use_react_action=True,
                llm_cfg_path="config/llm_core/config.yaml",
                default_tool_package="code",
            ),
        )
    """

    def __init__(
        self,
        llm_call: LlmCallFn,
        cfg: CodingConfig | None = None,
        tools: CodingToolSuite | None = None,
    ) -> None:
        cfg = cfg or CodingConfig()
        self._cfg = cfg

        use_react = cfg.use_react_action and tools is None
        self._use_react_action = use_react

        reg = get_registry()
        if cfg.default_tool_package and not reg.is_package_known(cfg.default_tool_package):
            reg.register_packages(cfg.default_tool_package)

        if use_react:
            self._react_executor: SubAgentManifestExecutor | None = SubAgentManifestExecutor(
                cfg.llm_cfg_path
            )
            self._code_executor: CodeNodeExecutor | None = None
        else:
            self._react_executor = None
            self._code_executor = CodeNodeExecutor(
                llm_call,
                language=cfg.language,
                tools=tools,
                max_tool_iters=cfg.max_tool_iters,
            )

        planner = CodePlanner(llm_call, cfg)
        replanner = CodeReplanner(llm_call, max_cycles=cfg.max_replan_cycles)

        super().__init__(
            planner=planner,
            atomic_planner=None,
            registry=None,
            replanner=replanner,
            parallel_limit=cfg.parallel_limit,
            replanner_triggers={"on_task_failed", "on_plan_complete"},
        )

    # ── 覆写：原子节点执行（不经 RunnableNode）──────────────────────────────

    async def _dispatch_atomic(
        self,
        node_id: str,
        spec: ManifestPlanSpec,
    ) -> NodeResult:
        manifest: NodeManifest = spec.manifest(node_id)
        inputs: dict[str, Any] = {
            dep: self._outputs[dep]
            for dep in manifest.depends_on
            if dep in self._outputs
        }

        t0 = time.monotonic()
        loop = asyncio.get_running_loop()

        if self._use_react_action:
            assert self._react_executor is not None
            output = await loop.run_in_executor(
                self._executor_pool,
                self._react_executor.run,
                manifest,
                inputs,
                None,
            )
        else:
            assert self._code_executor is not None
            output = await loop.run_in_executor(
                self._executor_pool,
                self._code_executor.run,
                manifest,
                inputs,
                None,
            )

        self._outputs[node_id] = output
        return NodeResult(
            task_id=node_id,
            status=NodeStatus.done,
            output=output,
            elapsed_seconds=time.monotonic() - t0,
        )

    # ── 便捷 API ───────────────────────────────────────────────────────────

    async def run_coding(self, goal: str) -> CodeResult:
        result = await self.run(goal)
        return CodeResult.from_run(
            plan_id=result.plan_id,
            status=result.status,
            goal=goal,
            outputs=dict(self._outputs),
            conclusion=result.answer or "",
        )
