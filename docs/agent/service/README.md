# agent/service — AgentService

将 **`SchedulerEngine`**、**`TaskRunner`**、**`HeartbeatModule`** 组装为可 **`start()` / `stop()`** 的长期运行单元；适用于 Bot、常驻工作站进程等需要在后台持续推进时钟与心跳的场景。

源码：`src/agent/service.py`。

---

## 组装关系

```
AgentService.start()
    → SchedulerEngine(cfg, executor=TaskRunner, heartbeat=HeartbeatModule)
    → TemporalClock.start()
```

`TaskRunner` 与 `HeartbeatModule` 在构造阶段 **`scheduler_engine` 可先为空**，`start()` 创建 Engine 后再回注到 checker / runner，避免循环依赖。

---

## 可选依赖

构造参数可传入 **`life_manager`**（心跳钩子）、**`journal`**、**`channel_router`**、**`long_term`**、**`timeline`**、`notify_fn` 等，供任务落地写结果、推送通知或与记忆/时间线联动。

---

## 相关文档

- [runtime/README.md](../../runtime/README.md)
- [agent/soul/heartbeat/README.md](../soul/heartbeat/README.md)
