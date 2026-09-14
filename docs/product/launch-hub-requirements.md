# 启动站（Launch Hub）与统一启动流程 — 需求文档

- 状态：**实施中**（2026-09-14 讨论定稿；分支 `feat/launch-hub`；按第 7 节顺序执行）
- 关联：`docs/product/README.md`（产品形态与多客户端定位）、`docs/webui/README.md`

---

## 1. 决策记录（讨论结论，实施时不得偏离）

1. **放弃独立 GUI 壳**（tkinter / pywebview / Electron / Tauri 均否）。理由：本地 AI 工具的工业惯例就是"本地后端 + Web 前端"（Ollama / ComfyUI / A1111 同构）；现有 webui 资产（FastAPI + js2 前端）直接复用；产品文档的多客户端战略本就以 WebUI 为控制室。
2. **统一入口 = webui 内的"启动站"页面**：从启动站自由选择进入 Web 对话、打开本地游戏 demo、桌宠等。
3. **术语约定**：
   - **产品形态 A「本地部署」** = 前端与后端都跑在用户本机（现状，本文所有需求的目标形态）；
   - **产品形态 B「服务端部署」** = 服务端在服务器/云端，客户端在用户处（未来形态）。
   - 与 `docs/product/README.md` 的本地/云端/混合三形态一一对应。设计不得写入阻碍形态 B 的假设（见 3.1 依赖规则、R5.3）。

---

## 2. 现状盘点（实施前事实，均已在代码中核实）

### 2.1 启动链

```
start.bat（双击入口）
  ├─ 定位 Python：venv/.venv → conda(D:\anaconda\envs\LLMs) → 系统 Python
  ├─ 依赖安装：requirements.txt MD5 哈希比对，变化则 uv/pip 重装
  ├─ 控制台问答：是否 Docker 起 MySQL+Redis？是否跳过 SearXNG？
  └─ python src/run.py → uvicorn(webui.app) in-process → 轮询 8300 就绪 → 开浏览器
```

- `src/run.py`：进程入口（`--mode webui|cli|check`），`--host` 默认 `127.0.0.1`（`config/agent/run_config.py:9`）、`--port` 默认 8300。定位是**工作站启动薄壳**，不放业务。
- `src/webui/app.py`：`GET /` 直接返回 `index.html`（js2 控制室/对话 SPA）。
- js2 SPA：屏幕制路由（`ui/router.js`，screens = landing/workspace/plan/benchmark/scheduler），**启动需先过账号门（account gate）**——因此启动站不能做成 SPA 内的一个屏。
- infra 初始化：`src/webui/state.py::_init_infra()` → `LLMService(...)`；embedding 经 `app.py` 启动事件挂到 `state.inbound_router`（懒加载）。
- soul 启动：`src/agent/adapters/soul_bootstrap.py::do_soul_init`（硬性要求 `persona.enabled=true` 且 LLM handle 就绪）。
- 已有就绪判定：`GET /api/soul/readiness`（routers/soul.py）——本需求将其判定逻辑**上移为 launch 层正本**（见 3.2）。

### 2.2 可选接口清单（hub 配置面要覆盖的全部选项）

| 能力 | 可选项 | 配置位置 | 就绪判定 |
|---|---|---|---|
| LLM | `openai` 兼容远程 API / `vllm` / `transformers` | `src/config/llm_core/config.py`（`LLMConfig.backend`，另有 `trained_model_path` 微调权重） | 探活一次补全 |
| Embedding | 本地 HF 模型，默认 `BAAI/bge-small-zh-v1.5` | `src/config/embedding/config.py` + `config/soul/memory/infra.yaml` | 懒加载，可预热 |
| 存储 | `json` / `mysql` | `config/infra/db.yaml` → `DBConfig.resolved_storage_backend()` | mysql 探活，失败降级提示 |
| 搜索 | SearXNG(Docker) → Tavily → DDG 逐级降级 | `infra/searxng_manager` | 可选能力 |
| 知识库 | MySQL + Redis | `docker/docker-compose-db.yml` | 可选能力 |

### 2.3 demo 清单

| demo | 形态 | 启动方式 | 依赖 |
|---|---|---|---|
| 星陨之痕 metroidvania | 纯 HTML5 Canvas + 原生 JS，零构建 | 双击 `index.html` 或静态服务 | 无（未接 soul） |
| 桌宠 desktop_pet | Python 进程（pygame + win32 分层窗口） | `PYTHONPATH=src python demos/desktop_pet/main.py [--char X --scale N]` | **soul ready**（WS `127.0.0.1:8300`，session `live:desktop-pet`） |
| 小镇 pygame_town | Python 进程 | `PYTHONPATH=src python demos/pygame_town/main.py` | **soul ready**（channel `pygame-town`） |
| speak 节奏验证台 | Python 进程（fake LLM） | `python demos/speak/run.py` | 开发者工具，不依赖 soul |

### 2.4 问题清单（本需求要解决的）

- **P1 入口分散**：环境问答在 start.bat 控制台；接口选择散落各 yaml；demo 全靠手动命令行。
- **P2 首页即控制室**：`/` 直接进对话/配置界面，没有总览、没有引导；且 SPA 要先过账号门。
- **P3 demo 进程无托管**：手动起、手动杀；webui 关闭与 demo 生命周期无约定。
- **P4 启动阶段不可见**：soul/LLM/embedding/存储就绪状态没有统一聚合端点（散落在 `/api/speak/status`、`/api/soul/readiness` 等处）。
- **P5 抽象层级缺失**：启动编排在 `run.py`（工作站薄壳）与 `webui/state.py`（表现层）里各长一半，没有独立的域。

---

## 3. 抽象层级与目录结构（定稿）

### 3.1 分层模型与依赖规则

```
src/
  run.py                  进程入口薄壳：CLI 解析 → 组装宿主。不放业务（"工作站启动"仅此而已）。
  launch/                 ★ 宿主编排层（新顶层包，与 agent/infra/webui 平级）＝启动站后端域
    phases.py             五阶段模型（env→config→infra→soul→serve）与阶段判定
    probes.py             探测原语：LLM handle / 存储后端 / persona 文件 / soul 运行态（duck-typed state，无 webui 依赖）
    status.py             聚合快照 snapshot(state)：/api/launch/status 与 run.py --check 的共同正本
    guide.py              失败项 → 人话原因 + 修复指引
    demos/                【形态 A 专属】demo 注册表 + 子进程托管
      registry.py         注册表：id / 名称 / 启动命令模板 / 依赖声明
      manager.py          子进程托管：start/stop/状态/退出清理钩子
  webui/                  表现层（FastAPI app + 前端页面）
    routers/launch.py     薄适配：GET /api/launch/status → launch.status.snapshot(state)
    routers/demos.py      薄适配：/api/demos* → launch.demos（Phase 2）
    static/hub/           启动站前端：独立轻页面（hub.html/css/js，原生 JS，不依赖 js2、不过账号门）
    static/js2/           控制室 SPA（原样保留，挂到 /console）
```

**依赖方向（强制）**：

- `run.py → launch → {config, infra, agent}`；
- `webui → launch`：只允许经 routers 薄适配调用；
- **`launch` 不得 import `webui`**——形态 B 的无头服务端将来复用同一套 launch 编排，其中没有 webui；
- `launch/demos/` 子包标注形态 A 专属，无头服务端路径不得引用。

### 3.2 URL 分层（进站前 / 进站后）

| URL | 层 | 内容 |
|---|---|---|
| `/` | 进站前 | 启动站：五阶段状态灯 + 入口卡片 + 修复引导。独立轻页面，无账号门。 |
| `/console` | 进站后 | js2 控制室 SPA（账号门 → landing/workspace/…，内部逻辑不变）。 |

### 3.3 判定逻辑正本归位

- 就绪判定的正本 = `launch/probes.py` + `launch/status.py`；
- `webui/routers/soul.py` 的 `/api/soul/readiness` 暂保持原样（SPA 依赖），**Phase 3 改为委托 launch 层**，避免双正本漂移。

---

## 4. 需求

### R1 统一启动流程（后端，落 `src/launch/`）

- **R1.1** 启动序列标准化为五阶段：`env`（Python/依赖）→ `config`（yaml 装载）→ `infra`（LLM/embedding/存储）→ `soul`（`do_soul_init`）→ `serve`（webui 在役）。每阶段状态可查询。
- **R1.2** 聚合状态端点 `GET /api/launch/status`（薄适配在 `webui/routers/launch.py`）：返回五阶段灯 + 详情（llm 的 backend/model、embedding 的 model/ready、storage 的 backend/ok、soul 的 state/speak_initialized、demos 运行态）。
- **R1.3** 阶段失败给人话原因与修复指引（`launch/guide.py`，复用 `soul_init_error` 等现有错误通道），例如 `persona.enabled=false` → "去设置 → 人格演化 → 启用"。
- **R1.4** `start.bat` 保留但简化：控制台问答（Docker DB / SearXNG）迁到 hub 首次启动引导卡；bat 只负责 找 Python → 装依赖 → 起服务 → 开浏览器。

### R2 启动站页面（前端，落 `src/webui/static/hub/`）

- **R2.1** `/` 改为启动站独立轻页面；原 js2 控制室迁至 `/console`（SPA 内部不动）。
- **R2.2** hub 内容四区：
  1. **状态区**：五阶段就绪灯，轮询 `/api/launch/status`；
  2. **入口卡片**：Web 对话（→ `/console`）、桌宠、小镇、星陨之痕；（speak 验证台仅开发者开关下显示）
  3. **引导区**：未就绪项的一键修复/说明（persona 未启用直达 `/console` 设置、embedding 预热、mysql 降级黄牌）；
  4. **配置直达**：`/console` 的 LLM/人格/记忆/知识库设置。
- **R2.3** demo 卡片状态机：`不可用`（soul 未就绪，置灰+原因）→ `运行中`（含停止按钮）→ `已停止`。
- **R2.4** 页脚标注形态："本地部署：前端与后端均运行在本机（产品形态 A）"。

### R3 接口选择约定（配置面）

- **R3.1** LLM 后端选择三选一：`openai` 兼容远程（base_url/key/model）/ `vllm`（本地服务地址）/ `transformers`（本地权重路径）。落盘到 `config/llm_core` 现有结构，**不自造新配置格式**。
- **R3.2** embedding：显示当前模型与就绪态；提供预热/预下载操作（复用 `hf_download`）。
- **R3.3** 存储后端切换 `json`/`mysql`：mysql 未连通时黄牌提示且**不阻塞启动**（json 兜底，与现有 resolved_storage_backend 行为一致）。
- **R3.4** 任何接口切换不允许用户改代码；需明确哪些改动要重启 soul、哪些热生效，并在 UI 标注。

### R4 demo 集成与进程托管（落 `src/launch/demos/` + `webui/routers/demos.py`）

- **R4.1** `GET /api/demos`（注册表+运行态）、`POST /api/demos/{id}/start|stop`（start body 可带参数，如 `--char`/`--scale`）。
- **R4.2** 子进程托管：`subprocess.Popen([sys.executable, entry, ...], cwd=ROOT, env={PYTHONPATH: src})`，stdout/stderr 落盘 `.react/logs/demo-{id}.log`；AppState 挂 child 进程表；**webui shutdown 与 atexit 统一清理子进程**。
- **R4.3** metroidvania：`app.mount("/demos/metroidvania", StaticFiles(directory=ROOT/"demos/metroidvania", html=True))`，hub 卡片直接链接。（目录在仓库根而非 `src/webui/` 下，用 ROOT 相对解析。）
- **R4.4** desktop_pet / pygame_town 依赖 soul ready：未就绪时 start 返回 409 + 人话原因。
- **R4.5** 同一 demo 单实例：重复 start 幂等返回"运行中"。

### R5 网络与部署约定

- **R5.1** 监听默认 `127.0.0.1:8300`（`run_config.py` 已是默认）；`--host 0.0.0.0` 仅限用户显式传参，`src/run.py` 帮助文本示例同步改为 127.0.0.1。
- **R5.2** 形态 A 契约落 docs：数据全本地（`.react/`、json_root、可选本地 MySQL）、无云依赖、loopback only。
- **R5.3** 子进程托管（R4.2）是**形态 A 专属**能力：代码集中在 `src/launch/demos/` 并注释标注，不得进入未来无头服务端路径。

---

## 5. 非目标

- 不做独立 GUI 壳（已决策，见 1.1）。
- 不做多用户/鉴权（形态 B 课题，product README 已列）。
- 不做打包发行（pyinstaller / 安装包，另立需求）。
- 不改造 demo 本体（只托管，不改 desktop_pet / pygame_town 内部代码）。

---

## 6. 验收标准

1. 双击 `start.bat` → 浏览器自动打开启动站；五阶段状态灯全绿（或有可解释的黄牌）。
2. 从 hub 一键进入 Web 对话（`/console`）。
3. soul 就绪后：hub 拉起桌宠（出窗口、可气泡对话）→ 点停止可退出；**关闭 webui 时桌宠/小镇自动退出**。
4. hub 内点击"星陨之痕"直接游玩（`/demos/metroidvania/`）。
5. 切换 LLM 后端（openai ↔ vllm/transformers）后状态面板正确反映，需重启 soul 的项有明确提示。
6. `persona.enabled=false` 等典型错误在 hub 有人话提示 + 直达修复入口。
7. `python src/run.py --check` 与 `GET /api/launch/status` 结论一致（同一套 launch 层判定）。

---

## 7. 实施拆分（分支 `feat/launch-hub`）

| Phase | 内容 | 涉及 |
|---|---|---|
| 1 | `src/launch/`（phases/probes/guide/status）+ `webui/routers/launch.py` + hub 轻页面 + `/`→hub、控制室迁 `/console` + run.py 帮助文本收敛 | 本文档 3.1 全部新文件 |
| 2 | `launch/demos/`（registry+manager）+ `webui/routers/demos.py` + metroidvania 静态挂载 + shutdown 清理钩子 | `src/launch/demos/` |
| 3 | 接口选择配置面 + start.bat 简化（问答迁 hub 引导卡）+ `/api/soul/readiness` 委托 launch 层 + 启动序列事件化（sequence 编排进 app startup） | `launch/` 扩展、start.bat |
| 4（可选） | demo 启动参数 UI、日志页内 tail、开发者模式开关 | js2 |

## 8. 开放问题（默认值已给，实施前可推翻）

1. ~~`/` 直接是 hub，还是 hub 放 `/hub` 由 `/` 重定向？~~ **已定：`/` 即 hub 独立轻页面**（SPA 有账号门，hub 必须在门外）。
2. ~~原控制室路由名？~~ **已定：`/console`。**
3. desktop_pet 启动参数（`--char`/`--scale`）是否上 UI？**默认：Phase 4 再做，先用注册表默认参数。**
4. `demos/speak` 验证台是否出现在 hub？**默认：开发者开关，默认隐藏。**
5. 子进程日志呈现方式？**默认：落盘 + "打开日志"按钮，不做页内 tail。**
