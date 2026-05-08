# WebUI

基于 FastAPI 的 Web 界面，以工作站仪表板为主页，统一展示所有子系统状态与配置入口；支持 Chat / ReAct 双模式对话，集成知识库、语音、调度器与历史管理。

## 文件结构

| 路径 | 说明 |
|---|---|
| `src/webui/app.py` | FastAPI 应用入口，挂载静态资源，注册所有 router，处理 startup / shutdown |
| `src/webui/state.py` | 后端单例 `AppState`，持有 LLM、ReAct、基础服务、工具等所有运行时对象 |
| `src/webui/index.html` | 单页前端，纯 HTML + Vanilla JS ES 模块，无框架依赖 |
| `src/webui/run.py` | uvicorn 启动入口（默认端口 8080，正式端口由 `config/react/run.yaml` 的 `webui.port` 决定，默认 **8300**）|
| `src/webui/schemas/llm.py` | LLM 相关 Pydantic 模型 |
| `src/webui/schemas/react.py` | ReAct WebSocket 消息 Pydantic 模型 |
| `src/webui/routers/llm.py` | LLM 配置、初始化、状态、Chat 流式接口 |
| `src/webui/routers/react.py` | ReAct 初始化、推理（SSE + WebSocket）、工具查询、时间线 |
| `src/webui/routers/history.py` | 对话历史 CRUD（JSON 文件持久化） |
| `src/webui/routers/memory.py` | 记忆配置读写与蒸馏触发 |
| `src/webui/routers/persona.py` | 人格配置读写 |
| `src/webui/routers/scheduler.py` | 调度器任务管理 |
| `src/webui/routers/knowledge.py` | 知识库文档管理与检索 |
| `src/webui/routers/voice.py` | TTS / STT 配置、合成、转录、模型下载 |
| `src/webui/routers/infra/vllm.py` | vLLM 服务器配置与启停 |
| `src/webui/routers/infra/sandbox.py` | 沙盒配置读写 |
| `src/webui/routers/infra/services.py` | 统一服务状态与启停 |
| `src/webui/static/css/main.css` | 全局样式 |
| `src/webui/static/js/main.js` | 应用入口：引导、生命周期、事件绑定 |
| `src/webui/static/js/state.js` | 前端状态机（`S`、`setState`、`set`） |
| `src/webui/static/js/api.js` | HTTP / WebSocket 工具与所有路径常量（`PATHS`） |
| `src/webui/static/js/history.js` | 对话历史 CRUD + 侧边栏渲染 |
| `src/webui/static/js/settings.js` | 设置弹窗 Tab 读写，委托各域模块 |
| `src/webui/static/js/streaming.js` | `ChatSession` / `ReactSession` WebSocket 会话管理 |
| `src/webui/static/js/render.js` | 消息区 DOM 操作 |
| `src/webui/static/js/modules/llm.js` | LLM 配置 / 初始化 / 工作站卡片 |
| `src/webui/static/js/modules/react.js` | ReAct 初始化 / 状态 / 工具 / 工作站卡片 |
| `src/webui/static/js/modules/memory.js` | 记忆配置 / 蒸馏 / 工作站卡片 |
| `src/webui/static/js/modules/persona.js` | 人格配置 / 工作站卡片 |
| `src/webui/static/js/modules/voice.js` | TTS / STT 配置 / 工作站卡片 |
| `src/webui/static/js/modules/scheduler.js` | 调度器任务 / 工作站卡片 |
| `src/webui/static/js/modules/infra.js` | vLLM / 沙盒 / 服务状态 |
| `src/webui/static/js/modules/knowledge.js` | 知识库面板 |
| `src/webui/routers/plan.py` | Plan 模式编排控制（运行 / 状态 / SSE 流 / 快照 / 回滚 / 日志 / 暂停 / 跳步）|
| `src/webui/static/js/modules/plan.js` | Plan 模式前端（BFS DAG 布局、SVG 渲染、SSE 实时更新、影子编辑器、快照列表、日志尾流）|
| `src/webui/routers/benchmark.py` | Benchmark Suite 后端（场景列表 / 运行 SSE / 报告读写 / 历史 / 清除）|
| `src/webui/static/js/modules/benchmark.js` | Benchmark Suite 前端（场景选择、SSE 进度、结果表格、漂移对比）|

## 启动

```bash
# 项目根目录（推荐）
python src/run.py

# 或直接
python src/webui/run.py
```

访问 `http://localhost:8300`（端口由 `config/react/run.yaml` 的 `webui.port` 控制，默认 8300）。

---

## API

### LLM 管理

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/config` | GET | 读取当前 LLM 配置（含 WebUI 偏好设置：`tools_enabled`、`show_full_prompt`、`prompt_lang`、`max_steps`）|
| `/api/config/save` | POST | 保存 LLM 配置到 YAML，WebUI 偏好保存到 `config/webui/settings.json` |
| `/api/llm/config` | GET | 同 `/api/config`（别名）|
| `/api/llm/config/save` | POST | — |
| `/api/init` 或 `/api/llm/init` | POST | 初始化 / 切换 Chat 模式 LLM |
| `PATCH /api/llm` | PATCH | 流式保护下热替换 LLM（streaming 时返回 409）|
| `/api/status` | GET | 查询 LLM 状态，返回 `initialized`、`model`、`backend`、`react_ready`、`turn_count`、`is_streaming` |

`GET /api/config` 返回示例：

```json
{
  "model": "gpt-4o",
  "api_key": "sk-…",
  "base_url": "",
  "max_tokens": 512,
  "temperature": 1.0,
  "system_prompt": "",
  "tools_enabled": false,
  "show_full_prompt": false,
  "prompt_lang": "cn",
  "max_steps": 10
}
```

### 普通对话

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/chat` | POST | SSE 流式对话（纯文本，带多轮 history，兼容用）|
| `/ws/chat` | WebSocket | WebSocket 流式对话（主路径，含 `gen_id`、abort 支持）|

### ReAct 推理

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/react/init` 或 `/api/react/reinit` | POST | 初始化 ReAct 会话（`lang`、`max_steps`、`primary_tools`、`enable_kb`）；streaming 时返回 409 |
| `/api/react/run` | POST | SSE 流式 ReAct 推理（兼容用）|
| `/ws/react/run` | WebSocket | WebSocket 流式 ReAct 推理（主路径）|
| `/api/react/reset` | POST | 清空当前会话历史 |
| `/api/react/restore` | POST | 从消息列表恢复会话历史（`{ messages: [...] }`）|
| `/api/react/abort` | POST | REST 备用中止（WebSocket 断开时使用）|
| `/api/react/status` | GET | 查询 ReAct 初始化状态（`initializing` / `ready` / `error`）|
| `/api/react/memory/clear` | POST | 清除所有记忆层 |
| `/api/react/persona/clear` | POST | 清除人格漂移数据 |
| `/api/react/tools` | GET | 查询已注册工具列表（按分类）|
| `/api/react/tools/search` | GET | 语义搜索工具（`?query=...&top_k=5`）|
| `/api/timeline` | GET | 获取事件时间线（`?date=YYYY-MM-DD`，默认今天）|

### 对话历史

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/history` | GET | 列出所有已保存对话（按更新时间倒序）|
| `/api/history/{id}` | GET | 读取单条对话完整内容 |
| `/api/history` | POST | 保存对话（创建） |
| `/api/history/{id}` | POST | 保存对话（更新，使用指定 id）|
| `/api/history/{id}` | DELETE | 删除单条对话 |
| `/api/history` | DELETE | 删除全部历史 |

历史记录存储于 `.react/history/` 目录，每条对话一个 JSON 文件：

```json
{
  "id": "uuid",
  "title": "对话标题",
  "mode": "chat | react",
  "messages": [{"role": "user", "content": "…"}, {"role": "assistant", "content": "…"}],
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

### 人格（Persona）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/persona` | GET | 读取人格配置（画像 + 配置项）|
| `/api/persona/save` | POST | 保存人格配置 |

### 记忆（Memory）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/memory` | GET | 读取记忆配置（L1 / L2 / L3 / Milestone）|
| `/api/memory/save` | POST | 保存记忆配置 |
| `/api/memory/consolidate` | POST | 手动触发中期记忆蒸馏 |

### 知识库（Knowledge Base）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/kb/documents` | GET | 列出所有文档 |
| `/api/kb/documents/{doc_id}` | DELETE | 删除指定文档 |
| `/api/kb/search` | GET | 检索知识库（`?q=...&mode=hybrid&top_k=5`）|
| `/api/kb/ingest` | POST | 写入新文档 |
| `/api/kb/fix-index` | POST | 修复未向量化的 chunks |

`/api/kb/search` 的 `mode` 参数：`keyword` / `semantic` / `hybrid`（默认）。

### 调度器（Scheduler）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/scheduler/tasks` | GET | 列出所有任务 |
| `/api/scheduler/tasks` | POST | 创建任务 |
| `/api/scheduler/tasks/{id}` | DELETE | 删除任务 |

### TTS / STT

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/tts/config` | GET | 读取 TTS 配置 |
| `/api/tts/config/save` | POST | 保存 TTS 配置 |
| `/api/tts/synthesize` | POST | 一次性合成音频 |
| `/api/tts/download` | GET | 下载模型（SSE 进度流）|
| `/ws/tts` | WebSocket | 流式 TTS（推送音频 chunk）|
| `/api/stt/config` | GET | 读取 STT 配置 |
| `/api/stt/config/save` | POST | 保存 STT 配置 |
| `/api/stt/transcribe` | POST | 上传音频，返回转录文本 |
| `/api/stt/download` | GET | 下载本地 STT 模型（SSE 进度流）|
| `/ws/stt` | WebSocket | 实时 STT |

### 基础设施（Infra）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/vllm/config` | GET | 读取 vLLM 配置 |
| `/api/vllm/config/save` | POST | 保存 vLLM 配置 |
| `/api/vllm/start` | POST | 启动 vLLM 服务器 |
| `/api/vllm/stop` | POST | 停止 vLLM 服务器 |
| `/api/vllm/status` | GET | 查询 vLLM 运行状态 |
| `/api/vllm/logs` | GET | 获取 vLLM 日志 |
| `/api/sandbox/config` | GET | 读取沙盒配置 |
| `/api/sandbox/config/save` | POST | 保存沙盒配置 |
| `/api/services/status` | GET | 查询所有服务状态（vLLM / SearXNG / Sandbox / TTS / STT）|
| `/api/services/{name}/status` | GET | 单个服务状态 |
| `/api/services/{name}/start` | POST | 启动指定服务 |
| `/api/services/{name}/stop` | POST | 停止指定服务 |
| `/api/services/{name}/logs` | GET | 获取服务日志 |

### Plan 模式（Plan Mode）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/plan/run` | POST | 启动新计划（`{ "question": "..." }`），返回 `plan_id` |
| `/api/plan/status` | GET | 返回当前 `PlanDocument` 状态（任务列表、依赖、执行状态）|
| `/api/plan/stream` | GET | SSE 事件流，推送 `PlanEvent`（task_start / task_running / task_complete / task_failed / replan / snapshot 等）|
| `/api/plan/snapshots` | GET | 列出所有可用快照 |
| `/api/plan/rollback` | POST | 回滚到指定快照（`{ "snapshot_id": "..." }`）|
| `/api/plan/logs` | GET | 获取结构化日志（`?task_id=&n=50`）|
| `/api/plan/pause` | POST | 暂停计划执行 |
| `/api/plan/resume` | POST | 恢复计划执行 |
| `/api/plan/skip/{task_id}` | POST | 跳过指定任务 |

### Benchmark Suite

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/benchmark/scenarios` | GET | 返回 YAML 场景名称列表 |
| `/api/benchmark/report` | GET | 读取 `.react/benchmark/report.json`，不存在返回空 |
| `/api/benchmark/history` | GET | 读取 `.react/benchmark/history.json`，不存在返回空 |
| `/api/benchmark/run` | POST | `{ scenarios: [...] }` → SSE 流，每场景结束推一条 JSON；全部完成后写入报告和历史 |
| `/api/benchmark/report` | DELETE | 删除 `report.json` 与 `history.json` |

---

## 初始化链

### LLM 初始化

```
Settings → Save（saveModelTab）
   │  POST /api/config/save  → 写 config/llm_core/config.yaml
   │  POST /api/init         → llm.py: init_llm()
   │     state.llm = LLM(cfg)
   │     state.llm_cfg = cfg
   └── 若 tools_enabled: reactMod.init(payload) → ReAct 初始化链
```

### ReAct 初始化链（完整）

```
前端触发
  settings.js:saveModelTab() 或 reactMod.init(payload)
      │
      ▼
POST /api/react/reinit  (react.py:201)
  ├─ 校验：state.llm 是否存在（否 → 400 "LLM not initialized."）
  ├─ 校验：is_streaming（是 → 409）
  ├─ state.react_init_event.clear()
  ├─ state.conv_loop = None
  └─ task_runner.submit("react_init", _do_react_init)  ← 后台线程
          │
          ▼
      _do_react_init(req, state)  (react.py:107)
          │
          ├─ 取消旧 scheduler（若存在）
          ├─ 等待旧 preload_future（最多 120s）
          ├─ old_tao.close()
          │
          ├─ executor = state.tool_manager.build_executor()
          ├─ TaoConfig(
          │      max_steps=req.max_steps,
          │      storage=state.cache,           # StorageConfig(.react/)
          │      prompt=PromptConfig(lang=req.lang),
          │      memory=MemoryConfig.from_yaml(...),
          │      persona=PersonaConfig(...),
          │      scheduler=SchedulerConfig(...),
          │      agent=SubAgentConfig(...),
          │      plan=PlanConfig(...)
          │  )
          │
          ├─ TaoLoop(llm, executor, tool_descriptions, cfg)
          │      │  内部构建顺序（src/agent/react/tao.py）：
          │      ├─ LLMHandle(llm)
          │      ├─ TraceStore / PersonaManager / TimelineStore
          │      ├─ make_memory / make_milestone / RecentHistoryMemory
          │      ├─ 注册工具：recall → scratchpad → sandbox → KB → scheduler → delegate → plan
          │      ├─ executor.set_event_sink(timeline.make_tool_sink())
          │      └─ PromptManager(effective_descriptions, cfg.prompt)  ← 必须在所有工具注册后
          │
          ├─ state.active_tao = tao
          ├─ state.conv_loop = ConvLoop(tao)
          ├─ state.react_init_event.set()
          ├─ task_runner.submit("preload", tao.preload)
          └─ asyncio.run_coroutine_threadsafe(scheduler_engine.start(), main_event_loop)

前端轮询
  reactMod.init() 内：pollUntilReady()
      └─ 每 500ms GET /api/react/status
             ├─ "ready"  → set('reactReady', true)
             ├─ "error"  → 抛出异常，toast 显示错误
             └─ 超时（120s）→ 抛出 "ReAct init timed out"

GET /api/react/status  (react.py:233)
  ├─ react_init_event.is_set() == False → "initializing"
  ├─ react_init_error 非空              → "error"
  └─ 其他                               → "ready"
```

> **⚠️ 已知语义陷阱**：`AppState.__post_init__` 在启动时即执行 `react_init_event.set()`（含义：初始空闲），导致未调用 `reinit` 时 `GET /api/react/status` 也返回 `ready`，前端 `reactReady` 会被设为 `true`。但此时 `conv_loop is None`，用户发消息时 WebSocket 仍会返回 `"ReAct not initialized."`。  
> **解法**：首次使用前务必在 Settings 保存配置并开启工具，或点击 "New ReAct Session" 触发 reinit。

---

## 对话交互链

### ReAct 模式（/ws/react/run）

```
用户点击 Send（main.js:handleSend）
    │
    ├─ 检查 S.reactReady（否 → toast "ReAct not initialized"，返回）
    ├─ setState('streaming', { mode: 'react' })
    └─ streaming.js: ReactSession.run(question)
            │
            ├─ wsFactory('/ws/react/run') → WebSocket 连接
            ├─ send({ question, gen_id })
            │
            │  后端 ws_react_run (react.py:352)
            │      ├─ 接收 question / gen_id
            │      ├─ conv_loop is None → send error, close
            │      ├─ state.set_streaming(True, gen_id)
            │      ├─ 线程: _produce()
            │      │      for event in conv_loop.stream(question):
            │      │           → ConvLoop.stream → TaoLoop.stream(question)
            │      │           → _event_to_dict(event) → queue.put(msg)
            │      └─ 线程: _receive_client()
            │             处理 abort / approval_response
            │
            │  TaoLoop.stream 每轮 yield：
            │      PromptPreviewEvent(step=0)
            │      StepStartEvent(index=i)
            │      ChunkEvent(index=i, chunk=...)   ← LLM 流式 token
            │      RetryEvent(index=i, reason=...)  ← 解析失败重试
            │      ApprovalRequestEvent(...)         ← 高风险工具审批
            │      StepEvent(thought, action, observation)
            │      FinishEvent(answer=...)
            │
            │  前端收到事件 (streaming.js:onmessage → main.js 回调)
            │      chunk    → ctrl.appendChunk(i, chunk)
            │                   仅提取 <T>…</T> 内容显示，屏蔽 <A>/<O> 原始 JSON
            │      step     → ctrl.addStep(step)
            │                   若 step.output 非空且 step.action !== 'finish'：
            │                     ctrl.close() → appendAssistantMsg() 显示 output
            │                     → 新建 appendReactMsg() 继续后续步骤（多气泡分割）
            │      sub_start  → ctrl.openSubAgent(action, instruction)
            │      sub_chunk  → ctrl.addSubChunk(index, chunk)
            │      sub_step   → ctrl.addSubStep(stepObj)
            │      sub_finish → ctrl.closeSubAgent(answer, false)
            │      sub_error  → ctrl.closeSubAgent(error, true)
            │      max_steps  → toast 提示，resolve Promise（步骤数据保留）
            │      finish   → ctrl.close() / el.remove() → appendAssistantMsg(answer)
            │                   → resolve Promise, setState('idle')
            │      error    → reject Promise, setState('idle')
            │
            └─ finish 后：
                   后端: task_runner.submit("post_process", conv_loop.post_process)
                       → TaoLoop.post_process()（后台线程）
                           processor.commit(q, a)
                           timeline.append("conversation", ...)
                           persona.evolve(q, a)
                           manager.add_turn(q, a)
                           _maybe_consolidate()
                           static_cache = manager.build_static()

### Chat 模式（/ws/chat）

> **注意**：`ChatSession` 已从 `streaming.js` 移除，`main.js` 的 `handleSend` 始终调用 `_runReact`，前端不再有独立的 Chat 分支。`/ws/chat` 后端路由保留但当前前端不主动使用。

### 中止

```
用户点击 ⊘（Abort）
    ├─ 方式 A：通过 WebSocket 发 { type:"abort", gen_id }
    │        → _receive_client() 匹配 gen_id → conv_loop._tao.abort()
    │          → TaoLoop._stop_event.set() → stream() 在下个 chunk 边界 return
    └─ 方式 B：POST /api/react/abort（WS 断开备用）
```

---

## 前端 TAO 渲染详解

`render.js` 提供 `appendReactMsg()` 工厂，返回一个控制器对象，统一管理从流式 token 到结构化步骤卡片的全部 DOM 操作。

### 流式阶段（`appendChunk`）

每个 `chunk` 事件到达时：

1. 将 chunk 追加到当前步骤的累积字符串 `s.streamed`。
2. 用正则从累积文本中提取 `<T>…</T>` 内容，**仅显示思维链文本**；`<A>` 中的工具调用 JSON 和 `<O>` 中的输出文本在结构化完成前不暴露给用户。
3. 首次 chunk 到达时自动展开步骤卡片（添加 `open` 类），同时隐藏 Activity spinner。

### 结构化阶段（`addStep`）

`step` 事件到达后，调用 `ctrl.addStep(stepObj)`，按以下顺序构建步骤卡片内容：

| 区块 | 来源字段 | 渲染方式 |
|---|---|---|
| Thought | `stepObj.thought` | Markdown（`marked.parse` + `hljs`）|
| Action（单工具） | `stepObj.action` + `stepObj.action_input` | Action 纯文本；Input 渲染为 JSON code block |
| Actions（并行） | `stepObj.calls`（length > 1）| 标题「Actions (N parallel)」，每项显示序号 + `action` + args JSON code block |
| Observation | `stepObj.observation` | Markdown |
| 原始输出 | `s.streamed`（流式累积文本）| 折叠的 `<pre>` 块，点击展开，显示完整 `<T><A><O>` XML |

步骤完成后：移除 streaming 标签，在标题追加思维链摘要（≤50 字符）和 ✓ 徽章，并将卡片折叠（移除 `open` 类）。

### 中间气泡分割（`step.output` 非 finish 步骤）

当一个非 finish 步骤携带非空 `output` 字段时，`main.js` 执行多气泡分割：

```
ctrl.close()                   // 关闭当前 ReAct 卡片（移除 activity 和 answerBubble）
appendAssistantMsg()           // 插入普通 assistant 气泡，显示 step.output
ctrl = appendReactMsg()        // 新建 ReAct 卡片，继续后续步骤
```

这允许 Agent 在中间步骤向用户输出可见内容，同时保持推理链继续执行。

### 子 Agent 块渲染

`sub_start` 触发 `ctrl.openSubAgent(action, instruction)`，在当前父步骤的 detail 区（或 stepsWrap）内创建 `.sub-agent-block`，包含：

- 可折叠标题（`Sub-agent: <action>`）
- instruction 预览（最多 120 字符）
- 子步骤行（`addSubStep`）：Thought / Action / Input / Observation，逐步追加
- 流式文本区（`addSubChunk`）：每次 sub_chunk 追加到 `.sub-stream`，下一个 sub_step 到达时自动清除

`sub_finish` / `sub_error` 触发 `ctrl.closeSubAgent(text, isError)`：在标题追加 ✓ done / ✗ error 徽章，并在 body 追加答案摘要（最多 300 字符）或错误横幅。

### 历史重建（`_rebuildFromHistory`）

切换历史对话时，`main.js._rebuildFromHistory(messages)` 对每条 assistant 消息：

- 若含 `steps` 数组（ReAct 记录）：依次调用 `ctrl.addStep(step)`，遇到 `step.output` 非 finish 步骤时同样执行多气泡分割，最后调用 `ctrl.close()` 并显示 `m.content` 最终答案气泡。
- 若无 `steps`（Chat 或旧格式）：调用 `appendAssistantMsg()` 直接渲染内容。

历史记录格式：

```json
{
  "role": "assistant",
  "content": "最终答案文本",
  "steps": [
    {
      "index": 0,
      "thought": "…",
      "action": "tool_name",
      "action_input": {},
      "observation": "…",
      "calls": null,
      "output": ""
    }
  ]
}
```

---

## 配置文件路径

| 用途 | 路径（相对仓库根） |
|---|---|
| LLM 配置 | `config/llm_core/config.yaml` |
| vLLM 配置 | `config/llm_core/vllm.yaml` |
| Memory 配置 | `config/agent/memory.yaml` |
| 长期记忆细分 | `config/agent/memory/long_term.yaml` |
| Embedding 模型 | `config/embedding/model.yaml` |
| Sandbox 配置 | `config/infra/sandbox.yaml` |
| WebUI 偏好设置 | `config/webui/settings.json` |
| 启动端口等 | `config/agent/run.yaml` |
| 人格运行时 | `.react/persona/persona_config.json` |
| 运行时数据根 | `.react/`（由 `StorageConfig.root` 决定）|

---

## WebSocket 事件流

### `/ws/chat` — 普通对话

客户端首条消息：`{ "question": "...", "gen_id": "uuid" }`

| 事件 | 方向 | 字段 | 说明 |
|---|---|---|---|
| `chunk` | S→C | `chunk: str` | LLM 流式输出片段 |
| `finish` | S→C | `aborted: bool` | 对话结束 |
| `error` | S→C | `message: str` | 错误信息 |
| `abort` | C→S | `type: "abort"`, `gen_id: str` | 客户端中止请求 |

### `/ws/react/run` — ReAct 推理

客户端首条消息：`{ "question": "...", "gen_id": "uuid" }`

| 事件类型 | 方向 | 字段 | 说明 |
|---|---|---|---|
| `prompt_preview` | S→C | `messages: list[dict]` | 完整 Prompt 组装结果（首步前推送一次）|
| `step_start` | S→C | `index: int` | 开始第 N 步推理 |
| `chunk` | S→C | `index: int`, `chunk: str` | LLM 流式输出片段 |
| `step` | S→C | `index`, `thought`, `action`, `action_input`, `observation`, `calls: list[{action,args}] \| null`, `output: str` | 单步推理完整记录；`calls` 在并行工具时非空，`output` 为 `<O>` 内容（无时为空字符串）|
| `retry` | S→C | `index: int`, `reason: str` | 当前步骤重试 |
| `approval_request` | S→C | `request_id`, `tool_name`, `args`, `risk_level`, `reason`, `deadline_secs` | 高风险工具等待用户审批 |
| `max_steps` | S→C | `max_steps: int` | 已达步数上限；前端 toast 提示并保留已完成步骤数据 |
| `finish` | S→C | `answer: str`, `aborted: bool` | 最终答案（WebSocket 随后关闭）|
| `error` | S→C | `message: str` | 推理过程中发生异常 |
| `sub_start` | S→C | `action: str`, `instruction: str` | 子 Agent 启动，携带委托动作名与指令文本 |
| `sub_chunk` | S→C | `index: int`, `chunk: str` | 子 Agent LLM 流式 token |
| `sub_step` | S→C | `index`, `thought`, `action`, `action_input`, `observation`, `is_error: bool` | 子 Agent 完整步骤记录 |
| `sub_finish` | S→C | `answer: str` | 子 Agent 正常完成，返回最终答案 |
| `sub_error` | S→C | `error: str` | 子 Agent 出错 |
| `abort` | C→S | `type: "abort"`, `gen_id: str` | 客户端中止 |
| `approval_response` | C→S | `type: "approval_response"`, `request_id: str`, `approved: bool` | 工具审批回应 |

### 后台提交机制

`finish` 事件发送后 WebSocket 立即关闭，以下操作在后台线程异步完成：

```
客户端收到 finish → WebSocket 关闭
                          ↓（后台线程）
                    post_process()
                      commit → FAISS 写入
                      persona.evolve()
                      add_turn() + consolidate()
                      build_static()
```

---

## 前端布局

### 工作站主页（`#s-landing`）

应用启动后默认显示工作站仪表板，包含五个顶层导航入口：

```
┌─────────────────────────────────────────────────────────────┐
│  ⚡ ReAct Workstation                    [↻ Refresh] [⚙]   │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure Services                                    │
│  [vLLM ●] [SearXNG ●] [Sandbox ●] [TTS ●] [STT ●]         │
├───────────┬───────────┬──────────┬───────────┬─────────────┤
│ LLM Core  │ ReAct     │ Memory   │ Persona   │ Voice       │
│           │ Agent     │          │           │             │
├───────────┴───────────┴──────────┴───────────┴─────────────┤
│  Scheduler & Crew   │  Benchmark                           │
│  (只读摘要)         │  (只读摘要：通过率 / 最后运行时间)   │
├─────────────────────────────────────────────────────────────┤
│  Quick Start                                                │
│  [💬 New Chat]  [⚡ New ReAct Session]  [🗂 Plan Mode]     │
│  [🧪 Benchmark Suite]  [🗓 Scheduler]                       │
│  Recent conversations（最多 6 条）                          │
└─────────────────────────────────────────────────────────────┘
```

**五个顶层屏幕（`_showScreen` 管理）：**

| 屏幕 ID | 入口 | 说明 |
|---|---|---|
| `s-landing` | 应用启动 / Home 按钮 | 工作站仪表板 |
| `s-workspace` | New Chat / New ReAct Session | Chat & ReAct 对话区 |
| `s-plan` | Plan Mode 按钮 | 多智能体编排可视化 |
| `s-benchmark` | Benchmark Suite 按钮 | CI 性能基准套件 |
| `s-scheduler` | Scheduler 按钮 | 定时任务管理 + 时间轴 |

#### Infrastructure Services 行

5 张服务卡片横向排列：状态指示灯（绿 = running / 灰 = stopped / 黄闪 = loading）、服务名与状态。

| 服务 | 说明 | 启停 |
|---|---|---|
| vLLM | 本地推理服务器 | Start / Stop |
| SearXNG | 自托管搜索引擎 | Start / Stop |
| Sandbox | 代码执行沙盒 | 仅显示状态 |
| TTS | 语音合成引擎 | 仅显示状态 |
| STT | 语音识别引擎 | 仅显示状态 |

#### Modules 卡片网格

7 张只读状态卡，展示各模块实时摘要；支持双击卡片直接跳转到对应 Settings Tab（无 `data-tab` 的卡片不支持双击）：

| 卡片 | 展示内容 | Settings Tab |
|---|---|---|
| LLM Core | model / backend / streaming 状态；ready 徽章 | model |
| ReAct Agent | status / profile / persona；active 徽章 | model |
| Memory | L1 / L2 / L3 / MS 开关徽章 | memory |
| Persona | 人格名称、演化开关；active/disabled 徽章 | persona |
| Voice | TTS provider + 状态；STT provider + 状态 | voice |
| Scheduler & Crew | 任务总数 / pending / running；只读摘要 | — |
| Benchmark | 通过率 / 场景数 / 最近运行场景；只读摘要 | — |

#### 工作站数据加载

进入主页时并行调用：

| API | 用途 |
|---|---|
| `GET /api/status` | LLM 状态（`initialized`、`model`、`backend`、`react_ready`、`is_streaming`）|
| `GET /api/react/status` | ReAct 就绪状态 |
| `GET /api/services/status` | 5 个基础服务运行状态 |
| `GET /api/config` | LLM Core 卡片摘要 |
| `GET /api/memory` | Memory 卡片层级开关 |
| `GET /api/persona` | Persona 卡片信息 |
| `GET /api/react/tools` | ReAct Agent 工具总数与分类 |
| `GET /api/scheduler/tasks` | 调度器任务（Scheduler 卡片摘要） |
| `GET /api/benchmark/report` | Benchmark 最新报告（Benchmark 卡片摘要） |
| `GET /api/history` | 最近对话列表 |

### 对话区（`#s-workspace`）

#### 侧边栏

- 对话历史列表，支持切换 / 删除
- 顶栏按钮：新建对话（＋）、清空历史（🗑）、知识库（📚）、设置（⚙）
- 点击历史条目加载本地消息记录并重绘 DOM；**注意**：当前不自动调用 `/api/react/restore` 恢复后端 ReAct 上下文，切换对话后如需继续 ReAct 推理请手动重新初始化

#### 消息区

- `Enter` 发送，`Shift+Enter` 换行
- Chat 模式：流式气泡
- ReAct 模式：每步显示 Thought / Action / Action Input / Observation 折叠卡片
- "Show Full Input" 开关：在用户消息下方显示完整 Prompt（系统提示 + 对话历史 + 当前消息）

#### 知识库面板（`#kb-panel`）

点击侧边栏 📚 按钮进入，与聊天区完全隔离：

- **搜索区**：搜索框 + 模式下拉（`hybrid` / `semantic` / `keyword`）+ 搜索结果列表
- **写入区**：内容 / 标题 / 领域 / 概念输入框 + 写入按钮
- **文档列表**：列出所有文档，每行可删除；[修复索引] 按钮触发 `/api/kb/fix-index`

### Settings Modal（设置面板）

Settings 按钮（⚙）打开模态框，包含 6 个 Tab：

| Tab ID | 说明 |
|---|---|
| `model` | LLM 模型配置（API Key / Base URL / 参数）+ WebUI 偏好（Show Full Input、Agent 开关、Prompt Language、Max Steps）|
| `memory` | L1 短期记忆 / L2 中期记忆 / L3 长期记忆 / Milestone 参数 |
| `persona` | 人格开关、画像编辑（姓名 / 背景 / 性格 / 价值观 / 风格）|
| `voice` | TTS 提供商 / 语音参数；STT 提供商 / 语言 / 模型 |
| `vllm` | vLLM 服务器参数（host / port / tensor_parallel_size 等）|
| `sandbox` | 代码沙盒参数（工作目录 / 超时 / 封锁模块列表等）|

所有 Tab 点击模态框底部 **Save** 按钮保存；`vllm` 和 `sandbox` Tab 内也有独立的 Save 按钮。工作站主页各模块卡片的 Configure 按钮携带 tab 参数直接跳转到对应 Tab。

### Plan 模式界面（`#s-plan`）

点击工作站主页 **[📋 Plan Mode]** 卡片进入，独立于会话区，专为多智能体编排可视化设计。

```
┌──────────────────────────────────────────────────────────────┐
│  ◀ Home   Plan Mode      [status badge]   [⏸ Pause] [📷 Snap]│
├───────────────────────────┬──────────────────────────────────┤
│                           │  ┌─ Input ─────────────────────┐ │
│   DAG 可视化区（SVG）      │  │ [textarea: 目标/问题]        │ │
│                           │  │ [▶ Run Plan]                 │ │
│   task_a ──→ task_b       │  └─────────────────────────────┘ │
│      ↓           ↓        │                                  │
│   task_c ──→ task_d       │  ┌─ Shadow Editor ─────────────┐ │
│                           │  │ (Markdown 影子编辑器)         │ │
│   节点颜色：               │  │ [Apply Edits]               │ │
│   ⬜ pending  🔵 running  │  └─────────────────────────────┘ │
│   ✅ done    ❌ failed    │                                  │
│   ⏭ skipped             │  ┌─ Snapshots ─────────────────┐ │
│                           │  │ [snap_id]  [Rollback]        │ │
│                           │  └─────────────────────────────┘ │
│                           │                                  │
│                           │  ┌─ Logs ──────────────────────┐ │
│                           │  │ [task_id filter] [Refresh]   │ │
│                           │  │ 结构化日志条目…               │ │
│                           │  └─────────────────────────────┘ │
└───────────────────────────┴──────────────────────────────────┘
```

#### DAG 可视化

- 使用 BFS 分层布局算法计算节点列（层）和行（同层内排序）坐标，自动适配任意拓扑。
- 节点样式根据 `TaskStatus` 动态着色；`running` 状态节点带脉冲动画。
- 通过 SSE（`/api/plan/stream`）实时接收 `PlanEvent`，增量更新节点 CSS 类，无需全量重渲染。
- 支持的事件类型：`task_running`、`task_complete`、`task_failed`、`task_skipped`、`replan`（触发全量 DAG 重绘）、`snapshot`、`plan_complete`、`plan_abort`。

#### 影子编辑器（Shadow Editor）

- 展示当前 `PlanDocument` 的 Markdown 表示，用户可直接编辑。
- 点击 **Apply Edits** 将 diff 发送回编排器（通过 `HumanEditChannel` patch 队列），编排器在下一个安全点应用修改（暂停任务调度、应用、恢复）。
- 支持修改任务描述、参数、`writes` 资源声明，以及跳过任务（`status: skipped`）。

#### 快照管理

- 列出所有 `.react/plan/snapshots/<plan_id>/` 下的快照。
- 点击 **Rollback** 恢复到快照时刻的 `PlanDocument`；回滚会重置 `running` 和 `failed` 状态的任务至 `pending`，并清除 `execution_ctx`。

#### 日志查看

- 从 `/api/plan/logs` 获取最近 N 条 JSONL 结构化日志（默认 50 条）。
- 支持按 `task_id` 过滤，展示事件类型、时间戳、消息与附加字段。

### Benchmark Suite 界面（`#s-benchmark`）

点击工作站主页 **[🧪 Benchmark Suite]** 进入，独立全屏。

```
┌──────────────────────────────────────────────────────────────┐
│  ◀ Home   Benchmark Suite  [status]  [▶ Run All] [Run Sel] [Clear] │
├───────────────────────────┬──────────────────────────────────┤
│  Scenarios                │  Results                         │
│  ☑ simple_qa              │  ┌──────┬──┬───────┬─────┬───┐  │
│  ☑ tool_use               │  │场景  │OK│Tokens │Wall │Qty│  │
│  ☑ plan_exec              │  ├──────┼──┼───────┼─────┼───┤  │
│                           │  │ ...  │✓ │  200  │12ms │—  │  │
│  Progress（运行时追加）    │  └──────┴──┴───────┴─────┴───┘  │
│  ✓ simple_qa              ├──────────────────────────────────┤
│  ✓ tool_use               │  History Drift                   │
│                           │  ┌──────────┬──────────────────┐ │
│                           │  │场景      │Token Δ vs prev   │ │
│                           │  │simple_qa │▲ +5.2%           │ │
│                           │  └──────────┴──────────────────┘ │
└───────────────────────────┴──────────────────────────────────┘
```

- **左侧**：场景 checkbox 列表（全选 / 按需选）+ 实时运行进度（SSE 驱动，每场景完成后追加一行）
- **右侧上**：结果表格（场景名 / 成功标志 / Tokens / Wall 时间 / Quality Score）
- **右侧下**：与上次运行的 Token 漂移对比（超过 20% 标红）
- 数据持久化于 `.react/benchmark/report.json`（报告）和 `.react/benchmark/history.json`（历史）

### Scheduler 界面（`#s-scheduler`）

点击工作站主页 **[🗓 Scheduler]** 进入，独立全屏。

```
┌──────────────────────────────────────────────────────────────┐
│  ◀ Home   Scheduler  [—]        [+ New Task] [↺ Refresh]    │
├───────────────────────────┬──────────────────────────────────┤
│  Task Table               │  Timeline — Today                │
│  ┌────┬──────┬───────┬──┐ │  ┌──────────────────────────┐   │
│  │Name│Profil│Trigger│..│ │  │08:30  conversation  ...  │   │
│  ├────┼──────┼───────┼──┤ │  │09:12  tool_call  search  │   │
│  │daily│mini │interval│ │ │  │10:05  plan_event  task_a  │   │
│  └────┴──────┴───────┴──┘ │  └──────────────────────────┘   │
│                           │  （今日事件，时间倒序，来自       │
│  [New Task Form（折叠）]   │   GET /api/timeline）            │
└───────────────────────────┴──────────────────────────────────┘
```

- **左侧**：当前任务列表（调用 `GET /api/scheduler/tasks`）+ 新建表单（+ New Task 按钮展开）
- **右侧**：今日时间轴（调用 `GET /api/timeline`，展示 `TimelineStore` 写入的所有事件，时间倒序）
- 时间轴事件类型包括：`conversation`（对话完成）、`tool_call`（工具调用）、`plan_event`（Plan 编排事件）等

