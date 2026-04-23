# 本地文件缓存管理

本文档描述 ReAct Agent 在运行时产生的所有本地文件，包括目录结构、各文件用途、控制路径的配置字段及默认值。

---

## 总体原则

> **一个 Agent 实例，一个缓存根目录。**

所有运行时产出的缓存文件统一放在 `.react/` 目录下，按模块分子目录。
`config/` 目录是静态配置层，不属于运行时缓存，单独存放。

---

## 目录结构

```
<repo>/
├── config/
│   └── llm_core/
│       └── config.yaml          # LLM 配置（静态配置，非缓存）
│
└── .react/                      # Agent 唯一缓存根目录
    ├── history/                 # 对话历史
    │   └── {uuid}.json
    ├── memory/                  # L3 长期记忆
    │   ├── memories.json
    │   └── memory_index.faiss
    ├── milestones/              # L2 里程碑（重要事件，按需检索）
    │   └── milestones.json
    ├── persona/                 # 人格数据（稳定层）
    │   ├── profile.json
    │   ├── skills.json
    │   ├── chronicle.json
    │   ├── reflection.txt
    │   └── persona_config.json  # WebUI 人格开关（仅 WebUI 写入）
    └── traces/                  # 推理链存档
        └── {YYYYMMDD_HHMMSS}_{slug}.json
```

---

## 各模块详细说明

### 1. 对话历史 `.react/history/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/webui/app.py` |
| 触发时机 | 每轮对话结束，前端调用 `POST /api/history` |
| 文件命名 | `{uuid}.json`（UUID 由前端生成） |
| 文件内容 | 完整对话记录（id、title、mode、messages、timestamps） |
| 路径常量 | `_HISTORY_DIR = <repo>/.react/history` |
| 路径控制 | 硬编码于 `src/webui/app.py`，不经由 config dataclass |

相关 API：

| 端点 | 操作 |
|---|---|
| `GET /api/history` | 列出所有对话（扫描目录） |
| `GET /api/history/{id}` | 读取单条 |
| `POST /api/history` | 保存/更新 |
| `DELETE /api/history/{id}` | 删除单条 |
| `DELETE /api/history` | 清空全部 |

---

### 2. 长期记忆 `.react/memory/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/react/memory/long_term/store.py` |
| 触发时机 | `TaoLoop.post_process()` → `MemoryProcessor.commit()` → `LongTermMemory.save()` |
| 文件列表 | `memories.json`（向量条目元数据）、`memory_index.faiss`（FAISS 索引） |
| 路径配置字段 | `LongTermMemoryConfig.memory_dir` |
| 默认值 | `".react/memory"`（相对于进程 CWD） |
| 文件名常量 | `MEMORIES_FILE = "memories.json"`、`FAISS_INDEX_NAME = "memory_index"` |

**`memories.json` 结构（条目数组）：**

```json
[
  {
    "id": "uuid",
    "created_at": "2026-01-01T00:00:00+00:00",
    "text": "Q: ...\nA: ...",
    "meta": { "question": "..." }
  }
]
```

召回结果均携带时间戳前缀 `[YYYY-MM-DD HH:MM UTC]`，LLM 可直接感知事件发生时间。

---

### 3. L2 里程碑 `.react/milestones/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/react/memory/milestone/store.py` |
| 触发时机 | `TaoLoop.post_process()` → `MemoryProcessor.commit()` → `MilestoneMemory.try_add()` |
| 写入条件 | LLM 评估重要性 >= `MilestoneConfig.importance_threshold`（默认 0.6）|
| 文件列表 | `milestones.json` |
| 路径配置字段 | `MilestoneConfig.milestone_dir` |
| 默认值 | `".react/milestones"`（由 `CacheConfig.milestones_dir` 注入）|
| 开关 | `MilestoneConfig.enabled`（默认 `False`）|

**`milestones.json` 结构：**

```json
[
  {
    "id": "uuid",
    "summary": "用户决定换工作",
    "detail": "Q: 我打算辞职了\nA: ...",
    "created_at": "2026-01-01T00:00:00+00:00",
    "keywords": ["辞职", "工作", "决定"],
    "emotion": "neutral",
    "importance": 0.82
  }
]
```

**与 L3 的区别：**

| 维度 | L2 里程碑 | L3 长期记忆 |
|---|---|---|
| 检索方式 | 关键词重叠率 | FAISS 向量相似度 |
| 写入条件 | LLM 评估重要性 ≥ 阈值 | 每次对话后写入 |
| 注入方式 | 与 L3 合并进同一 MemoryBlock | 同上 |
| 数量 | 少（仅重要事件）| 多（所有对话）|

---

### 4. 人格数据 `.react/persona/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/react/persona/profile/store.py`、`src/react/persona/chronicle/store.py`、`src/webui/app.py` |
| 路径配置字段 | `PersonaConfig.persona_dir` |
| 默认值 | `".react/persona"`（相对于进程 CWD） |
| WebUI 路径常量 | `_PERSONA_DIR = <repo>/.react/persona`（绝对路径） |

#### 4.1 人物画像 `profile.json`

| 项目 | 说明 |
|---|---|
| 写入类 | `ProfileStore.save_profile()` |
| 触发时机 | `PersonaManager` 初始化时（首次加载自动创建默认值）；`TaoLoop.post_process()` → `persona.evolve()` |
| 内容 | 姓名、背景、性格特质、价值观、风格 |

#### 4.2 技能库 `skills.json`

| 项目 | 说明 |
|---|---|
| 写入类 | `ProfileStore.save_skills()` |
| 触发时机 | 技能演化时（`PersonaConfig.skills_enabled = True`） |
| 内容 | Agent 积累的技能条目列表 |
| 开关 | `PersonaConfig.skills_enabled`（默认 `True`） |

#### 4.3 事件演化日志 `chronicle.json`

| 项目 | 说明 |
|---|---|
| 写入类 | `ChronicleStore.save_chronicle()` |
| 触发时机 | 每轮 `post_process()` 触发 `persona.evolve()` → 追加新条目 |
| 内容 | 叙事风格的经历条目数组（时间戳 + 叙述文本） |
| 最大条数 | `PersonaConfig.max_chronicle_entries`（默认 100） |
| 开关 | `PersonaConfig.chronicle_enabled`（默认 `True`） |

#### 4.4 自省记录 `reflection.txt`

| 项目 | 说明 |
|---|---|
| 写入类 | `ProfileStore.save_reflection()` |
| 触发时机 | `PersonaConfig.reflection_enabled = True` 且达到 `reflect_interval` 时 |
| 内容 | 纯文本，第一人称自我感知段落 |
| 开关 | `PersonaConfig.reflection_enabled`（默认 `False`） |

#### 4.5 WebUI 人格开关 `persona_config.json`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/webui/app.py`，`POST /api/persona/save` |
| 内容 | WebUI 人格面板的开关与参数（`enabled`、`chronicle_enabled`、各长度上限等） |
| 说明 | 仅 WebUI 写入，CLI 模式不使用此文件 |

**仅当 `PersonaConfig.enabled = True` 时，演化类写入（chronicle、skills、reflection）才会触发。`profile.json` 在 `PersonaManager` 初始化时总会确保存在。**

> **短期偏好（`ShortTermPreference`）不持久化**，仅保存在 `PersonaManager` 内存中，会话结束即重置，无对应磁盘文件。

---

### 5. 推理链存档 `.react/traces/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/react/trace/store.py` |
| 触发时机 | `TaoLoop.post_process()` → `TraceStore.write()` |
| 文件命名 | `{YYYYMMDD_HHMMSS}_{query_slug}.json` |
| 路径配置字段 | `TraceConfig.trace_dir` |
| 默认值 | `".react/traces"`（相对于进程 CWD） |
| 开关 | `TraceConfig.enabled`（默认 `True`） |

**单个 trace 文件结构：**

```json
{
  "id": "uuid",
  "timestamp": "2026-01-01T00:00:00+00:00",
  "question": "...",
  "answer": "...",
  "steps": [
    {
      "index": 0,
      "thought": "...",
      "action": "web_search",
      "action_input": { "query": "..." },
      "observation": "..."
    }
  ]
}
```

**自定义路径：**

```python
from config.react.trace_config import TraceConfig

cfg = TraceConfig(trace_dir="/data/my_agent/traces")
```

---

### 6. LLM 配置 `config/llm_core/config.yaml`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/webui/app.py`，`POST /api/config/save` |
| 触发时机 | 用户在 WebUI 设置面板点击 "Save & Apply" |
| 内容 | model、api_key、base_url、max_tokens、temperature、system_prompt 等 |
| 路径常量 | `_LLM_CONFIG_YAML = <repo>/config/llm_core/config.yaml`（硬编码） |
| 说明 | 属于**静态配置层**，不是运行时缓存，独立于 `.react/` |

---

## 路径控制字段一览

| 文件/目录 | 配置字段 | 默认值 | 路径基准 |
|---|---|---|---|
| `.react/history/` | WebUI 硬编码 `_HISTORY_DIR` | `<repo>/.react/history` | 绝对（`_REPO_ROOT`） |
| `.react/memory/` | `LongTermMemoryConfig.memory_dir` | `".react/memory"` | 相对 CWD |
| `.react/milestones/` | `MilestoneConfig.milestone_dir` | `".react/milestones"` | 相对 CWD |
| `.react/persona/` | `PersonaConfig.persona_dir` | `".react/persona"` | 相对 CWD（CLI）/ 绝对（WebUI） |
| `.react/traces/` | `TraceConfig.trace_dir` | `".react/traces"` | 相对 CWD |
| `config/llm_core/config.yaml` | WebUI 硬编码 `_LLM_CONFIG_YAML` | `<repo>/config/llm_core/config.yaml` | 绝对（`_REPO_ROOT`） |

> **CWD 说明：** WebUI 通过 `uvicorn` 启动时，CWD 通常为仓库根目录，相对路径与绝对路径等效。CLI 模式（`python src/run.py`）同理，建议始终在仓库根目录下运行。

---

## 各模块写入触发时序

```
用户发送消息
│
├─ [Chat 模式]
│    └─ LLM 回复完成 → 前端 saveConv() → POST /api/history
│                                         └─ .react/history/{uuid}.json ✎
│
└─ [ReAct 模式]
     └─ TaoLoop.stream()
          ├─ 每步工具调用 → PromptManager（内存，不落盘）
          └─ 收到 FinishEvent → 前端 saveConv() → .react/history/{uuid}.json ✎
               └─ TaoLoop.post_process()（后台线程）
                    ├─ MemoryProcessor.commit()
                    │    ├─ LongTermMemory.save()         → .react/memory/ ✎
                    │    └─ MilestoneMemory.try_add()
                    │         ├─ LLM 评估重要性（0.0-1.0）
                    │         └─ 重要性 >= threshold
                    │              └─ MilestoneStore.save() → .react/milestones/ ✎
                    ├─ TraceStore.write()                  → .react/traces/ ✎
                    └─ PersonaManager.evolve()
                         ├─ ProfileStore.save_profile()    → .react/persona/profile.json ✎
                         ├─ ProfileStore.save_skills()     → .react/persona/skills.json ✎
                         ├─ ChronicleStore.save()          → .react/persona/chronicle.json ✎
                         ├─ ProfileStore.save_reflection() → .react/persona/reflection.txt ✎
                         └─ PreferenceUpdater.update()     （内存更新，不落盘）
```

---

## 清理与迁移

**清空对话历史（保留其他数据）：**

```bash
# 通过 API
curl -X DELETE http://localhost:8080/api/history

# 或直接删除文件
rm .react/history/*.json
```

**清空全部缓存：**

```bash
rm -rf .react/
```

**迁移旧版本数据**（旧版长期记忆存放于 `long_term_memory/`，旧版历史文件存放于 `.react/*.json`）：

```bash
# 长期记忆迁移
mkdir -p .react/memory
mv long_term_memory/* .react/memory/

# 历史文件迁移（将 .react/ 根目录下的 UUID 文件移入 history/）
mkdir -p .react/history
# 仅移动符合 UUID 格式的 JSON 文件
for f in .react/*.json; do mv "$f" .react/history/; done
```
