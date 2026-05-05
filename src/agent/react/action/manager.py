from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from ..action.executor import ActionExecutor
from ..action.tools import (
    Base64Action,
    CalculatorAction,
    FileExistsAction,
    FileListAction,
    FileReadAction,
    FileWriteAction,
    GenerateUUIDAction,
    GetDatetimeAction,
    GetWeekdayAction,
    HashAction,
    HttpRequestAction,
    JsonQueryAction,
    NoteDeleteAction,
    NoteReadAction,
    NoteWriteAction,
    PythonRunAction,
    RandomChoiceAction,
    RandomNumberAction,
    RegexExtractAction,
    StringTransformAction,
    TextDiffAction,
    ToolMeta,
    ToolRegistry,
    ToolSearchAction,
    UnitConverterAction,
    WeatherAction,
    WebSearchAction,
    WordCountAction,
)
from ..action.tools.impl.web_fetch import WebFetchAction
from ..action.tools.impl.knowledge_hybrid_search import KnowledgeHybridSearchAction
from ..action.tools.impl.knowledge_save import KnowledgeSaveAction
from ..action.tools.impl.knowledge_list import KnowledgeListAction
from ..action.tools.impl.scheduler_add import SchedulerAddAction
from ..action.tools.impl.scheduler_list import SchedulerListAction
from ..action.tools.impl.scheduler_cancel import SchedulerCancelAction

if TYPE_CHECKING:
    from ..action.mcp.registry import MCPRegistry, MCPToolInfo
    from ..action.skill.registry import SkillRegistry, SkillMeta

# 默认主要工具（在 prompt 中展示给 Agent 的 5 个）
DEFAULT_PRIMARY: list[str] = [
    "calculator",
    "get_datetime",
    "web_search",
    "unit_converter",
    "word_count",
]


def _build_default_registry() -> ToolRegistry:
    """构建包含所有内置工具的默认注册表。"""
    reg = ToolRegistry()
    reg.add(CalculatorAction,      category="math",       tags=["计算", "数学", "表达式", "calculator"])
    reg.add(GetDatetimeAction,     category="time",       tags=["时间", "日期", "时区", "datetime"])
    reg.add(GetWeekdayAction,      category="time",       tags=["星期", "日期", "weekday"])
    reg.add(WeatherAction,         category="search",     tags=["天气", "weather", "城市"])
    reg.add(WebSearchAction,       category="search",     tags=["搜索", "互联网", "duckduckgo", "查询"])
    reg.add(WebFetchAction,        category="search",     tags=["网页", "抓取", "全文", "url", "fetch"])
    reg.add(UnitConverterAction,   category="conversion", tags=["换算", "单位", "长度", "重量", "温度", "面积"])
    reg.add(WordCountAction,       category="text",       tags=["字数", "统计", "文本", "字符"])
    reg.add(StringTransformAction, category="text",       tags=["字符串", "大小写", "反转", "文本处理"])
    reg.add(Base64Action,          category="text",       tags=["base64", "编码", "解码"])
    reg.add(HashAction,            category="text",       tags=["哈希", "md5", "sha256", "加密"])
    reg.add(RandomNumberAction,    category="random",     tags=["随机", "随机数", "random"])
    reg.add(RandomChoiceAction,    category="random",     tags=["随机", "选择", "抽签"])
    reg.add(GenerateUUIDAction,    category="random",     tags=["uuid", "唯一标识符", "随机"])
    reg.add(KnowledgeHybridSearchAction, category="knowledge", tags=["知识库", "混合检索", "语义搜索", "关键词", "hybrid", "knowledge"])
    reg.add(KnowledgeSaveAction,   category="knowledge",  tags=["知识库", "保存", "写入", "学习"])
    reg.add(KnowledgeListAction,   category="knowledge",  tags=["知识库", "列表", "领域", "已知边界"])
    reg.add(SchedulerAddAction,    category="scheduler",  tags=["调度", "预约", "时间轴", "定时", "scheduler", "once", "interval"])
    reg.add(SchedulerListAction,   category="scheduler",  tags=["调度", "时间轴", "列表", "查看", "scheduler"])
    reg.add(SchedulerCancelAction, category="scheduler",  tags=["调度", "取消", "时间轴", "cancel", "scheduler"])
    reg.add(JsonQueryAction,       category="data",       tags=["json", "jsonpath", "查询", "提取", "数据"])
    reg.add(RegexExtractAction,    category="data",       tags=["正则", "提取", "匹配", "regex", "pattern"])
    reg.add(TextDiffAction,        category="data",       tags=["差异", "对比", "diff", "文本比较"])
    reg.add(FileReadAction,        category="filesystem", tags=["文件", "读取", "本地", "file", "read"])
    reg.add(FileWriteAction,       category="filesystem", tags=["文件", "写入", "保存", "file", "write"])
    reg.add(FileListAction,        category="filesystem", tags=["目录", "文件列表", "ls", "file", "list"])
    reg.add(FileExistsAction,      category="filesystem", tags=["文件", "存在", "检查", "file", "exists"])
    reg.add(HttpRequestAction,     category="network",    tags=["http", "请求", "api", "rest", "post", "get"])
    reg.add(PythonRunAction,       category="code",       tags=["python", "代码", "执行", "计算", "脚本"])
    reg.add(NoteWriteAction,       category="workspace",  tags=["笔记", "草稿本", "记录", "note", "write"])
    reg.add(NoteReadAction,        category="workspace",  tags=["笔记", "草稿本", "读取", "note", "read"])
    reg.add(NoteDeleteAction,      category="workspace",  tags=["笔记", "草稿本", "删除", "note", "delete"])
    return reg


class ToolManager:
    """
    分级工具管理器。

    层级结构
    --------
    Layer 1 — primary tools（5 个，始终在 prompt 中展示）
    Layer 2 — tool_search（特殊元工具，始终展示，用于扩展发现）
    Layer 3 — full registry（executor 预加载全部工具，含 skill + mcp）

    扩展注册
    --------
    - skill_registry : SkillRegistry  →  技能合并进 ToolRegistry（可搜索）
    - mcp_registry   : MCPRegistry    →  MCP 工具加载为 BaseTool 实例注入 executor

    LangChain 接口
    -------------
    - as_langchain_tools()       → 全量 BaseTool 列表（含 skill、mcp）
    - primary_langchain_tools()  → 仅主要工具 + tool_search 的 BaseTool 列表
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        primary_names: list[str] | None = None,
        skill_registry: SkillRegistry | None = None,
        mcp_registry: MCPRegistry | None = None,
    ) -> None:
        self._registry: ToolRegistry = registry or _build_default_registry()
        self._primary_names: list[str] = primary_names or list(DEFAULT_PRIMARY)
        self._skill_registry: SkillRegistry | None = skill_registry
        self._mcp_registry: MCPRegistry | None = mcp_registry

        if skill_registry:
            self._merge_skills(skill_registry)

    # --- 内部合并 ---

    def _merge_skills(self, skill_registry: SkillRegistry) -> None:
        """将 SkillRegistry 中的技能合并进主 ToolRegistry。"""
        for action_cls, category, tags in skill_registry.to_tool_entries():
            self._registry.add(action_cls, category=category, tags=tags)

    # --- 属性 ---

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def skill_registry(self) -> SkillRegistry | None:
        return self._skill_registry

    @property
    def mcp_registry(self) -> MCPRegistry | None:
        return self._mcp_registry

    @property
    def primary_names(self) -> list[str]:
        return list(self._primary_names)

    # --- 动态挂载 ---

    def mount_skill_registry(self, skill_registry: SkillRegistry) -> None:
        """运行时挂载技能注册表（自动合并进 ToolRegistry）。"""
        self._skill_registry = skill_registry
        self._merge_skills(skill_registry)

    def mount_mcp_registry(self, mcp_registry: MCPRegistry) -> None:
        """运行时挂载 MCP 注册表（build_executor 时自动加载工具）。"""
        self._mcp_registry = mcp_registry

    # --- executor 构建 ---

    def build_executor(self) -> ActionExecutor:
        """
        构建 ActionExecutor。

        注册顺序：
        1. ToolRegistry 中的全量工具（class 注册）
        2. MCP 工具（BaseTool 实例，通过 register_lc_tool）
        3. ToolSearchAction（BaseAction 实例，注入 manager 引用）
        """
        executor = ActionExecutor()

        for meta in self._registry.all():
            executor.register(meta.action_cls)

        if self._mcp_registry:
            for tool in self._mcp_registry.load_all():
                executor.register_lc_tool(tool)

        executor.register_instance(ToolSearchAction(manager=self))
        return executor

    # --- prompt 描述 ---

    def primary_descriptions(self, names: list[str] | None = None) -> dict[str, str]:
        """
        返回用于构建 prompt 的工具描述字典。

        始终包含 tool_search；若 names 为 None，使用默认主要工具列表。
        """
        selected = names if names is not None else self._primary_names
        result: dict[str, str] = {}
        for name in selected:
            meta = self._registry.get(name)
            if meta:
                result[name] = meta.description
        result["tool_search"] = ToolSearchAction.model_fields["description"].default
        return result

    # --- 搜索（跨 tool/skill/mcp） ---

    def search(self, query: str, top_k: int = 5) -> list[ToolMeta]:
        """
        搜索全量工具库（含 skill），排除已在 prompt 中展示的主要工具。

        MCP 工具不在 ToolRegistry 中，单独通过 search_mcp() 查询。
        """
        return self._registry.search(
            query,
            top_k=top_k,
            exclude=self._primary_names + ["tool_search"],
        )

    def search_mcp(self, query: str, top_k: int = 5) -> list[MCPToolInfo]:
        """在已加载的 MCP 工具中搜索（需先调用 mcp_registry.load_tools）。"""
        if self._mcp_registry is None:
            return []
        return self._mcp_registry.search(query, top_k)

    def search_skills(self, query: str, top_k: int = 5) -> list[SkillMeta]:
        """在 SkillRegistry 中搜索技能（与 ToolRegistry 搜索结果可能重叠）。"""
        if self._skill_registry is None:
            return []
        return self._skill_registry.search(query, top_k)

    # --- LangChain 接口 ---

    def as_langchain_tools(self) -> list[BaseTool]:
        """
        全量 BaseTool 列表，含 tool/skill/mcp + tool_search。

        可直接传入任意 LangChain Agent（create_react_agent 等）。
        """
        tools: list[BaseTool] = self._registry.as_langchain_tools()
        if self._mcp_registry:
            tools.extend(self._mcp_registry.load_all())
        tools.append(ToolSearchAction(manager=self))
        return tools

    def primary_langchain_tools(self) -> list[BaseTool]:
        """主要工具 + tool_search 的 BaseTool 列表（轻量 Agent 使用）。"""
        tools = self._registry.as_langchain_tools(self._primary_names)
        tools.append(ToolSearchAction(manager=self))
        return tools

    # --- 工具目录摘要（注入 prompt 用） ---

    def category_summary(self) -> str:
        """
        返回按 category 分组的工具目录摘要字符串，用于注入系统提示词。

        示例输出：
            [可用工具目录 — 共N个]
            search(3): web_search, web_fetch, weather
            knowledge(3): knowledge_hybrid_search, knowledge_save, knowledge_list
            → 使用 tool_search(query) 查看任意工具详细说明
        """
        from collections import defaultdict

        groups: dict[str, list[str]] = defaultdict(list)
        for meta in self._registry.all():
            groups[meta.category].append(meta.name)

        total = sum(len(names) for names in groups.values())
        lines = [f"[可用工具目录 — 共 {total} 个]"]
        for category in sorted(groups):
            names = groups[category]
            lines.append(f"  {category}({len(names)}): {', '.join(names)}")
        lines.append("→ 使用 tool_search(query) 查看任意工具的详细说明")
        return "\n".join(lines)

    # --- 工具信息（API 层使用） ---

    def all_tool_info(self) -> list[dict]:
        tool_info = [
            {
                "name": m.name,
                "description": m.description,
                "category": m.category,
                "tags": m.tags,
                "source": "tool",
                "is_primary": m.name in self._primary_names,
            }
            for m in self._registry.all()
        ]
        if self._mcp_registry:
            for info in self._mcp_registry.loaded_tool_info():
                tool_info.append({
                    "name": info.name,
                    "description": info.description,
                    "category": "mcp",
                    "tags": ["mcp", info.server_name],
                    "source": "mcp",
                    "is_primary": False,
                })
        return tool_info
