# react/action

动作空间模块，负责工具的注册、Pydantic 参数校验与执行。输入为 JSON 字符串，输出为字符串结果。

## 目录结构

```
src/react/action/
├── __init__.py        # 统一导出
├── base.py            # BaseAction 抽象基类（含 args_model ClassVar）
├── executor.py        # ActionExecutor — 注册表 + Pydantic 校验 + 执行
├── manager.py         # ToolManager — 多类型工具聚合 + 描述生成
├── registry.py        # 兼容层，转发到 tools/registry.py
└── tools/             # 所有工具实现（含注册表）
    ├── __init__.py    # 统一导出工具类 + ToolMeta + ToolRegistry
    ├── registry.py    # ToolMeta + ToolRegistry
    ├── calculator.py
    ├── datetime_tool.py
    ├── random_tool.py
    ├── string_tool.py
    ├── tool_search.py
    ├── unit_converter.py
    ├── weather.py
    ├── web_search.py
    ├── word_count.py
    └── impl/                         # 实例注入型工具（需外部依赖）
        ├── web_fetch.py              # 网页全文抓取
        ├── memory_recall.py          # 长期 / 里程碑记忆召回
        ├── knowledge_hybrid_search.py# 知识库混合检索
        ├── knowledge_save.py         # 知识库写入
        ├── knowledge_list.py         # 知识库领域列表
        ├── scheduler_add.py          # 预约调度任务（一次性 / 周期性）
        ├── scheduler_list.py         # 查看时间轴上所有任务
        ├── scheduler_cancel.py       # 取消调度任务
        ├── file_system.py            # 沙箱文件读写 / 列目录 / 判断存在
        ├── http_request.py           # 通用 HTTP 请求（GET/POST/PUT/DELETE/PATCH）
        ├── python_run.py             # 受限沙箱 Python 代码执行
        ├── scratchpad.py             # 会话级 K-V 草稿本（note_write/read/delete）
        ├── data_tool.py              # JSONPath 查询 / 正则提取 / 文本 diff
        ├── delegate_task.py          # 同步委派子 Agent（阻塞等待结果）
        ├── spawn_agent.py            # 异步派发子 Agent（立即返回 agent_id）
        ├── get_agent_result.py       # 查询异步子 Agent 结果
        ├── spawn_all.py              # 批量并行派发（Fan-out）
        ├── await_agent.py            # 阻塞等待单个子 Agent 完成
        ├── await_all.py              # 阻塞等待全部子 Agent（Fan-in）
        └── plan_tools.py             # Plan 编排工具（run_plan / plan_status / plan_pause / plan_skip / plan_snapshot / plan_rollback）
```

---

## 核心组件

### `BaseAction`（`base.py`）

所有工具的抽象基类，继承自 `langchain_core.tools.BaseTool`：

```python
class BaseAction(BaseTool, ABC):
    args_model: ClassVar[type[BaseModel] | None] = None  # Pydantic 参数 Schema
    name: str                                             # 工具名称
    description: str                                      # 工具描述

    @abstractmethod
    def execute(self, **kwargs) -> str: ...
```

子类通过 `args_model` 声明参数 Schema，校验由 `ActionExecutor` 统一负责，`execute()` 无需手动验证参数。

### `ActionExecutor`（`executor.py`）

注册工具并执行：

```python
executor = ActionExecutor()
executor.register(CalculatorAction)          # 注册类
executor.register_instance(tool_instance)    # 注册实例（MCP/Skill 等）

result = executor.run('{"action": "calculator", "args": {"expression": "1+1"}}')
```

执行前自动调用 `_coerce()` 进行 Pydantic 校验，将非法参数转换为 `ValueError`。

#### 执行路径

```
executor.run(json_str)
  └─ 解析 JSON → action, args
       │
       ├─ 查找已注册的 BaseAction 子类（按 name）
       │     └─ _coerce(cls, args)          ← Pydantic 校验/类型转换
       │           action_instance.execute(**validated_args)
       │
       └─ 查找已注册的实例（按 name）
             └─ _coerce(instance, args)     ← 同上
                   instance.execute(**validated_args)
```

### `ToolManager`（`manager.py`）

聚合多类型工具（内置工具 / Skill / MCP），构建 `ActionExecutor`，提供工具描述供 Prompt 组装：

```python
manager = ToolManager()

# 构建执行器（注册所有工具）
executor = manager.build_executor()

# 获取主工具描述（字典，key=name, value=description）
descriptions = manager.primary_descriptions(primary_names=["calculator", "web_search"])

# 获取全部工具信息（含分类）
manager.all_tool_info()   # list[dict]，含 name/description/category

# 语义搜索工具
manager.search("天气查询", top_k=5)  # list[ToolMeta]

# 注册表（只读）
manager.registry          # dict[str, ToolMeta]
manager.primary_names     # list[str]（默认主工具列表）
```

---

## Pydantic 参数校验（Zod 风格）

每个工具定义独立的 `XxxArgs(BaseModel)` 作为参数 Schema，并通过 `args_model` 关联：

```python
class CalculatorArgs(BaseModel):
    expression: str = Field(..., min_length=1, description="数学表达式")

class CalculatorAction(BaseAction):
    name = "calculator"
    args_model = CalculatorArgs

    def execute(self, expression: str, **kwargs) -> str:
        # 此处 expression 已经过类型检查和约束验证
        ...
```

`ActionExecutor._coerce()` 在执行前实例化 `args_model`，失败时抛出含字段路径和错误描述的 `ValueError`，便于 LLM 识别并修正参数。

### 各工具 Args Schema 一览

#### 内置类注册工具（category: math / time / text / random / search / conversion）

| 工具 | Args 类 | 主要约束 |
|---|---|---|
| `CalculatorAction` | `CalculatorArgs` | `expression: str`（非空）|
| `DatetimeAction` | `DatetimeArgs` | `timezone: str`（可选）|
| `RandomAction` | `RandomArgs` | `low < high`（`model_validator`）|
| `StringAction` | `StringArgs` | `operation: Literal[...]`（枚举）|
| `ToolSearchAction` | `ToolSearchArgs` | `query: str`，`top_k: int`（1~20）|
| `UnitConverterAction` | `UnitConverterArgs` | `category / from_unit / to_unit: Literal[...]` |
| `WeatherAction` | `WeatherArgs` | `city: str`（非空）|
| `WebSearchAction` | `WebSearchArgs` | `query: str`，`num_results: int`（1~10）|
| `WordCountAction` | `WordCountArgs` | `text: str` |

#### 实例注入型工具（category: scheduler）

调度工具需要 `TaoConfig.scheduler` 为非 `None`，由 `TaoLoop.__init__` 注入 `SchedulerEngine` 实例。

| 工具 | 主要参数 | 说明 |
|---|---|---|
| `scheduler_add` | `name, instruction, trigger_type, at, interval_seconds, profile` | 预约一次性或周期性任务 |
| `scheduler_list` | 无 | 查看时间轴上所有任务及状态 |
| `scheduler_cancel` | `task_id` | 取消指定调度任务 |

`profile` 可选 `minimal`（仅 LLM + 工具）/ `with_memory`（开启长期记忆）/ `full`（记忆 + 人格）。

#### 实例注入型工具（category: sandbox）

沙箱工具需要 `SandboxManager` 注入，由 `TaoLoop.__init__` 完成。操作均限制在沙箱 `workspace_root` 目录内。

| 工具 | 主要参数 | 说明 |
|---|---|---|
| `file_read` | `path, encoding, max_chars` | 读取文件内容（txt/json/csv/md 等纯文本）|
| `file_write` | `path, content, mode` | 写入或追加文件（mode: write/append）|
| `file_list` | `path, recursive` | 列出目录内容（可递归）|
| `file_exists` | `path` | 检查文件或目录是否存在 |
| `http_request` | `url, method, headers, body, json_body, timeout` | 通用 HTTP 请求（域名受沙箱 allow/block list 约束）|
| `python_run` | `code` | 在受限沙箱中执行 Python 代码片段，禁止访问文件系统和网络 |

#### 实例注入型工具（category: scratchpad）

会话草稿本工具，需要 `ScratchpadStore` 注入。数据存储在内存中，生命周期与当前会话一致，`reset()` 时清空。

| 工具 | 主要参数 | 说明 |
|---|---|---|
| `note_write` | `key, content` | 写入一条笔记（K-V）|
| `note_read` | `key` | 读取笔记；key 留空则列出全部摘要 |
| `note_delete` | `key` | 删除指定笔记 |

#### 实例注入型工具（category: data）

数据处理工具，无需外部依赖（`json_query` 需安装 `jsonpath-ng`）。

| 工具 | 主要参数 | 说明 |
|---|---|---|
| `json_query` | `data, path` | JSONPath 查询 JSON 数据 |
| `regex_extract` | `text, pattern, flags, max_matches` | 正则表达式提取（支持 i/m/s 标志）|
| `text_diff` | `text_a, text_b, context_lines` | 输出 unified diff 格式文本差异 |

#### 实例注入型工具（category: crew）

Crew 工具需要 `TaoConfig.crew` 为非 `None`，由 `TaoLoop.__init__` 注入 `CrewManager` 实例。**子 Agent 的 `TaoConfig` 中 `crew=None`、`scheduler=None`，禁止递归嵌套（planner profile 除外）。**

| 工具 | 主要参数 | 语义 | 编排模式 |
|---|---|---|---|
| `delegate_task` | `instruction, profile` | 同步委派，阻塞等待结果 | 顺序 |
| `spawn_agent` | `instruction, profile` | 异步派发，立即返回 `agent_id` | 异步单任务 |
| `get_agent_result` | `agent_id` | 非阻塞查询结果 | 轮询 |
| `spawn_all` | `tasks`（JSON 数组）| 批量并行派发所有任务 | Fan-out |
| `await_agent` | `agent_id, timeout` | 阻塞等待单个完成 | 同步等待 |
| `await_all` | `agent_ids`（JSON 数组）, `timeout` | 等待全部完成并汇总 | Fan-in |

`profile` 可选 `minimal`（全工具集）/ `researcher`（搜索 + 知识库工具集）/ `analyst`（计算 + 分析工具集）/ `planner`（任务规划编排，支持递归），或自定义。

---

## 工具注册表（`ToolRegistry`）

存储所有已注册工具的元信息：

```python
@dataclass
class ToolMeta:
    name: str
    description: str
    category: str = "general"
    tags: list[str] = field(default_factory=list)
```

`ToolRegistry` 以 `dict[str, ToolMeta]` 形式维护注册表，支持按名称查找和语义搜索（TF-IDF 近似）。

---

## 使用方式

### 定义新工具

```python
from pydantic import BaseModel, Field
from react.action.base import BaseAction

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

`args` 字段可省略（无参工具）。未注册的工具名 → `ValueError`；非法 JSON → `json.JSONDecodeError`；参数校验失败 → `ValueError`（含字段错误详情）。

---

## Agent 当前完整能力一览

下表列出 WebUI 中 ReAct Agent 初始化后可调用的全部工具（按 category 分组）。基础工具始终可用；知识库、调度、Crew、沙箱等工具需对应 `TaoConfig` 字段非 `None`。

| Category | 工具名 | 触发条件 | 一句话说明 |
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
| data | `regex_extract` | 始终 | 正则表达式提取（支持 i/m/s 标志）|
| data | `text_diff` | 始终 | 输出两段文本的 unified diff 差异 |
| memory | `memory_recall` | 长期记忆启用时 | 检索长期 / 里程碑记忆 |
| knowledge | `knowledge_hybrid_search` | KB 启用时 | 知识库混合检索 |
| knowledge | `knowledge_save` | KB 启用时 | 向知识库写入新内容 |
| knowledge | `knowledge_list` | KB 启用时 | 列出知识库已有领域 |
| scheduler | `scheduler_add` | `TaoConfig.scheduler` 非空 | 预约一次性或周期性 Agent 任务 |
| scheduler | `scheduler_list` | 同上 | 查看所有调度任务及状态 |
| scheduler | `scheduler_cancel` | 同上 | 取消调度任务 |
| sandbox | `file_read` | `SandboxManager` 注入 | 读取沙箱工作区文件内容 |
| sandbox | `file_write` | 同上 | 向沙箱工作区写入 / 追加文件 |
| sandbox | `file_list` | 同上 | 列出沙箱目录内容（可递归）|
| sandbox | `file_exists` | 同上 | 检查沙箱文件或目录是否存在 |
| sandbox | `http_request` | 同上 | 通用 HTTP 请求（域名受沙箱 allow/block list 约束）|
| sandbox | `python_run` | 同上 | 受限沙箱中执行 Python 代码片段 |
| scratchpad | `note_write` | `ScratchpadStore` 注入 | 向会话草稿本写入笔记（K-V）|
| scratchpad | `note_read` | 同上 | 读取草稿本笔记；留空则列出全部 |
| scratchpad | `note_delete` | 同上 | 删除草稿本指定笔记 |
| crew | `delegate_task` | `TaoConfig.crew` 非空 | 同步委派子 Agent，阻塞等结果 |
| crew | `spawn_agent` | 同上 | 异步派发子 Agent，返回 agent_id |
| crew | `get_agent_result` | 同上 | 查询异步子 Agent 结果 |
| crew | `spawn_all` | 同上 | 批量并行派发（Fan-out）|
| crew | `await_agent` | 同上 | 等待单个子 Agent 完成 |
| crew | `await_all` | 同上 | 等待全部子 Agent 并汇总（Fan-in）|
| plan | `run_plan` | `TaoConfig.plan` 非空 | 启动 Plan-and-Execute 多智能体编排，返回执行结果 |
| plan | `plan_status` | 同上 | 查询当前计划 DAG 执行状态 |
| plan | `plan_pause` | 同上 | 暂停 / 恢复计划执行 |
| plan | `plan_skip` | 同上 | 跳过指定任务（`task_id`）|
| plan | `plan_snapshot` | 同上 | 手动保存计划快照 |
| plan | `plan_rollback` | 同上 | 回滚到指定快照（`snapshot_id`）|
