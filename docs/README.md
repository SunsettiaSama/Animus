# ReAct 项目总览

基于 ReAct（Reasoning + Acting）范式的智能体框架，支持本地 Transformer 推理与 OpenAI 兼容 API，集成三层记忆系统、人格演化引擎与可扩展动作空间。

---

## 项目结构

```
src/
├── config/                  # 所有模块的配置 dataclass
│   ├── llm_core/            # LLM 核心配置
│   └── react/               # ReAct 各子模块配置
│       ├── memory/          # 记忆模块配置（short/medium/long/milestone）
│       └── persona_config   # 人格配置（含近期偏好字段）
├── llm_core/                # LLM 抽象层（本地 + OpenAI API）
├── react/                   # ReAct 核心框架
│   ├── action/              # 动作空间（工具 + MCP + Skill）
│   ├── memory/              # 三层记忆系统
│   │   ├── short_term/      # L1 短期（Token 滑动窗口）
│   │   ├── medium_term/     # 中期蒸馏（LLM 提炼）
│   │   ├── long_term/       # L3 长期（BGE + FAISS，含时序召回）
│   │   └── milestone/       # L2 里程碑（重要事件，关键词检索）
│   ├── prompt/              # 块驱动 Prompt 组装 + 静态缓存
│   ├── persona/             # 人格演化（稳定层 + 动态层）
│   │   ├── profile/         # 长期人格：画像 + 技能库 + 自省
│   │   └── preference/      # 近期偏好：情绪 / 话题兴趣 / 风格偏移（k 天滑动窗口）
│   ├── trace/               # 推理链存档
│   ├── loop.py              # ConvLoop — 外层多轮对话循环
│   ├── tao.py               # TaoLoop  — 内层 TAO 推理循环
│   └── parser.py            # LLM 输出解析
├── embedding/               # BGE 嵌入模型（FAISS 索引构建辅助）
├── cache/                   # 缓存根目录配置（CacheConfig）
├── webui/                   # Web 前端（FastAPI + 单页 HTML）
└── test/                    # 测试套件
```

---

## 已完成模块

| 模块 | 状态 | 说明 |
|---|---|---|
| `llm_core` | ✅ | 本地推理 + OpenAI API 双后端，流式输出 |
| `react/action` | ✅ | 工具注册、Pydantic 参数校验、执行调度（Tool / MCP / Skill）|
| `react/memory/short_term` | ✅ | Token 级滑动窗口 L1 短期记忆 |
| `react/memory/medium_term` | ✅ | LLM 蒸馏中期记忆，被驱逐步骤压缩摘要 |
| `react/memory/long_term` | ✅ | L3 BGE + FAISS，时间戳感知，五场景自动检索（含 TIMELINE）|
| `react/memory/milestone` | ✅ | L2 里程碑，LLM 重要性评分，关键词精确匹配（jieba 可选），detail 注入，溢出迁移 L3 |
| `react/prompt` | ✅ | 块驱动组装 + `StaticPromptParts` 静态缓存预热 |
| `react/persona/profile` | ✅ | 人物画像 + 技能库 + 自省（IROTE），LLM 演化引擎 |
| `react/persona/preference` | ✅ | 短期偏好动态层（mood / 话题兴趣 / 风格偏移），影响 L3 检索偏置 |
| `react/trace` | ✅ | 推理链存档（`.react/traces/`）|
| `react/loop` | ✅ | ConvLoop + TaoLoop 两层循环，异步后台提交，Prompt 预热 |
| `webui` | ✅ | ReAct + 普通对话双模式，Prompt 预览，人格配置，历史管理 |
| `test` | ✅ | 记忆模块 27 用例（含时序检索 + 模式检测）+ 工具测试 |

---

## 核心架构

```
用户输入
    │
    ▼
ConvLoop（多轮会话管理）
    │
    ▼
TaoLoop.stream(question)
    │
    ├─ bias_query = persona.bias_query(question)   ← 短期偏好偏置 L3 检索方向
    │
    ├─ processor.recall(bias_query)
    │       ├─ L1 短期   → StepsBlock（Human 消息）
    │       ├─ 中期蒸馏  → MemoryBlock（System 消息）
    │       ├─ L3 长期   → 向量检索，含 [DATE] 时间戳
    │       └─ L2 里程碑 → 关键词检索，与 L3 合并注入
    │
    ├─ persona.all_blocks()
    │       → [ProfileBlock, SkillsBlock?,
    │           ReflectionBlock?, PreferenceBlock?]
    │
    ├─ build_messages(...)  →  LLM.stream()  →  parse()
    │       └─ [finish] → FinishEvent → 客户端立即收到答案
    │
    └─ post_process()（后台线程）
            ├─ commit()
            │     ├─ L3 write
            │     ├─ L2 milestone score & write
            │     │     └─ 溢出时按 importance 淘汰 → 迁移写入 L3
            │     └─ evicted milestones → L3.add()
            ├─ trace_store.write()
            ├─ persona.evolve()
            │     └─ 动态层：preference 更新 → PreferenceStore.save()（持久化）
            └─ build_static() → _static_cache（预热下轮）
```

---

## 记忆三层设计

| 层 | 名称 | 检索方式 | 注入方式 | 持久化 |
|---|---|---|---|---|
| L1 | 短期 | 滑动窗口（内存）| ✅ 每步自动 | ❌ |
| — | 中期蒸馏 | LLM 摘要（内存）| ✅ 每问题自动 | ❌ |
| L2 | 里程碑 | 关键词精确子串 + 可选 jieba | ❌ 按需检索（含 detail）| ✅ `milestones.json` |
| L3 | 长期 | FAISS 向量相似度 | ❌ 动态 | ✅ FAISS + JSON |

**L2 溢出策略**：条目数超过 `max_milestones`（默认 50）时，按 importance 从低到高淘汰，被淘汰条目自动迁移写入 L3，确保不丢失任何重要信息。

**L2 中文分词**：`MilestoneRetriever` 优先使用 `jieba`（若已安装），未安装时自动降级为关键词精确子串匹配 + 字符 bigram，LLM 提取的词组级关键词在两种模式下均可有效匹配。

---

## 人格双层设计

| 层 | 名称 | 内容 | 持久化 | 影响 |
|---|---|---|---|---|
| 稳定层 | 长期人格 | 画像 / 技能库 / 自省 | ✅ | Prompt 注入 |
| 动态层 | 近期偏好 | 情绪 / 话题兴趣 / 风格偏移（k 天滑动窗口）| ✅ `preference.json` | L3 检索偏置 + Prompt 注入 |

**近期偏好**：每轮由 LLM 生成带时间戳的 `PreferenceEntry` 快照，滑动窗口（默认 7 天）自动剪枝过期条目，聚合后注入 Prompt；跨会话持久化，重启后自动恢复。

---

## 快速开始

```python
from config.llm_core.config import LLMConfig
from config.react.tao_config import TaoConfig
from llm_core.llm import LLM
from react.action.executor import ActionExecutor
from react.tao import TaoLoop

llm = LLM(LLMConfig(model="gpt-4o", api_key="sk-..."))
executor = ActionExecutor()
cfg = TaoConfig()

loop = TaoLoop(
    llm=llm,
    executor=executor,
    tool_descriptions={"weather": "查询当地天气"},
    cfg=cfg,
)
print(loop.run("今天天气怎么样？"))
```

启动 WebUI：

```bash
# 在仓库根目录下运行
python src/run.py
# 或指定端口
python src/run.py --port 8080
```

---

## 子模块文档

| 文档 | 说明 |
|---|---|
| [react/README.md](./react/README.md) | 完整链路：两层循环、三层记忆、Prompt、Persona、Trace |
| [react/persona/README.md](./react/persona/README.md) | 人格演化引擎详解（稳定层 + 动态层）|
| [cache/README.md](./cache/README.md) | 本地文件缓存管理（目录结构、路径配置、写入时序）|
| [react/action/README.md](./react/action/README.md) | 工具注册与 Pydantic 校验 |
| [react/memory/README.md](./react/memory/README.md) | 三层记忆系统（含 L2 里程碑）|
| [react/prompt/README.md](./react/prompt/README.md) | 块驱动 Prompt 组装 |
| [llm_core/README.md](./llm_core/README.md) | LLM 抽象层 |
| [webui/README.md](./webui/README.md) | Web 界面与 API |
| [test/README.md](./test/README.md) | 测试覆盖说明 |
