# ReAct Workstation

**ReAct 工作站**：面向日常使用的统一运行环境——在本地或容器化部署下一套入口即可驱动 ReAct 智能体、多轮对话、Plan 编排、记忆与知识库、定时任务与 Web 操作台。

- **运行时**：`python src/run.py`（默认 WebUI；可选 CLI、`--check` 健康检查、SearXNG 容器管理）
- **详细说明**：[docs/README.md](docs/README.md)（架构、模块状态、快速代码示例）
- **容器与观测**：[`docker/README.md`](docker/README.md)（Compose、管理容器、Grafana/Prometheus/Loki 等）

本仓库正从「框架型项目」演进为**可长期驻留的工作站形态**：同一套配置与数据目录支撑开发调试与生产部署，通过 WebUI 完成交互与编排，通过 `docs/` 分层文档维护各子系统约定。
