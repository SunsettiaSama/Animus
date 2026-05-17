# agent/react/action

动作空间模块，负责工具的注册、Pydantic 参数校验与执行。输入为 JSON 字符串，输出为字符串结果。

## 目录结构

```
src/agent/react/action/
├── __init__.py        # 统一导出
├── base.py            # BaseAction 抽象基类（含 args_model ClassVar）
├── executor.py        # ActionExecutor — 注册表 + Pydantic 校验 + 执行
├── manager.py         # ToolManager — 多类型工具聚合 + 描述生成
├── registry.py        # 兼容层，转发到 tools/registry.py
├── tools/             # 内置工具（class 注册）
│   ├── __init__.py    # 统一导出工具类 + ToolMeta + ToolRegistry
│   ├── registry.py    # ToolMeta + ToolRegistry
│   ├── tool_search.py # ToolSearchAction（元工具，始终注入）
│   └── impl/          # 实例注入型工具（需 TaoLoop 注入依赖）
│       ├── web_fetch.py
│       ├── memory_recall.py
│       ├── scheduler_add.py
│       ├── scheduler_list.py
│       ├── scheduler_cancel.py
│       ├── timeline_read.py
│       ├── file_system.py
│       ├── http_request.py
│       ├── python_run.py
│       ├── scratchpad.py
│       ├── data_tool.py
│       ├── notify_user.py
│       ├── send_notification.py
│       ├── send_bot_message.py
│       └── plan_tools.py     # 遗留 plan_* Action（默认 TaoLoop 未注册；当前 Flow 走 flow_skill）
├── mcp/               # MCP 工具协议（Model Context Protocol）
│   ├── base.py
│   └── registry.py    # MCPRegistry — MCP 工具加载与搜索
├── skill/             # Skill 技能（复合 LLM 调用工具）
│   ├── base.py        # BaseSkill 基类
│   ├── registry.py    # SkillRegistry
│   ├── delegate_task.py  # DelegateTaskSkill — 子 Agent 同步委派
│   ├── domain_learning.py
│   ├── research.py
│   ├── document_summary.py
│   └── flow_skill.py    # FlowSkillSet — run_flow / flow_status / flow_wait / flow_skip（由 TaoLoop 按 cfg.flow 注入）
└── risk/              # 风险评估门控
    ├── level.py       # RiskLevel + OperationRisk
    ├── assessor.py    # BaseRiskAssessor / RuleBasedAssessor / ExternalAPIAssessor
    ├── allow_list.py  # AllowList — 允许规则
    └── gate.py        # RiskGate — 配置驱动的审批/阻断门控
```

---

## 核心组件

### `BaseAction`（`base.py`）

所有工具的抽象基类：

```python
from agent.react.action.base import BaseAction

class MyAction(BaseAction):
    name = "my_tool"
    description = "描述工具用途"
    args_model = MyArgs

    def execute(self, **kwargs) -> str: ...
```

### `ActionExecutor`（`executor.py`）

注册工具并执行：

```python
executor = ActionExecutor()
executor.register(CalculatorAction)          # 注册类
executor.register_instance(tool_instance)    # 注册实例（Skill / MCP 等）

result = executor.run('{"action": "calculator", "args": {"expression": "1+1"}}')
```

### `ToolManager`（`manager.py`）

分级工具管理器，聚合 Tool / Skill / MCP，构建 `ActionExecutor`：

```python
manager = ToolManager(
    skill_registry=skill_registry,   # 可选，注入 Skill
    mcp_registry=mcp_registry,       # 可选，注入 MCP 工具
)

executor = manager.build_executor()
descriptions = manager.primary_descriptions()    # 主要工具描述（Prompt 用）
category_summary = manager.category_summary()    # 分类目录摘要字符串
```

层级结构：
- **Layer 1**：primary tools（5 个，始终在 prompt 中展示）
- **Layer 2**：`tool_search`（始终展示，用于扩展发现）
- **Layer 3**：full registry（executor 预加载全部工具，含 Skill + MCP）

---

## Pydantic 参数校验

每个工具定义独立的 `XxxArgs(BaseModel)` 作为参数 Schema：

```python
from pydantic import BaseModel, Field

class CalculatorArgs(BaseModel):
    expression: str = Field(..., min_length=1, description="数学表达式")

class CalculatorAction(BaseAction):
    name = "calculator"
    args_model = CalculatorArgs

    def execute(self, expression: str, **kwargs) -> str: ...
```

`ActionExecutor._coerce()` 在执行前实例化 `args_model`，失败时抛出含字段路径的 `ValueError`，便于 LLM 识别并修正参数。

---

## Agent 完整工具一览

下表列出 `TaoLoop` 初始化后可调用的全部工具，按 category 分组。

| Category | 工具名 | 触发条件 | 说明 |
|---|---|---|---|
| math | `calculator` | 始终 | 数学表达式计算 |
| time | `get_datetime` | 始终 | 获取当前日期时间（可指定时区）|
| time | `get_weekday` | 始终 | 获取指定日期的星期 |
| search | `weather` | 始终 | 查询城市天气 |
| search | `web_search` | 始终 | DuckDuckGo / SearXNG 搜索 |
| search | `web_fetch` | 始终 | 抓取指定 URL 的网页全文 |
| conversion | `unit_converter` | 始终 | 单位换算（长度 / 重量 / 温度 / 面积）|
| text | `word_count` | 始终 | 字数 / 字符统计 |
| text | `string_transform` | 始终 | 字符串大小写 / 反转 / 处理 |
| text | `base64` | 始终 | Base64 编码 / 解码 |
| text | `hash` | 始终 | MD5 / SHA256 哈希 |
| random | `random_number` | 始终 | 生成随机数 |
| random | `random_choice` | 始终 | 从列表中随机选择 |
| random | `generate_uuid` | 始终 | 生成 UUID |
| general | `tool_search` | 始终 | 语义搜索全部工具（元工具）|
| data | `json_query` | 始终 | JSONPath 查询 JSON 数据 |
| data | `regex_extract` | 始终 | 正则表达式提取 |
| data | `text_diff` | 始终 | 输出两段文本的 unified diff 差异 |
| workspace | `note_write` | 始终（TaoLoop 自动注入）| 向会话草稿本写入笔记（K-V）|
| workspace | `note_read` | 始终 | 读取草稿本笔记；留空则列出全部 |
| workspace | `note_delete` | 始终 | 删除草稿本指定笔记 |
| memory | `memory_recall` | 长期记忆或里程碑启用时 | 主动检索长期 / 里程碑记忆 |
| knowledge | （已移除）| `KnowledgeBase` 包不存在 | `knowledge_*` 工具块留在源码仅当配置误启用时会失败；请保持 **`TaoConfig.knowledge=None`** |
| scheduler | `scheduler_add` | `TaoConfig.scheduler` 非空 | 预约一次性或周期性 Agent 任务 |
| scheduler | `scheduler_list` | 同上 | 查看所有调度任务及状态 |
| scheduler | `scheduler_cancel` | 同上 | 取消调度任务 |
| scheduler | `timeline_read` | `TaoConfig.scheduler` 非空 | 读取会话时间线事件（`SchedulerEngine` 注入）|
| filesystem | `file_read` | `SandboxManager` 注入 | 读取沙箱工作区文件内容 |
| filesystem | `file_write` | 同上 | 向沙箱工作区写入 / 追加文件 |
| filesystem | `file_list` | 同上 | 列出沙箱目录内容（可递归）|
| filesystem | `file_exists` | 同上 | 检查沙箱文件或目录是否存在 |
| network | `http_request` | 同上 | 通用 HTTP 请求（域名受沙箱 allow/block list 约束）|
| code | `python_run` | 同上 | 受限沙箱中执行 Python 代码片段 |
| notify | `notify_user` | 始终（TaoLoop 自动注入）| 推理过程中向用户发送中间通知 |
| notify | `send_notification` | `AppState.bark_notifier` / `ntfy_notifier` 注入 | 通过 Bark / ntfy 推送通知（有频率限制）|
| notify | `send_bot_message` | `AppState.bot_service` 注入 | 通过 Bot 服务向目标发送消息（有频率限制）|
| skill | `delegate_task` | `TaoConfig.agent` 非空 | 同步委派子 Agent，阻塞等结果 |
| flow | `run_flow` | `TaoConfig.flow` 非空 | 异步启动 Flow DAG 编排（返回 flow_id）|
| flow | `flow_status` | 同上 | 查询当前 Flow / PlanDocument 执行状态 |
| flow | `flow_wait` | 同上 | 阻塞等待 Flow 完成（可超时）|
| flow | `flow_skip` | 同上 | 跳过指定 task_id（可选 cascade）|

> **legacy**：`tools/impl/plan_tools.py` 仍包含 `plan_status` 等 Action 类名，但 **`TaoLoop` 默认仅注入上述 `flow_*` Skill**（见 `flow_skill.py`）。REST `/api/plan/*` 等与编排观测相关的路由仍可能沿用「plan」用词，指同一套 Flow 编排器。

> **注意**：`note_write` / `note_read` / `note_delete`（workspace）由 TaoLoop 无条件注入，无需配置。`notify_user` 也无条件注入。`memory_recall` 由 TaoLoop 在长期记忆或里程碑至少一个启用时注入。`send_notification` / `send_bot_message` 需要 `AppState` 中对应的通知服务初始化后才注入。

---

## `DelegateTaskSkill`（`skill/delegate_task.py`）

子 Agent 同步委派工具，`TaoConfig.agent` 非空时由 `TaoLoop` 注入：

| 参数 | 说明 |
|---|---|
| `instruction` | 给子 Agent 的完整指令（必填）|
| `profile` | 子 Agent 能力配置：`minimal` / `executor` / `researcher` / `researcher_with_memory` / `analyst`，默认 `minimal` |

详见 [../../README.md](../../README.md)（`agent/` 层文档）。

---

## 定义新工具

```python
from pydantic import BaseModel, Field
from agent.react.action.base import BaseAction

class MyArgs(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(5, ge=1, le=20)

class MyAction(BaseAction):
    name = "my_tool"
    description = "描述工具用途"
    args_model = MyArgs

    def execute(self, query: str, limit: int = 5, **kwargs) -> str:
        return f"查询：{query}，限制：{limit}"
```

### JSON 输入格式

```json
{
    "action": "工具名称",
    "args": { "参数键": "参数值" }
}
```

未注册的工具名 → `ValueError`；非法 JSON → `json.JSONDecodeError`；参数校验失败 → `ValueError`（含字段错误详情）。
