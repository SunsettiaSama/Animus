# test

仓库根目录下 **`src/test/`**：按领域拆分的自动化测试（unittest / pytest）。覆盖 React 记忆与工具、`runtime.scheduler`、`agent.flow`、子 Agent 委派、基准脚本等。

---

## 目录概览

| 路径 | 内容 |
|---|---|
| `src/test/memory/` | `MemoryProcessor`、短期/中期、`LongTermMemory` / Qdrant 相关 |
| `src/test/tools/` | 内置 Action（计算器、文件、HTTP、`scratchpad` 等）|
| `src/test/react/` | 解析器、执行器、风险评估、`SchedulerEngine` |
| `src/test/agent/flow/` | DAG、`FlowOrchestrator`、文档与节点组件 |
| `src/test/delegate/` | `delegate_task` / SubAgent |
| `src/test/infra/` | LLM、搜索等基础设施 |
| `src/test/benchmark/` | Tao / Plan 等基准与回归 |
| `src/test/voice/` | TTS 相关 |

---

## 运行方式

在**仓库根目录**执行（需已安装依赖）：

```bash
pytest src/test/memory/test_memory.py -q
pytest src/test/tools/test_tools_basic.py -q
pytest src/test/react/test_scheduler.py -q
```

或运行某一目录：

```bash
pytest src/test/agent/flow -q
```

---

## `src/test/memory/test_memory.py`

测试 **`MemoryProcessor`** 与 **`RecentHistoryMemory`** 的交互（含中期持久化与 Mock L3）。

**依赖隔离**：部分用例通过 `sys.modules` Stub 规避 `langchain_community`、嵌入模型等重型依赖；向量侧历史上曾有 FAISS 占位 stub，当前实现以 **Qdrant** 为主。

### ShortTermMemory

| 测试函数 | 验证内容 |
|---|---|
| `test_empty` | 初始状态无步骤 |
| `test_add_single` | 单步骤正确写入 |
| `test_eviction_by_turns` | 超过 max_turns 触发驱逐 |
| `test_eviction_by_tokens` | Token 超限触发驱逐 |
| `test_clear` | clear() 后状态归零 |

### MemoryProcessor（短期 only）

| 测试函数 | 验证内容 |
|---|---|
| `test_recall_empty` | 空状态 recall |
| `test_add_and_recall` | add + recall 一致 |
| `test_commit_no_long_term` | 无长期记忆时 commit |
| `test_trace_contents` | trace 含已添加步骤 |

### MemoryProcessor（短期 + 中期）

| 测试函数 | 验证内容 |
|---|---|
| `test_medium_term_absorbs_evicted` | 驱逐步骤流入中期 |
| `test_medium_term_distillate_after_trigger` | 蒸馏触发 |

### MemoryProcessor（含 LongTermMemory Mock）

| 测试函数 | 验证内容 |
|---|---|
| `test_recall_with_long_term` | L3 出现在 MemoryResult |
| `test_commit_calls_long_term` | commit 调用 long.add/save |
| `test_include_long_term_false` | 跳过向量检索 |
| `test_medium_distillate_property` | medium_distillate |

### 完整交互场景

| 测试函数 | 验证内容 |
|---|---|
| `test_full_interaction` | 短/中/长协同 |

---

## `src/test/tools/`

| 文件 | 侧重点 |
|---|---|
| `test_tools_basic.py` | `ActionExecutor`、计算器、时间、随机数、字符串、单位换算等 |
| `test_tools_data.py` | JSONPath / diff 等数据类工具 |
| `test_file_system.py` / `test_http.py` / `test_python_run.py` / `test_scratchpad.py` | 沙箱与网络工具 |

工具测试覆盖 Pydantic 参数校验的正例与反例（非法 JSON、缺参、`ValueError` 等）。
