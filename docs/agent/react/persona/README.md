# agent/react/persona（已迁移）

人格实现已迁至 **`agent/soul/persona`**。React 侧使用 `PersonaService`，其底层状态与持久化由 `PersonaManager` 管理；面向 Tao prompt 的转换位于 `agent/adapters/soul_tao/persona_prompt.py`。

请参阅：[agent/soul/persona/README.md](../../soul/persona/README.md)。
