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
│   └── sandbox_config.py           # SandboxConfig
├── network/
│   └── web_search_config.py        # WebSearchConfig
├── tts/                            # TTS / STT 配置
└── hf_download/
    └── config.py                   # HFDownloadConfig
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
    plan: PlanConfig | None = None
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
    load_from_disk: bool = True
    top_k: int = 5
    model_name_or_path: str = "BAAI/bge-small-zh-v1.5"
    use_fp16: bool = True
    device: str = "auto"
    max_entry_chars: int = 2000
    max_recall_chars: int = 3000
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
    def memory_dir(self) -> str: ...
    @property
    def milestones_dir(self) -> str: ...
    @property
    def persona_dir(self) -> str: ...
    @property
    def traces_dir(self) -> str: ...
    @property
    def scheduler_dir(self) -> str: ...
