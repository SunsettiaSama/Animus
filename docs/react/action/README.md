# react/action

动作空间模块，负责动作的注册、解析与执行。输入为 JSON 字符串，输出为字符串结果。

## 文件

| 文件 | 说明 |
|---|---|
| `base.py` | `BaseAction` 抽象基类 |
| `executor.py` | `ActionExecutor` 注册表与执行器 |
| `tools/weather.py` | 占位天气工具（固定返回） |

## 使用方式

### 定义动作

```python
from react.action.base import BaseAction

class SearchAction(BaseAction):
    name = "search"

    def execute(self, query: str, **kwargs) -> str:
        return f"搜索结果：{query}"
```

### 注册与执行

```python
from react.action.executor import ActionExecutor

executor = ActionExecutor()
executor.register(SearchAction)

result = executor.run('{"action": "search", "args": {"query": "python"}}')
```

### JSON 输入格式

```json
{
    "action": "动作名称",
    "args": { "参数键": "参数值" }
}
```

`args` 字段可省略（无参动作）。

## 内置工具

### `WeatherAction`

测试占位工具，无论输入何种参数，始终返回：

```
7月1日，晴天，温度为30~35°
```

替换真实 API 时只需修改 `execute()` 方法内部实现。

## 错误处理

- 未注册的动作名 → 抛出 `ValueError`
- 非法 JSON 输入 → 抛出 `json.JSONDecodeError`
