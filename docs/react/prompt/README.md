# react/prompt

ReAct Prompt 编排模块，负责将角色定义、工具描述、四层记忆上下文与当前问题组装为 LLM 可消费的消息序列。

## 文件结构

```
src/react/prompt/
├── __init__.py     # 统一导出
├── template.py     # MemoryTierLabel + ReActTemplate + 中英预设 + 注册表
├── block.py        # PromptBlock 基类 + 所有具体块（底层构建单元）
├── manager.py      # 主路径：面向消息的 PromptManager + 静态缓存支持
└── builder.py      # 辅助路径：面向纯文本的 PromptBuilder（单次推理场景）
```

---

## 分层设计

```
template.py          → 提供文本模板和结构化标签（MemoryTierLabel）
    │
    ▼
block.py             → 以模板 + 数据构造自描述的 PromptBlock（底层）
    │
    ▼
manager.py           → 声明块列表，组装为 list[BaseMessage]（主路径）
builder.py           → 声明块列表，组装为纯文本 str（辅助路径）
```

---

## block.py — Prompt 块层

### 基类

```python
class PromptBlock(ABC):
    @abstractmethod
    def render(self) -> str | None:
        """返回渲染后的文本，返回 None 表示跳过此块。"""
```

### 内置具体块

| 块类 | 签名 | 归属消息 | 条件 | 说明 |
|---|---|---|---|---|
| `SystemBlock(text)` | `text: str` | system | 始终渲染 | ReAct 格式指令 + 工具列表 |
| `MemoryBlock(title, desc, separator, content)` | 见下 | system / human | content 非空时渲染 | 各层记忆区段 |
| `QuestionBlock(prefix, question)` | | human | 始终渲染 | 问题前缀 + 当前问题 |
| `StepsBlock(step_format, steps)` | | human | steps 非空时渲染 | 当前轮 TAO 轨迹 |
| `SuffixBlock(text)` | | human | 始终渲染 | `"Thought:"` 引导续写 |

### MemoryBlock 渲染格式

```python
MemoryBlock(title, desc, separator, content).render()
```

输出（content 为空时返回 `None`，整块跳过）：

```
---
## [区段标题]
一句话描述这段内容的来源和用途。

<具体内容>
```

### 扩展方式

新增内容块只需继承 `PromptBlock`，实现 `render()`：

```python
class FewShotBlock(PromptBlock):
    def render(self) -> str | None:
        return "\n".join(self._examples) if self._examples else None
```

---

## template.py — 模板层

### `MemoryTierLabel`

```python
@dataclass
class MemoryTierLabel:
    title: str   # markdown 标题，如 "## 【L2 中期记忆】"
    desc: str    # 一句话描述

    def render(self, content: str = "", separator: str = "---") -> str | None:
        """独立渲染为标准块格式（与 MemoryBlock 约定完全一致）。"""
```

### `ReActTemplate`

| 字段 | 类型 | 用途 |
|---|---|---|
| `system` | `PromptTemplate` | ReAct 格式指令，含 `{tool_list}` 占位符 |
| `react_role` | `MemoryTierLabel` | 智能体身份与能力说明（系统提示最顶层） |
| `chat_role` | `MemoryTierLabel` | 纯 chat 模式的角色职责说明 |
| `long_term` | `MemoryTierLabel` | L3 长期记忆区段标签 |
| `milestone` | `MemoryTierLabel` | 里程碑记忆区段标签 |
| `medium_term` | `MemoryTierLabel` | L2 中期记忆区段标签 |
| `short_term_distillate` | `MemoryTierLabel` | L1 蒸馏摘要区段标签 |
| `question_prefix` | `str` | 问题前缀 |
| `suffix` | `str` | `"Thought:"` 引导续写 |
| `step_format` | `PromptTemplate` | 单步 TAO 格式（Thought/Action/Action Input/Observation）|
| `separator` | `str` | 区段分隔线 `"---"` |

预置 `EN`（英文）和 `CN`（中文）两套，通过 `get_template(lang)` 按语言取出。

---

## manager.py — 主路径

### 初始化

```python
PromptManager(tool_descriptions: dict[str, str], cfg: PromptConfig | None = None)
```

- 从 `PromptConfig.lang` 选取模板
- 将工具描述格式化后填入 `system` 模板，得到 `_base_system`
- 预渲染 `_role_prefix`（智能体身份块，每次系统消息都前置）
- 构造 LangChain `ChatPromptTemplate`：

```
[SystemMessage:        {system}        ]
[MessagesPlaceholder:  history         ]
[HumanMessage:         {current_input} ]
```

### 系统提示组成顺序

每条系统消息由以下块按序拼接（`\n\n` 分隔）：

```
_role_prefix                        ← react_role 块（身份 + 能力说明）
_base_system                        ← ReAct 格式指令 + 工具列表
*extra_system_blocks                ← Persona 注入（可选）
MemoryBlock(medium_term, ...)       ← L2 近期历史（条件）
MemoryBlock(milestone, ...)         ← 里程碑记忆（条件）
MemoryBlock(long_term, ...)         ← L3 向量检索（条件）
```

Human 消息组成顺序：

```
QuestionBlock                       ← 问题
MemoryBlock(short_term_distillate)  ← L1 蒸馏摘要（条件）
StepsBlock                          ← 当前轮 TAO 轨迹（条件）
SuffixBlock                         ← "Thought:"
```

### build_messages（完整路径）

```python
def build_messages(
    self,
    question: str,
    result: MemoryResult,
    extra_system_blocks: list[PromptBlock] | None = None,
) -> list[BaseMessage]:
```

### build_static（后台预热）

`post_process()` 在后台线程中调用，预先渲染不依赖下一问题的部分：

```python
@dataclass
class StaticPromptParts:
    system_without_lt: str       # role + base_system + persona（记忆槽位留空）
    history: list[BaseMessage]   # add_turn() 后的历史快照
```

### build_messages_from_static（快速路径）

第 2 轮起使用，只填入动态部分：

```python
def build_messages_from_static(
    self,
    static: StaticPromptParts,
    question: str,
    long_term: str = "",
    medium_term: str = "",
    milestone: str = "",
    short_term: list[Step] | None = None,
    short_term_distillate: str = "",
) -> list[BaseMessage]:
```

---

## 完整数据流

```
TaoLoop.__init__
  └─ PromptManager(tool_descriptions, cfg.prompt)
        ├─ get_template(lang) → ReActTemplate
        ├─ _base_system = tpl.system.format(tool_list=...)
        └─ _role_prefix = tpl.react_role.render()

每步推理（i==0，无缓存）:
  processor.recall(query, include_long_term=True)
    └─ MemoryResult { short_term, short_term_distillate, medium_term, milestone, long_term }
          │
          ▼
  PromptManager.build_messages(question, result, persona_blocks)
    └─ 完整渲染 → list[BaseMessage] → LLM

每步推理（有缓存 / i>0）:
  PromptManager.build_messages_from_static(cache, question, long_term, medium_term, milestone, ...)
    └─ 快速注入 → list[BaseMessage] → LLM

Action == "finish" → post_process() [后台线程]:
    processor.commit(question, answer)
    manager.add_turn(question, answer)
    manager.build_static(persona_blocks) → TaoLoop._static_cache
```

---

## 与其他模块的依赖

| 模块 | 关系 |
|---|---|
| **memory** | `build_messages` 接收 `MemoryResult`（含所有五个字段）|
| **action** | 工具描述通过构造函数传入，由 `SystemBlock` 渲染 |
| **llm** | 产出 `list[BaseMessage]`，交给 LLM 消费 |
| **config** | `PromptConfig.lang` 控制语言模板选择 |
| **loop** | `ConvLoop.restore` 通过 `manager.add_turn` 重放历史恢复会话 |
| **webui** | chat 模式使用 `tpl.chat_role.render()` 构建系统消息 |
