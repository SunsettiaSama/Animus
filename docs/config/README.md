# config

所有模块的配置 dataclass 集中存放目录，与业务代码解耦。

## 目录结构

```
src/config/
├── __init__.py                     # AppPaths — 统一路径入口
├── app_config.py
├── storage.py                      # StorageConfig（运行时文件根目录）
├── llm_core/
│   ├── config.py                   # LLMConfig
│   └── vllm_config.py              # VLLMConfig
├── agent/                          # Agent 各子模块配置
│   ├── tao_config.py               # TaoConfig（顶层）
│   ├── run_config.py               # RunConfig（WebUI host/port、SearXNG 设置）
│   ├── persona_config.py           # PersonaConfig
│   ├── prompt_config.py            # PromptConfig
│   ├── risk_config.py              # RiskConfig
│   ├── trace_config.py             # TraceConfig
│   └── memory/
│       ├── memory_config.py        # MemoryConfig + LongTermMemoryConfig
│       ├── short_term_config.py    # ShortTermMemoryConfig
│       ├── medium_term_config.py   # MediumTermMemoryConfig
│       ├── milestone_config.py     # MilestoneConfig
│       └── retrieve_config.py      # RetrieveConfig
├── embedding/
│   └── __init__.py                 # EmbeddingConfig
├── knowledge/                      # 知识库配置
├── infra/
│   ├── sandbox_config.py           # SandboxConfig
│   ├── bot_config.py               # BotConfig（OneBot / QQ Official）
│   ├── bark_config.py              # BarkConfig（Bark 推送）
│   ├── ntfy_config.py              # NtfyConfig（ntfy 推送）
│   └── db_config.py                # DBConfig（Redis + MySQL，Soul 记忆等）
├── network/
│   └── web_search_config.py        # WebSearchConfig
├── tts/                            # TTS / STT 配置
├── hf_download/
│   └── config.py                   # HFDownloadConfig
└── soul/
    └── memory/
        └── service_config.py       # MemoryServiceConfig（Soul MemoryService）
```

---

## 各配置说明

### `LLMConfig`（`config/llm_core/config.py`）

```python
@dataclass
class LLMConfig:
    model: str = ""
    api_key: str = ""
    base_url: str | None = None
    max_tokens: int = 512
    temperature: float = 1.0
    do_sample: bool = False
    top_p: float = 1.0
    top_k: int = 0
    repetition_penalty: float = 1.0
    device: str = "auto"
    system_prompt: str = ""
    backend: str = "openai"          # "openai" | "vllm" | "transformers"
    trained_model_path: str = ""
```

从 YAML 加载：`LLMConfig.from_yaml("config/llm_core/config.yaml")`

---

### `TaoConfig`（`config/agent/tao_config.py`）

```python
@dataclass
class TaoConfig:
    max_steps: int = 10
    storage: StorageConfig = ...
    prompt: PromptConfig = ...
    memory: MemoryConfig = ...
    persona: PersonaConfig = ...
    trace: TraceConfig = ...
    knowledge: KnowledgeConfig | None = None
    repair_llm: LLMConfig | None = None
    scheduler: SchedulerConfig | None = None
    agent: SubAgentConfig | None = None   # 子 Agent 委派（注入 DelegateTaskSkill）
    flow: FlowConfig | None = None
    db: DBConfig | None = None            # Soul：Redis/MySQL（可选）
```

`scheduler` 的类型为 **`runtime.scheduler.config.SchedulerConfig`**（定义不在 `src/config/`）；详见 [runtime/README.md](../../runtime/README.md)。

---

### `SchedulerConfig` / `HeartbeatConfig`（运行时）

- **`SchedulerConfig`**：`runtime/scheduler/config.py`，字段含 `scheduler_dir`、`profiles`、`heartbeat` 等。
- **`HeartbeatConfig`**：`runtime/scheduler/heartbeat_config.py`，默认清单路径 `.react/scheduler/HEARTBEAT.md`。

默认装配示例：`agent.soul.heartbeat.profiles.make_default_scheduler_config()`。

---

### `DBConfig`（`config/infra/db_config.py`）

聚合 Redis 与 MySQL，约定默认路径 `config/infra/db.yaml`：

```python
@dataclass
class DBConfig:
    redis: RedisConfig = ...
    mysql: MySQLConfig = ...
```

- `DBConfig.load_default()`：文件不存在时使用内置默认值。
- `RedisConfig.build_client()` / `MySQLConfig.build_client()`：构造 `infra.db` 客户端。

---

### `MemoryServiceConfig`（`config/soul/memory/service_config.py`）

Soul `MemoryService` 全局参数；默认读取 `config/soul/memory/service.yaml`：

```python
@dataclass
class MemoryServiceConfig:
    stm_half_life_days: float = 3.0
    stm_min_ttl_hours: float = 1.0
    ltm_half_life_days: float = 30.0
    ltm_forget_threshold: float = 0.05
    async_ingest: bool = True
    promote_threshold: float = 0.7
    recall_top_k: int = 5
    flush_activation_floor: float = 0.1
```

---

### `ShortTermMemoryConfig`

```python
@dataclass
class ShortTermMemoryConfig:
    enabled: bool = True
    max_turns: int = 10
    max_tokens: int = 2048
    distill_enabled: bool = True
    distill_trigger_steps: int = 4
    max_distillate_tokens: int = 400
```

### `MediumTermMemoryConfig`

```python
@dataclass
class MediumTermMemoryConfig:
    enabled: bool = True
    window_days: int = 7            # 加载最近 N 天的条目
    max_entries: int = 30
    max_chars: int = 3000
    memory_dir: str = ""            # 由 TaoConfig._propagate_dirs 自动填充
    consolidate_enabled: bool = True
    consolidate_batch: int = 10
    consolidate_interval_days: int = 1
    max_consolidate_tokens: int = 500
```

### `LongTermMemoryConfig`

```python
@dataclass
class LongTermMemoryConfig:
    enabled: bool = False
    memory_dir: str = ""
    qdrant_path: str = ".react/memory/qdrant"  # Qdrant 本地集合目录
    collection_name: str = "long_term_memory"
    load_from_disk: bool = True
    top_k: int = 5
    model_name_or_path: str = "BAAI/bge-small-zh-v1.5"
    query_prefix: str = "query: "
    passage_prefix: str = ""
    use_fp16: bool = True
    device: str = "auto"
    consolidation_k: int = 0
    max_entry_chars: int = 2000
    max_recall_chars: int = 3000
    distill_enabled: bool = False
    max_distill_tokens: int = 400
    retrieve: RetrieveConfig = ...
```

### `MilestoneConfig`

```python
@dataclass
class MilestoneConfig:
    enabled: bool = False
    max_milestones: int = 50
    importance_threshold: float = 0.6
    max_keywords: int = 5
    max_summary_chars: int = 200
    max_detail_chars: int = 1000
    top_k_retrieve: int = 2
    inject_detail: bool = True
    prompt_header: str = "## 重要里程碑"
```

### `MemoryConfig`（聚合）

```python
@dataclass
class MemoryConfig:
    short_term: ShortTermMemoryConfig
    medium_term: MediumTermMemoryConfig
    long_term: LongTermMemoryConfig
    milestone: MilestoneConfig
```

### `StorageConfig`（`config/storage.py`）

控制运行时文件根目录，通过 `TaoConfig._propagate_dirs()` 自动传播到各子模块。

```python
@dataclass
class StorageConfig:
    root: str = ".react"

    @property
    def history_dir(self) -> str: ...      # .react/history
    @property
    def memory_dir(self) -> str: ...       # .react/memory
    @property
    def milestones_dir(self) -> str: ...   # .react/milestones
    @property
    def persona_dir(self) -> str: ...      # .react/persona
    @property
    def traces_dir(self) -> str: ...       # .react/traces
    @property
    def scheduler_dir(self) -> str: ...    # .react/scheduler
    @property
    def workspace_dir(self) -> str: ...    # .react/workspace
    @property
    def timeline_dir(self) -> str: ...     # .react/timeline
    @property
    def life_dir(self) -> str: ...         # .react/life
    @property
    def benchmark_dir(self) -> str: ...    # .react/benchmark
    @property
    def obs_dir(self) -> str: ...          # .react/logs
    @property
    def train_dir(self) -> str: ...        # .react/train
    @property
    def checkpoints_dir(self) -> str: ...  # .react/train/checkpoints
    @property
    def adapters_dir(self) -> str: ...     # .react/train/adapters
    @property
    def merged_dir(self) -> str: ...       # .react/train/merged
```
