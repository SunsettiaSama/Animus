# react/prompt

ReAct 标准 Prompt 构造器，将工具描述、历史记忆和当前问题拼接成 LLM 可理解的格式。

## 核心类：`PromptBuilder`

```python
from react.prompt import PromptBuilder

builder = PromptBuilder(tool_descriptions={
    "weather": "查询天气，无需参数",
    "search": "搜索互联网，参数：query(str)",
})

prompt = builder.build(question="今天天气怎么样？", memory=memory)
```

## 生成的 Prompt 结构

```
You are a ReAct (Reasoning + Acting) agent...

Available tools:
- weather: 查询天气，无需参数
- search: 搜索互联网，参数：query(str)

Format your response STRICTLY as:
Thought: <your reasoning>
Action: <tool name>
Action Input: <JSON object with arguments>

When you have the final answer, use:
Thought: I now know the final answer.
Action: finish
Action Input: {"answer": "<your answer>"}

---
Question: 今天天气怎么样？
Thought: ...           ← 历史 Step 1
Action: weather
Action Input: {}
Observation: 7月1日，晴天，温度为30~35°
Thought:               ← LLM 从这里续写
```

## 设计要点

- 末尾以 `Thought:` 结尾，引导 LLM 自然续写，不需要额外指令
- 历史 Steps 按时间顺序排列，最旧在前
- `memory.steps()` 返回当前短期记忆窗口内的 Steps
