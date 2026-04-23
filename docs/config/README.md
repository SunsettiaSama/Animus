# config

所有模块的配置 dataclass 集中存放目录，与业务代码解耦。

## 目录结构

```
src/config/
├── __init__.py                     # AppPaths — 统一路径入口
├── app_config.py
├── llm_core/
│   └── config.py                   # LLMConfig
├── embedding/
│   └── config.py                   # EmbeddingConfig
├── hf_download/
│   └── config.py                   # HFDownloadConfig
├── network/
│   └── web_search_config.py        # WebSearchConfig
└── react/
    ├── tao_config.py               # TaoConfig（顶层）
    ├── persona_config.py           # PersonaConfig
    ├── prompt_config.py            # PromptConfig
    ├── run_config.py               # RunConfig（WebUI / SearXNG 默认端口）
    ├── trace_config.py             # TraceConfig
    └── memory/
        ├── memory_config.py        # MemoryConfig + LongTermMemoryConfig
        ├── short_term_config.py    # ShortTermMemoryConfig
        ├── medium_term_config.py   # MediumTermMemoryConfig
        ├── milestone_config.py     # MilestoneConfig
        ├── retrieve_config.py      # RetrieveConfig
        └── embedding_config.py     # EmbeddingConfig（记忆专用）
```

对应的 YAML 默认值文件位于 `config/react/`：

```
config/react/
├── memory.yaml          # 四层记忆的所有参数（统一入口）
├── run.yaml             # WebUI host/port、SearXNG 容器参数
└── memory/
    └── long_term.yaml   # L3 长期记忆详细参数（含 retrieve 子段）
```

---

## 各配置说明

### `ShortTermMemoryConfig`

```python
@dataclass
class ShortTermMemoryConfig:
    enabled: bool = True
    max_turns: int = 10             # 滑动窗口保留的最大步骤数
    max_tokens: int = 2048          # Token 上限（与 max_turns 取最严格约束）
    # 蒸馏：步骤溢出时自动压缩，保留推理精华
    distill_enabled: bool = True
    distill_trigger_steps: int = 4  # 积累 N 个驱逐步骤后触发 LLM 蒸馏
    max_distillate_tokens: int = 400
```

对应 `memory.yaml` 中的 `short_term` 段。

### `MediumTermMemoryConfig`

```python
@dataclass
class MediumTermMemoryConfig:
    enabled: bool = True
    window_days: int = 7            # 加载最近 N 天的条目
    max_entries: int = 30           # 最多加载 N 条（取最新）
    max_chars: int = 3000           # 注入 prompt 的字符上限
    memory_dir: str = ""            # 由 TaoConfig._propagate_dirs 自动填充
    # 滚动整合
    consolidate_enabled: bool = True
    consolidate_batch: int = 10     # 每次整合的旧条目数
    consolidate_interval_days: int = 1  # 自动整合最短间隔（天）；0 = 每次提交都检查
    max_consolidate_tokens: int = 500
```

对应 `memory.yaml` 中的 `medium_term` 段。

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
    consolidation_k: int = 0        # 0 = 关闭窗口整合
    max_entry_chars: int = 2000
    max_recall_chars: int = 3000
    retrieve: RetrieveConfig = ...
```

详细参数见 `config/react/memory/long_term.yaml`。

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

从 YAML 加载：

```python
cfg = MemoryConfig.from_yaml("config/react/memory.yaml")
```

### `EmbeddingConfig`

```python
@dataclass
class EmbeddingConfig:
    model_name_or_path: str = "BAAI/bge-small-zh-v1.5"
    use_fp16: bool = True
    device: str = "auto"
    query_prefix: str = "query: "
    passage_prefix: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
```
