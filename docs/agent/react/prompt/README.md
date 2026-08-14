# agent/react/prompt

该模块把 ReAct 角色、工具说明、可选系统块、历史、medium-term、当前问题和本轮 Step
组装为 `list[BaseMessage]`。它不是 Soul/Speak 主对话的 Prompt 系统。

## 组成

- `template.py`：中英文 `ReActTemplate` 与输出格式文本；
- `block.py`：`SystemBlock`、`MemoryBlock`、`QuestionBlock`、`StepsBlock`、
  `SuffixBlock`；
- `manager.py`：`PromptManager` 与 `StaticPromptParts`；
- `parser.py`：XML/legacy 输出解析；
- `repair.py`：解析失败后的独立修复调用；
- `builder.py`：辅助的纯文本构建路径。

## 实际消息顺序

首次构建或无静态缓存时：

```text
system:
  react_role
  base_system（格式规则 + 有效工具描述 + 工具分类摘要）
  extra_system_blocks（Soul/persona；Worker 还含 AgentState 画像）
  medium_term

history:
  PromptManager._history 中已完成的 HumanMessage / AIMessage

human:
  QuestionBlock
  StepsBlock（当前问题内的工具轨迹）
  SuffixBlock
```

快速路径 `build_messages_from_static()` 使用缓存的 base/persona/history，再动态追加
medium-term、question、steps、suffix。`StaticPromptParts` 的真实字段是 `system` 和
`history`，不是旧的 `system_without_lt`。

当前 `MemoryResult` 只有 `short_term` 与 `medium_term`，所以 PromptManager 不会渲染
旧的 long-term、milestone、short-term-distillate 槽位。长期 Soul 内容需要通过
`soul_*` 工具主动获取，工具 observation 随后以 Step 进入 Prompt。

## Worker 额外 Prompt

`worker.react.TaoLoop` 在每轮开始调用 `AgentStateService.begin_turn(question)`：

1. 快照中的 `memory_portrait`、`worker_portrait`、`reflection_portrait` 作为
   `MemoryBlock` 加入 system；
2. 每次请求都重建 static cache，避免上轮反思被旧缓存遮蔽；
3. 当前 `TurnTaskGraph.render()` 再直接追加到 system；
4. 工具结果持续更新任务图，轮后提交 reflection。

这条链只存在于 `worker/react`，不能归因于 `agent/react` CLI 或 legacy WebUI。

## 输出解析与反馈

当前推荐输出是：

```text
<T>reasoning</T>
<A>[{"action": "tool_name", "args": {...}}]</A>
<O>optional user-visible output</O>
```

解析器仍兼容旧 `Action:` 格式。失败时 TaoLoop 依次执行 strict/lenient 解析、
in-context 格式纠正、repair LLM；仍失败则降级为 finish。工具 observation 被保存为
`Step`，`StepsBlock` 对新式多调用使用 XML，对旧单调用使用 legacy 模板。

## 与 Soul/Speak 的区别

Soul/Speak 在 `agent/soul/speak/pipelines/` 组装 `SpeakPromptBundle`，其上下文包括
Presence/persona、session working memory、context distill、相似记忆、interactor
portrait、guidance/director plan 等，并由 `SpeakLLMEngine` 调用模型。该数据流不复用
`PromptManager`、`MemoryResult` 或 `StepsBlock`，也不经过 TaoLoop。
