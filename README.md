# 栖灵 Animus

**会思考、会行动、会记住、会成长的驻留型智能体平台。**

栖灵（Animus）是一套可长期运行的 AI Agent 环境：用户通过 Web 界面与之对话、下达任务；系统在后台持续积累记忆、演化人格、推进生活叙事，并在合适的时候主动出现——而不只是「问一句答一句」的无状态聊天。

---

## 为什么值得关注

- **任务能力**：推理 + 工具 + 子智能体 + 流程编排，胜任复杂工作流
- **关系连续性**：跨会话记忆、稳定人格、可感知的生活经历
- **产品化形态**：开箱即用的 Web 控制台，支持本地与 Docker 部署
- **可扩展**：模块化设计，可按需启用记忆、语音、调度等能力

→ **愿景、蓝图与完整文档导航**：[docs/README.md](docs/README.md)

---

## 快速开始

```bash
python src/run.py
```

默认启动 Web 控制台。可选 CLI、健康检查、端口指定等见 `src/run.py` 内说明。

**容器与生产部署**：[docker/README.md](docker/README.md)

---

## 文档入口

| 想了解… | 从这里开始 |
|---|---|
| 产品愿景与能力蓝图 | [docs/README.md](docs/README.md) |
| Soul（记忆 / 人格 / 生活 / 对话） | [docs/agent/soul/README.md](docs/agent/soul/README.md) |
| 推理环与工具 | [docs/agent/react/README.md](docs/agent/react/README.md) |
| Web 控制台 | [docs/webui/README.md](docs/webui/README.md) |

完整文档索引见 [docs/README.md · 文档导航](docs/README.md#文档导航)。

---

## 源码概览

```
src/
├── agent/          # 智能体核心（推理环 · Soul · Flow · 会话与接入）
├── webui/          # Web 界面与 API
├── infra/          # LLM、搜索、数据库等基础设施
├── runtime/        # 调度与时间任务
├── config/         # 配置
└── run.py          # 统一启动入口
```

实现细节、API 与模块说明均在 `docs/` 目录，按子系统分文档维护。
