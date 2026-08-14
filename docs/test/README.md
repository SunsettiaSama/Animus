# test

`src/test/` 是与生产模块并列的验证区，主体为 pytest 测试，同时容纳 benchmark 场景、workbench 评测程序、smoke/demo 和少量诊断脚本。目录用于验证当前实现，不是稳定的公共 API 或示例代码集合；运行范围和外部依赖应按具体子目录选择。

## 目录概览

| 路径 | 当前覆盖 |
|---|---|
| `src/test/agent/flow/` | Flow 图、节点、channel/link、预算、快照、patch、规划/评审与 orchestrator |
| `src/test/react/` | React parser、executor、risk 与 scheduler 行为 |
| `src/test/tools/` | 基础/数据/编码 Action，以及文件、HTTP、Python、scratchpad 等执行边界 |
| `src/test/delegate/` | 子 Agent 委派与事件传递 |
| `src/test/memory/` | Soul Memory 的图节点、网络、检索、扩散、聚类、叙事/社交上下文与向量基础设施相关回归 |
| `src/test/soul/` | Soul 生命周期、Persona、Presence、Speak pipeline/compose/session、accounts、workers 与 Soul 内部 Life/Memory 适配 |
| `src/test/life/` | Life session、体验管线、landmark、chronicle/story outcome、会话压缩及记忆擢升 |
| `src/test/worker/` | work intent/transition、flow dataflow 与 worker state/reflection |
| `src/test/interaction/` | posture 状态机、连续性栈/规则、对话边与 Agent 输出 |
| `src/test/storyview/` | scene grounding/network、Story/Storyview engine 与 director |
| `src/test/webui/` | Speak delivery hub、typing simulation 及相关性能探针 |
| `src/test/infra/` | LLM、搜索与吞吐诊断；部分用例需要真实基础设施或单独配置 |
| `src/test/voice/` | TTS 集成 |
| `src/test/benchmark/` | Tao、Plan、parser、DAG、工具和委派场景的 benchmark runner、fixtures、metrics 与回归测试 |
| `src/test/workbench/` | IFEval 与 Speak Turing 的数据集、runner、evaluator/judge、report 和入口，以及 workbench 自测 |

`benchmark/`、`tools/` 与 `react/` 应按上述职责理解；其文件和测试函数会随实现调整，本页不维护逐函数清单。

## 两套记忆边界

React 的 context 只处理当前运行/会话上下文：

- `agent.react.context.MemoryProcessor` 以步骤 trace 表示 short context。
- `RecentHistoryMemory` 保存并渲染近期对话摘要，构成 medium context。
- `MemoryResult` 仅包含 `short_term` 与 `medium_term`；`MemoryProcessor` 不接收长期存储，也不控制长期检索。

Soul 的长期记忆是另一条链路。当前生产源码由 `agent.soul.memory.MemoryService` 管理事件/社交记忆网络，通过 `MemoryInfraService` 使用 embedding 与 `QdrantVectorStore`；长期读取由 Soul Memory 查询或 React 的 memory action 主动触发，写入则经 Life/Memory 管线完成。旧测试中出现的 `LongTermStore` 名称不等同于 React context，也不是当前生产目录中的权威 API。

## 运行方式

在仓库根目录按需运行：

```bash
pytest src/test/react -q
pytest src/test/tools -q
pytest src/test/agent/flow -q
pytest src/test/soul -q
```

全量运行可使用 `pytest src/test -q`，但 infra、voice、smoke、benchmark/workbench 等范围可能要求额外依赖、服务、模型或数据集。

## 已知漂移

`src/test/memory/test_memory.py` 当前同时存在语法损坏和已移除 API 的引用，不能作为可运行测试或记忆接口的权威示例。应以当前 `agent.react.context`、`agent.soul.memory` 源码及其余对应测试为准；本次文档同步不修改该测试。
