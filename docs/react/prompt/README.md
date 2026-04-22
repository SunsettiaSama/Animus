# react/prompt

ReAct Prompt 编排模块，负责将工具描述、三层记忆上下文与当前问题组装成 LLM 可消费的消息序列。

## 文件结构

```
src/react/prompt/
├── __init__.py     # 统一导出（含 StaticPromptParts）
├── template.py     # 模板数据结构 + 中英预设 + 注册表
├── block.py        # PromptBlock 基类 + 所有具体块（底层构建单元）
├── manager.py      # 主路径：面向消息的 PromptManager + 静态缓存支持
└── builder.py      # 辅助路径：面向纯文本的 PromptBuilder（当前主流程未使用）
```

---

## 分层设计

```
template.py          → 提供文本模板和语言配置
    │
    ▼
block.py             → 以模板 + 数据构造自描述的 PromptBlock 对象（底层）
    │
    ▼
manager.py           → 声明块列表，组装为 list[BaseMessage]（主路径）
builder.py           → 声明块列表，组装为纯文本 str（辅助路径）
```

底层的构建契约由 `PromptBlock` 定义，所有上层的 build 过程均以块对象为基础展开。

---

## block.py — Prompt 块层（底层）

### 基类

```python
class PromptBlock(ABC):
    @abstractmethod
    def render(self) -> str | None:
        """返回渲染后的文本，返回 None 表示本次跳过此块。"""
```

所有具体块继承 `PromptBlock` 并实现 `render()`，扩展新块只需继承此基类。

### 内置具体块

| 块类 | 归属消息 | 条件 | 说明 |
|---|---|---|---|
| `SystemBlock(text)` | system | 始终渲染 | ReAct 指令 + 工具列表 |
| `MemoryBlock(header, separator, content)` | system | content 非空时渲染 | 长期或中期记忆区段 |
| `QuestionBlock(prefix, question)` | human | 始终渲染 | 问题前缀 + 当前问题 |
| `StepsBlock(step_format, steps)` | human | steps 非空时渲染 | 当前轮 TAO 轨迹 |
| `SuffixBlock(text)` | human | 始终渲染 | `"Thought:"` 引导续写 |

### 扩展方式

新增内容块只需继承 `PromptBlock`，实现 `render()`，然后插入对应的块列表，无需修改任何现有代码：

```python
class FewShotBlock(PromptBlock):
    def __init__(self, examples: list[str]) -> None:
        self._examples = examples

    def render(self) -> str | None:
        if not self._examples:
            return None
        return "\n".join(self._examples)
```

---

## template.py — 模板层

定义数据结构 `ReActTemplate`，承载所有文本模板字段：

| 字段 | 类型 | 用途 |
|---|---|---|
| `system` | `PromptTemplate` | 系统指令，含 `{tool_list}` 占位符 |
| `long_term_header` | `str` | 长期记忆区段标题 |
| `medium_term_header` | `str` | 中期摘要区段标题 |
| `question_prefix` | `str` | 问题前缀（`"Question:"` / `"问题："`) |
| `suffix` | `str` | 引导续写尾缀，固定为 `"Thought:"` |
| `step_format` | `PromptTemplate` | 单步 TAO 轨迹格式（Thought/Action/Action Input/Observation）|
| `separator` | `str` | 区段分隔线 `"---"` |

预置 `EN`（英文）和 `CN`（中文）两套，通过 `get_template(lang)` 按语言取出。

---

## manager.py — 主路径（与 TaoLoop 集成）

### 初始化

```python
PromptManager(tool_descriptions: dict[str, str], cfg: PromptConfig | None = None)
```

1. 从 `PromptConfig.lang` 选取模板。
2. 将 `tool_descriptions` 格式化后填入 `system` 模板，得到 `_base_system`（实例生命周期内固定不变）。
3. 构造 LangChain `ChatPromptTemplate`，骨架为：

```
[SystemMessage:        {system}        ]
[MessagesPlaceholder:  history         ]
[HumanMessage:         {current_input} ]
```

### build_messages（完整路径）

每个 ReAct 步（首轮或无缓存时）调用，基于块列表完整渲染所有部件：

```python
system_blocks = [
    SystemBlock(self._base_system),                                          # 始终
    *extra_system_blocks,                                                    # persona 注入
    MemoryBlock(tpl.long_term_header,  tpl.separator, result.long_term),    # 条件
    MemoryBlock(tpl.medium_term_header, tpl.separator, result.medium_term), # 条件
]
human_blocks = [
    QuestionBlock(tpl.question_prefix, question),   # 始终
    StepsBlock(tpl.step_format, result.short_term), # 条件
    SuffixBlock(tpl.suffix),                        # 始终
]
```

### build_static（后台预热，`post_process()` 调用）

构建**不依赖下一个问题**的静态部件，返回 `StaticPromptParts`：

```python
def build_static(
    self,
    medium_term: str = "",
    extra_system_blocks: list[PromptBlock] | None = None,
) -> StaticPromptParts:
    ...
```

```python
@dataclass
class StaticPromptParts:
    system_without_lt: str       # base_system + persona + medium_term（长期记忆槽位留空）
    history: list[BaseMessage]   # add_turn() 后的历史快照
```

预热后缓存到 `TaoLoop._static_cache`，下轮问题到达时直接使用，**无需重新渲染 persona / medium_term**。

### build_messages_from_static（快速路径）

第 2 轮起使用，只需填入长期检索文本和本步动态内容：

```python
def build_messages_from_static(
    self,
    static: StaticPromptParts,
    question: str,
    long_term: str = "",
    short_term: list[Step] | None = None,
) -> list[BaseMessage]:
    # 1. 将 long_term 注入 system_without_lt
    # 2. 拼接 human = question + steps + suffix
    # 3. 用 static.history 替代 _history（快照，已含当前 add_turn）
    ...
```

两条路径产出格式完全一致，对 LLM 透明。

### 多轮历史维护

| 方法 | 说明 |
|---|---|
| `add_turn(question, answer)` | 追加一轮 Q/A 到 `_history` |
| `clear_history()` | 清空全部历史 |
| `turn_count` | 已记录的轮数 |
| `recent_turns(k)` | 返回最近 k 轮 (question, answer) 对，供 consolidation 使用 |

---

## builder.py — 辅助路径

`PromptBuilder` 与 `PromptManager` 共享同一套块定义，区别仅在于组装方式：将所有块线性拼接为**单个纯文本字符串**，不维护多轮历史。

**当前主流程（TaoLoop）未使用此类**，适合无会话状态的单次推理场景。

---

## 完整数据流

```
TaoLoop.__init__
  └─ PromptManager(tool_descriptions, cfg.prompt)
        ├─ get_template(lang) → ReActTemplate
        └─ _base_system = tpl.system.format(tool_list=...)

每个 ReAct 步（i==0，无缓存）:
  processor.recall(question, include_long_term=True)
    └─ MemoryResult { long_term, medium_term, short_term }
          │
          ▼
  PromptManager.build_messages(question, result, persona_blocks)
    └─ 完整渲染 → list[BaseMessage] → LLM

每个 ReAct 步（i==0，有缓存 / i>0）:
  processor.recall(question, include_long_term=(i==0))
    └─ _cached_lt = result.long_term (i==0 时缓存)
          │
          ▼
  PromptManager.build_messages_from_static(cache, question, _cached_lt, short_term)
    └─ 快速注入 → list[BaseMessage] → LLM

Action == "finish"？
  └─ Yes → post_process():
              manager.add_turn(question, answer)
              manager.build_static(medium_term, persona_blocks) → _static_cache
```

---

## 与其他模块的依赖关系

| 模块 | 关系 |
|---|---|
| **memory** | `build_messages` 接收 `MemoryResult`；`build_static` 读取 `processor.medium_distillate` |
| **action** | 无直接 import；工具描述通过构造函数参数传入，由 `SystemBlock` 渲染 |
| **llm** | `build_messages / build_messages_from_static` 产出 `list[BaseMessage]`，交给 LLM |
| **config** | `PromptConfig.lang` 控制语言模板选择 |
| **loop** | `ConvLoop.restore` 通过 `manager.add_turn` 重放历史消息以恢复会话 |
