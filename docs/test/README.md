# test

功能测试，覆盖记忆模块与动作空间模块。

## 文件

| 文件 | 覆盖范围 |
|---|---|
| `test_memory.py` | 三级记忆系统（ShortTermMemory、MediumTermMemory、MemoryProcessor）|
| `test_tools.py` | 工具注册、Pydantic 参数校验、各工具执行逻辑 |

## 运行

```bash
cd G:\ReAct\src
python test/test_memory.py
python test/test_tools.py
```

---

## test_memory.py

测试三级记忆模块的交互逻辑，共 17 个测试用例。

**依赖隔离方案**：`langchain_community`、FAISS、HuggingFace Embeddings 等重型依赖通过 `sys.modules` Stub 注入，无需安装即可运行。`react` 包本身也被 Stub 以避免 `react/__init__.py` 触发完整依赖链。

### ShortTermMemory

| 测试函数 | 验证内容 |
|---|---|
| `test_empty` | 初始状态无步骤 |
| `test_add_single` | 单步骤正确写入 |
| `test_eviction_by_turns` | 超过 max_turns 触发驱逐，最旧步骤被移除 |
| `test_eviction_by_tokens` | Token 超限触发驱逐 |
| `test_clear` | clear() 后状态归零 |

### MemoryProcessor（短期 only）

| 测试函数 | 验证内容 |
|---|---|
| `test_recall_empty` | 空状态 recall 返回零值 |
| `test_add_and_recall` | add + recall 结果一致 |
| `test_commit_no_long_term` | 无长期记忆时 commit 正常完成 |
| `test_trace_contents` | trace 包含所有已添加步骤 |

### MemoryProcessor（短期 + 中期）

| 测试函数 | 验证内容 |
|---|---|
| `test_medium_term_absorbs_evicted` | 短期驱逐步骤流入中期 |
| `test_medium_term_distillate_after_trigger` | 达到 distill_trigger_steps 后 LLM 生成蒸馏 |

### MemoryProcessor（含 LongTermMemory Mock）

| 测试函数 | 验证内容 |
|---|---|
| `test_recall_with_long_term` | long_term.smart_recall 结果出现在 MemoryResult |
| `test_commit_calls_long_term` | commit 时调用 long.add 和 long.save |
| `test_include_long_term_false` | include_long_term=False 跳过向量检索 |
| `test_medium_distillate_property` | medium_distillate 属性返回正确蒸馏文本 |

### 完整交互场景

| 测试函数 | 验证内容 |
|---|---|
| `test_full_interaction` | 多轮问答下短/中/长期记忆协同工作的完整链路 |

---

## test_tools.py

测试工具注册与执行，覆盖 Pydantic 参数校验（Zod 风格）的正/负场景。

### ActionExecutor 基础

| 测试函数 | 验证内容 |
|---|---|
| `test_register_and_available_actions` | 注册后工具名出现在列表 |
| `test_unknown_action_raises` | 未注册工具名 → `ValueError` |
| `test_malformed_json_raises` | 非法 JSON → `json.JSONDecodeError` |

### 各工具正常执行

| 测试函数 | 验证内容 |
|---|---|
| `test_calculator_*` | 四则运算、幂运算、括号优先级 |
| `test_datetime_*` | 当前时间、指定时区 |
| `test_random_*` | 整数随机、浮点随机、范围校验 |
| `test_string_*` | upper/lower/reverse/length/count_words |
| `test_unit_converter_*` | 温度/长度/重量单位转换 |
| `test_word_count_*` | 字数统计 |
| `test_weather_*` | 天气查询（占位）|

### Pydantic 参数校验（负场景）

| 测试函数 | 验证内容 |
|---|---|
| `test_calculator_empty_expression` | 空表达式 → `ValueError` |
| `test_random_invalid_range` | low >= high → `ValueError` |
| `test_string_invalid_operation` | 非枚举 operation → `ValueError` |
| `test_unit_converter_invalid_category` | 未知 category → `ValueError` |
| `test_word_count_missing_text` | 缺少必填参数 → `ValueError` |
