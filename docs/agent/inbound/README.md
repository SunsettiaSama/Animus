# agent/inbound

`src/agent/inbound/` 是 **agent 顶层** 的会话首轮路由器：把 WebUI 第一条用户输入分成 `speak` 或 `work`。它不在 Soul/Speak 里，也不做会话中的 agent ↔ worker 通信。

WebUI 传输面是 [`src/webui/routers/agent.py`](../../src/webui/routers/agent.py) 的 **`/ws/agent/run`**。`/ws/speak/run` 只承载纯 Speak 长连接，不分类。

## 何时分类

- 只在 `session_open` 后第一条 `user_message` 上调用 `InboundRouter.handle()`。
- 结果钉在该 `session_id`。同会话后续消息不再分类。
- 没有可用 embedding 就不分类、不调 LLM、不入金池、不回落正则。

```text
/ws/agent/run
  session_open
  第一条 user_message
    -> EmbeddingService.embed_query
    -> 未上线 SVM 或仍在前 1k 首轮：embedding 接地 LLM
    -> 已上线 SVM：二维线性 SVM
    -> 钉住 session.route
         speak -> SoulService.speak_run_turn
         work  -> WorkIntentSignal + WorkerWorkService.submit_intent
```

## 二维特征

维护两类质心 `μ_work`、`μ_speak`（金池均值）。查询向量 `q` 只投影成两个差分特征，避免把两侧 cosine / L2 原值同时喂给线性模型：

```text
f1 = cos(q, μ_work) − cos(q, μ_speak)
f2 = ||q − μ_speak||₂ − ||q − μ_work||₂
```

两者越大越偏 `work`，越小越偏 `speak`。SVM 是 numpy Pegasos（hinge + L2），输入就是 `(f1, f2)`。权重文件带 `feature_dim=2`；旧四维权重会被忽略。

## 前 1k 与 SVM 上线

- 全局前 **1000 次会话首轮** 强制走 LLM（即使金池已经不少）。
- LLM 必须先 embedding：近邻样本 + `f1`/`f2` 进入短判定 prompt，只输出 `speak|work`。
- 金池正确样本 `n >= 1000` 后异步全量训练；训练成功才切到 SVM。之后新会话首轮不再走 LLM。
- 1k 请求用完但金池仍不足：继续 LLM，直到金池达标并训练完成。

种子例句（实现/修复/运行测试 vs 你好/陪我聊聊）带 embedding 后作为金池起步，不是正则闸门。

## 击穿

击穿只表示：**已经给出 speak/work，用户说标错了**。不是间隔不够，不是 embed 失败。

- 只发生在本会话首轮结果上。
- 用户真标签写入金池；原预测只记 pierce 日志。
- 超时、空输入、Worker 执行确认超时不是击穿，不入池。
- 前端只在首轮结果上提供「分错了」，没有常驻「自动 / 对话 / 干活」开关。

Worker 的 `work_confirmation_required` 是执行授权，和击穿不是同一件事。`reason` 以 `agent_inbound` 开头的信号不再做正则二次分类。

## 持久化

`.react/inbound/`：

| 文件 | 内容 |
|---|---|
| `route_samples.json` | 金池（最终正确标签 + embedding） |
| `route_weights.json` | SVM `w/b`、质心、`feature_dim` |
| `route_sessions.json` | 已钉住的 session.route |
| `route_pierces.json` | 击穿日志 |
| `route_meta.json` | 全局首轮计数 |

## 文件

| 路径 | 职责 |
|---|---|
| `types.py` | `RouteKind`、`RouteDecision`、`RouteContext`、`PierceResult` |
| `metrics.py` | cosine、L2、质心、`route_features()` |
| `llm_judge.py` | embedding 近邻 + 二维特征 → LLM |
| `classifier.py` | 质心投影 + 线性 SVM |
| `store.py` | 金池、权重、session、pierce、计数 |
| `router.py` | `handle()` / `pierce()` / 异步训练 |
