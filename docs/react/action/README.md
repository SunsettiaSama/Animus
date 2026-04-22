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
    └── word_count.py
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
