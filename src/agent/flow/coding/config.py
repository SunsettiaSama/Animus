from __future__ import annotations

from dataclasses import dataclass


_ROLE_SYSTEM_NOTES: dict[str, str] = {
    "design": (
        "本节点为架构/设计：产出模块结构、接口与数据契约说明，不要写完整业务实现。"
    ),
    "implement": (
        "本节点为实现：编写可运行、无占位符的完整代码，遵循上游设计与接口。"
    ),
    "test": (
        "本节点为测试：编写覆盖主路径、边界与异常的测试用例。"
    ),
    "review": (
        "本节点为审查：检查正确性与风格，给出改进版代码与简要审查结论。"
    ),
    "integrate": (
        "本节点为集成：将各模块拼装为可运行的整体（入口、依赖注入、配置）。"
    ),
}


@dataclass
class CodingConfig:
    """CodeOrchestrator 的配置项。

    language             生成代码所用编程语言，注入节点 system_note / inline executor。
    max_nodes            Planner 最多生成的节点数。
    parallel_limit       同时执行的节点数上限（0 = 不限制）。
    max_replan_cycles    on_task_failed 最多触发重规划次数。
    plan_timeout_secs    占位（单节点超时由 SubAgent / 外层控制）。
    extra_context        注入到 Planner prompt 的额外上下文。
    max_tool_iters       仅 inline + CodingToolSuite：mini-ReAct 最大轮次。

    default_tool_package 与 agent.react.action.manager.BUILTIN_PACKAGES 中的包名一致，
                         默认 ``\"code\"``（含 python_run / file_read / file_write 等），
                         供 SubAgentProfile / NodeManifest.tool_package 引用，与 base 一致。

    use_react_action     True：节点执行走 agent.flow.base.defaults.SubAgentManifestExecutor
                         → SubAgentRunner → react Action 工具链（与 DagOrchestrator + register_defaults 同源）。
                         False：走 CodeNodeExecutor（纯 LLM 或 CodingToolSuite）。传入 tools 非空时强制为 False。

    llm_cfg_path         use_react_action=True 时必填（传给 SubAgentManifestExecutor）。
    subagent_max_steps   写入每个 NodeManifest.max_steps；None 则执行器用内置默认。
    """

    language: str = "python"
    max_nodes: int = 8
    parallel_limit: int = 4
    max_replan_cycles: int = 1
    plan_timeout_secs: float = 0.0
    extra_context: str = ""
    max_tool_iters: int = 6

    default_tool_package: str = "code"
    use_react_action: bool = False
    llm_cfg_path: str = "config/llm_core/config.yaml"
    subagent_max_steps: int | None = 15

    def node_system_note(self, role: str) -> str:
        r = (role or "implement").strip().lower()
        base = _ROLE_SYSTEM_NOTES.get(r, _ROLE_SYSTEM_NOTES["implement"])
        parts = [base, f"目标编程语言：{self.language}。"]
        return "\n".join(parts)
