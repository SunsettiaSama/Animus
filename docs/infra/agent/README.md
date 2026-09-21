# infra.agent — 幻觉兜底（格式审查 + 输出审查官）

`src/infra/agent` 在最小 T/A/O 循环（`loop.py` / `parse.py`）之上提供两层输出防护：

```text
LLM 原始输出
  └─ parse.py        <T>/<A>/<O> 解析（失败 → "parse error" observation 回写）
       └─ review.py  工具调用格式审查（违规 → 整批拦截 + 纠错 observation）
            └─ action_runner.run(calls)
  异步旁路：auditor.py 输出忠实性审查官（默认关闭、静默）
```

## 格式审查（WhitelistCallReview）

- 挂载点：`BaseAgent` / `AgentService` 的 `call_review` 参数（默认 `None` = 行为不变）。
- 语义：**整批拦截**。parse 成功且非 finish 的步骤，先审查后执行；任一调用违规
  （action 为空、未知工具、args 非 dict），本步不执行任何工具，纠错文本以
  `add_observation(correction, tool="review", source="review")` 回写，模型下一步自纠
  （与 parse-error 路径同构，消耗一步）。
- 未知工具用 `difflib` 生成**显式**建议（"你是否想用 X"，由模型决定），不静默替换。
- 白名单支持动态来源：`frozenset[str]` 或 `Callable[[], frozenset[str]]`；取名单失败或
  名单为空时退化为纯结构检查，不误拦。审查器自身抛异常时 fail-open（放行 + warning 日志）。

```python
from infra.agent import AgentService, WhitelistCallReview

service = AgentService(
    llm,
    runner,
    call_review=WhitelistCallReview(runner.ACTIONS),  # 或 lambda: 动态名单
)
```

## 输出审查官（OutputAuditor）

对照时间线上下文（输入）判断模型产出（输出）是否包含**上下文完全没有提及**的事实性主张。

- **昂贵**：每次审查额外一次 LLM 调用；LLM 由调用方注入（建议走 aux 槽位，如
  `llm_service.get_aux_llm("auditor")`，未注册自动回退主模型）。
- **默认关闭**：`AuditorConfig(enabled=False)`；未启用时 `submit()` 直接忽略、不建线程。
- **异步**：内部常驻单线程 FIFO（`infra/threading.py` 的 ThreadLease 模式，owner=
  `agent.auditor`，可 `stop_owner("agent.auditor")` 回收）；`BaseAgent.step()` 在
  finish（默认）或每步（`scope="every_step"`）fire-and-forget 提交，不阻塞主循环。
- **静默**：裁决只写 logger（不忠实时 WARNING）与 obs 事件 `AuditEvent`
  （`.react/logs/obs_*.jsonl`），不修改 answer、不触发重试、永不 raise；
  解析失败/LLM 异常降级为 `faithful=None`（不确定）。

```python
from infra.agent import AgentService, AuditorConfig, OutputAuditor

auditor = OutputAuditor(llm_service.get_aux_llm("auditor"), AuditorConfig(enabled=True))
service = AgentService(llm, runner, auditor=auditor)
...
auditor.stop()   # 由持有方负责停止
```

## 测试

```bash
pytest src/test/infra/agent -q
```

覆盖：整批拦截与自纠（`test_loop.py`）、白名单/模糊建议/结构检查（`test_review.py`）、
裁决解析容错与异步静默（`test_auditor.py`）。
