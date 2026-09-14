# 单窗口永续对话 + 剧情自主（记忆即历史 · life 出剧情 · 角色自管开口 · speak 只扮演）— 需求文档

- 状态：**已实施（部分）v5**（2026-09-14；v1 单窗口 → v2 导演编剧迁 life → v3 角色自管
  开口/卡片双段/预跑 → v4 缺口修补+分层定稿 → v5 实施与验收记录，见第 13 节）
- 关联：`launch-hub-requirements.md`、`docs/agent/soul/README.md`、`docs/product/README.md`

---

## 1. 动机

三个错位：
1. **历史被当成档案**：会话档案柜隐喻（新建→轮次→存档→切换）不适合陪伴型 soul，
   "过去"应该是记忆：可被想起、会淡忘、能回响；
2. **生活被前端绑架**：剧情机器长在 speak 会话内部，前端打开才初始化轮询，关闭即
   停摆；
3. **开口被剧情包办**：导演"主动开口"、预约梯子、沉默阶梯挂在导演/编剧名下——
   但"何时开口、何时沉默"是角色的性格，不是剧情的决策。

## 2. 语义对齐（术语表，全文按此解读）

| 术语 | 定义 | 归属 |
|---|---|---|
| **记忆（memory）** | soul 对过去的唯一持有：dialogue experience、chronicle、中枢记忆 | 记忆系统 |
| **剧情（story/beat）** | life 侧自主推进的事件流：landmark 推进、议程到点、生活事件 | **life** |
| **导演（director）** | 剧情决策：下一个 beat、走向与推进节奏（**不管表演时机**） | **life**（迁入） |
| **编剧（screenwriter）** | 把 beat 写成可演材料（大纲 + 剧本式文本） | **life**（迁入） |
| **角色（character）** | speak 侧表演者人格（`CharacterRuntime`）；**自管**开口预约（开口卡片）、沉默、轮换节奏 | **speak** |
| **表演（perform）** | 把 beat 转成对用户的言语表达 | **speak** |
| **剧情卡片（story card）** | 剧情弧呈现单元：**大纲段（不变）+ 演绎进度段（实时）** | life 产内容，窗口呈现 |
| **窗口（window）** | 每账号/渠道唯一永续前端表面；刷新只恢复近期尾巴 | 前端 |
| **在场（presence）** | 用户是否连着；只影响**表演时机**，不影响剧情发生 | speak/角色 |

**三条职责原则**：speak 不持有历史；speak 不发起剧情；角色自管开口与沉默。

## 3. 目标（五句话）

1. 前端永久只留一个窗口：一条持续生长的流；
2. speak 只保留一个对外接口（`WS /ws/speak/run`）；
3. 历史完全交给记忆系统，"看过去" = 记忆检索；
4. 剧情完全交给 life：导演/编剧随 landmark 日程自主运转，与前端在否无关；
5. 角色自管开口；剧情卡片 = 大纲（不变）+ 进度（实时同步）；life 预跑演绎做缓存，
   speak 消费零等待。

## 4. 现状盘点（事实，已核实）

### 4.1 待退役/待收敛
- 前端多会话：`conversation.js`（turn 状态机）、`history_store.js`（转录持久化）、
  `history_list.js`（会话列表）；
- `/api/history` CRUD + `history_files.py`（JSON 转录）；
- speak 对外路径：WS 主路径 + HTTP 伴随（status/notify SSE/create_ui/proactive_ack）
  + legacy chat/react 对话路由。

### 4.2 已有地基
- 记忆记账：`life/experience/dialogue/` `record_dialogue_turn`（DialogueTurn 含
  salience/情绪增量）+ working_memory 短时衰减；
- 角色宿主：`responders/request_driven/character/`（CharacterRuntime/AgentHost、
  interaction 交互账本、memory_buffer、rhythm schedule）；
- 预热雏形：`story_pool/prewarmer.py`（后台异步生成候选灌池、pool_depth 护栏、
  同 key 单线程）；
- life 承接件：heartbeat checklist 网格 + `landmark_schedule`；
  `life/virtual/journal/`（LandmarkAgendaPlanner/Store、StorySceneGroundingPort）；
  `SoulService._ensure_story_service()` story_port 接线雏形；
- 编剧产出分层：大纲 / 剧情 unit / 开场旁白（`screenwriter/writer.py`）——卡片
  "大纲段"素材现成；
- 端口先例：`agent/soul/ports.py`（EmbeddingPort/LLMServicePort）——契约内核的
  仓库惯用法。

### 4.3 现存错位（证据）
- `directors/`、`screenwriter/`、`story_pool/`、`timeline.py` 长在
  `speak/responders/request_driven/` 内部；
- `start_dialogue_session()`（WS 连上才调）→ `ensure_screenwriter_init`；主动循环
  以 session 为单位；
- `speak/service.py`："导演主动开口：请求角色生成"、"取消近端预约 due，防止预约
  梯子…连发自言"——开口/预约/沉默调度权散落导演与编排器之间。

### 4.4 已知风险（v4 标注）
- **R-timeline**：`experience/hub/stack.py` 为纯内存态（无持久化方法），
  `close_dialogue` 才交出 ExperienceUnit——`/api/memory/timeline` 不能直接查内存
  会话，需要读模型（默认方案见开放问题 13）；
- **R-god**：`SoulService`/`SpeakService` 均为巨型对象，本需求**不重构**它们，但
  新接线必须集中（见 5.4 组装根规则），不得继续散落加深。

## 5. 抽象层级与目录结构（定稿，v4 核心）

### 5.1 分层模型

| 层 | 包 | 职责 | 禁止 |
|---|---|---|---|
| **L0 契约内核** | `agent/soul/storybus/` | 消息数据类（beat/ack/progress/signal）+ 端口协议（Outbox/Inbox/AckReceiver）；**零实现** | import 任何 soul 子系统 |
| **L1 领域层** | `agent/soul/life/`（含新子域 `life/story/`）、`memory/`、`persona/`、`presence/` | 生活与剧情的拥有者 | life/story ↛ speak、↛ webui |
| **L2 表演层** | `agent/soul/speak/`（character + performer + io） | 角色、表演、WS 出入口 | ↛ life/story、↛ life/virtual |
| **L3 时钟与组装** | `heartbeat/`（tick 网格）+ `SoulService`（组装根） | 驱动与接线 | 仅组装根可同时 import life/story 与 speak |
| **L4 宿主层** | `webui/`、`launch/`、`run.py` | 薄路由/页面/入口 | 业务逻辑不入宿主 |

### 5.2 目标目录树（含物理迁移终点）

```
agent/soul/
  storybus/                    ★ L0 新增：契约内核（沿用 ports.py 惯用法，独立成包）
    messages.py                  LifeStoryBeat / BeatAck / StoryProgressSync /
                                StorySignal / StoryCard（纯 dataclass）
    ports.py                     LifeStoryOutboxPort / SpeakBeatInboxPort /
                                BeatAckReceiver / StorySignalInbox（Protocol）
  life/
    story/                     ★ L1 新增：剧情子域（Phase 2 迁入 + 扩充）
      director/                  ← speak/.../request_driven/directors/（迁移）
      writer/                    ← speak/.../request_driven/screenwriter/（迁移）
      pool/                      ← speak/.../request_driven/story_pool/（迁移+升级为
                                  演绎级预跑缓存 R9）
      cards.py                   剧情卡片双段模型（R8）
      scheduler.py               剧情排程（注册为 heartbeat checklist item）
      outbox.py                  LifeStoryOutboxPort 实现（投递/幂等/保鲜）
    experience/  virtual/journal/  anchor/ …                （已有，不动）
  memory/
    timeline.py                ★ L1 新增：时间轴读模型（R2，读 append-only 流水）
  speak/
    responders/request_driven/
      character/                  （已有；收拢开口/沉默/预约决策权 R7）
      performance/              ★ 瘦身后的表演件（BeatPerformer；原"决定说什么"
                                  路径退役后 request_driven 更名/整理，Phase 4）
    io/outbound/…                 （已有 WS 端口，帧协议扩展见 8）
  heartbeat/                     （已有；checklist 注册 story scheduler）
  wiring/                      ★ L3 新增：组装模块
    story.py                      outbox↔inbox↔ack↔signal 接线（组装根的具象化，
                                  SoulService 只调用，不再内联长接线）
  ports.py                       （已有；storybus 之外的跨域端口仍在此）
```

### 5.3 依赖规则（强制，实施时以此审查 import）

```
storybus  → （无依赖）
life/story → storybus, life/{journal,experience}, persona, llm ports
speak     → storybus, memory(record), presence, persona(dialogue slice)
heartbeat → life/story.scheduler（仅公开入口）
wiring    → life/story + speak + storybus（唯一双向点）
SoulService → wiring（组装根只调 wiring，不再手搓接线）
webui     → soul 公开 API（thin routers）；launch 层不涉本需求
```

**禁止**：`speak` import `life/story`（经 storybus 消息通信）；`life/story`
import `speak`；`storybus` import 任何实现；`webui` 直接 import `life/story`
内部（卡片数据经 soul 公开方法/WS 帧）。

### 5.4 组装根规则

- 新接线**全部**落 `wiring/story.py`；`SoulService._ensure_story_service` 改为调用
  wiring，不新增内联逻辑——本需求不动 service.py 存量，但**增量为零容忍**；
- 启动序：SoulService.start → wiring/story 装配（storybus 端口互接）→ heartbeat
  注册 story scheduler → 导演/编剧常驻就绪（R6.1）。

## 6. 需求分解

### R1 前端单窗口改造（js2）
- 移除会话列表/新建/切换入口、history_store 写入；对话区改单一永续流视图；
- 刷新只恢复近期流尾（默认 50 事件或 24h）；"回溯更早" → R2。

### R2 记忆检索视图（"回忆"）
- 后端 `GET /api/memory/timeline`（`memory/timeline.py` 读模型 + webui 薄路由）；
- 前端回忆面板：时间轴 + 关键词搜索，片段卡片呈现；
- 读模型默认走 append-only 轮次流水（开放问题 13）。

### R3 speak 接口收敛
- 唯一对外 `WS /ws/speak/run`；HTTP 仅留 status + proactive_ack；
- 退役 legacy chat/react 对话路径、create_ui、notify SSE（开放问题 5）；
- `pipeline` 参数收敛唯一合法值（开放问题 2）。

### R4 会话模型简化
- session 固定 `live:<channel>`；start/close 语义 = 在场周期，不触发编剧初始化、
  剧情启停、预约启停。

### R5 记忆承接完备性
- 每轮记账：用户轮、beat 演出轮（provenance → beat_id/card_id）、被拒/沉默轮。

### R6 导演/编剧迁移：剧情自主化
- 常驻化（挂 heartbeat checklist，删会话门控）；landmark 到点 → planner → 导演
  → 编剧成稿；speak 的"决定说什么"路径退役；协议见第 7 节；不在场策略见开放
  问题 8。

### R7 角色自管开口与沉默
- 开口决策反转：beat 到达 → 角色按性格/在场/交互账本决定 即时开口|预约|沉默；
- 预约梯子、沉默阶梯、轮换节奏收拢进 CharacterRuntime 的 rhythm schedule；
- 输入边界：角色可见 beat+建议性 hint、presence、自身账本与记忆缓冲；不可见
  landmark 内部态与导演决策过程。

### R8 剧情卡片：双段结构与进度实时同步
- `StoryCard = outline（冻结）+ progress{current, upcoming（预告可变）}`；
- life 演绎推进一步 → `StoryProgressSync` 刷新；
- **前端帧协议扩展**：WS 下行新增 `story_card`（卡片建立/大纲段）、
  `story_progress`（进度段更新）帧——js2 `protocol/frames.js` 扩展，Phase 3；
- upcoming 是预告不是承诺。

### R9 演绎预跑缓存
- prewarmer 上移 `life/story/pool/` 并升级为演绎级预跑：按网格前瞻预跑（默认
  1 网格周期 ≈ 2 beat），产出完整 beat + 卡片进度；
- 护栏：池深即预算（**预跑烧 token，对齐 product README 成本原则**）、同 key 单
  线程、fresh 跳过；beat 带 `cached: true`；
- 失效：导演在用户轮信号（StorySignal）后评估，显著偏离 upcoming 时整卡重算；
  未命中回退同步生成。

### R10 重启恢复语义（v4 新增）
- **剧情态恢复归 life/story**：story_pool / landmark / agenda store 均已落盘，
  重启后续写（沿用现有"活体快照（重启续写）"语义，迁到 life 侧）；
- **表演态恢复归 speak/character**：预约梯子、交互账本、沉默阶梯经角色侧持久化
  （现有账本落库机制）恢复；
- **storybus 无恢复职责**：消息即弃（at-most-once 投递），状态只在两侧领域内；
  未 ack 的 beat 重启后由 life 侧按保鲜期重投或归档。

## 7. Life ↔ Speak 通信协议（v1.2）

### 7.1 传输与拓扑
- 进程内端口（storybus 定义，wiring 装配）；持久化落 story_pool；
- 角色与 life 无直接调用，一切经四类消息。

### 7.2 消息 schema

```yaml
LifeStoryBeat:            # life → speak（给角色的"想说的话"）
  beat_id: str            # 全局唯一，幂等键
  card_id: str            # 所属剧情弧/卡片（可空 = 独立事件）
  channels: [str]         # ★ 目标渠道集合（多张脸），导演决定
  kind: str               # landmark_progress | agenda_due | incident | chronicle_echo
  narrative: str
  performance_hint:       # 建议性输入——开口时机角色自决
    urgency: calm | normal | eager
    share_desire: float   # 0~1
    valid_until: ts
  provenance: { landmark_id, agenda_id, source_tick }
  cached: bool            # 来自预跑缓存则 true

StoryProgressSync:        # life → speak（高频、可合并、无 ack、丢帧无害）
  card_id: str
  current: str
  upcoming: [str]
  updated_at: ts

StorySignal:              # ★ speak → life（用户轮信号，供导演失效判定）
  session_id: str
  channel: str
  turn_digest: str        # 用户轮摘要（非全文，控制信息量）
  salience_hint: float    # 轮末 salience（复用记账值）
  at: ts

BeatAck:                  # speak/角色 → life（按渠道分别回）
  beat_id: str
  channel: str
  status: performed | expired | declined | silenced | suppressed
  performed_at: ts
```

### 7.3 语义约定
- 幂等：beat_id 去重；ProgressSync 可丢可合并（保序）；StorySignal 至少一次；
- 开口自主：beat 到达 ≠ 演出；`silenced` 是正常状态不是失败；
- 优先级：用户对话中角色自行 suppress，life 改期；
- 保鲜：过期 beat 归档记忆（"错过的剧情" → chronicle 事件）；
- 进度一致性：`performed` ack 后才推进 landmark 并 sync；预跑进度为前瞻态；
- 多渠道路由：beat.channels 为集合，各渠道独立 ack；全部渠道终态后剧情才推进
  （默认；单渠道部署无感知）。

## 8. 前端协议扩展（WS 帧新增）

| 帧类型 | 方向 | 载荷 |
|---|---|---|
| `story_card` | 下行 | card_id、outline（冻结段）、初始 progress |
| `story_progress` | 下行 | card_id、current、upcoming |
| beat 元数据 | speak_event 扩展 | beat 演出帧附 beat_id/card_id（供前端归组） |

## 9. 测试策略（v4 新增）
- **storybus 契约单测**：幂等（重复 beat 不重演）、保鲜（过期归档）、ack 状态机
  （五态迁移）、ProgressSync 乱序/丢弃容忍；
- **角色开口决策确定性测试**：fake clock 驱动 rhythm schedule（复用 `demos/speak`
  的 FakeClock/RhythmPoller 先例），覆盖 即时/预约/沉默/suppress 四分支；
- **迁移回归**：WS 帧协议向后兼容（旧字段保留），桌宠/pygame_town 客户端不改动
  即可通过（`src/client/speak_ws.py` 契约不破坏）；
- **预跑护栏测试**：池深超限跳过、同 key 单线程、失效重算。

## 10. 非目标

- 不重构 SoulService/SpeakService 存量（增量集中 wiring，见 5.4）；
- 不改记忆内部算法、persona 蒸馏内容生产、CharacterRuntime 表演内核；
- 多客户端协议不动（帧只增不改）；benchmark/plan/scheduler 屏单独排查。

## 11. 实施拆分（v4，含包级交付物）

| Phase | 内容 | 包级交付物 | 验收要点 |
|---|---|---|---|
| **1 后端基座**（可独立上线） | timeline 读模型 + speak 收敛 + session 在场化 | `memory/timeline.py`、`routers/memory.py` 增端点、`routers/speak.py` 收敛、legacy 路由移除、`service.py` 在场化 | `/api/memory/timeline` 分页可用；对外仅一 WS；`--check` 一致 |
| **2a 契约与接线** | storybus + wiring | `storybus/{messages,ports}.py`、`wiring/story.py`、组装根改造 | 契约单测全绿；依赖规则审查通过（无违禁 import） |
| **2b 剧情常驻** | 导演/编剧逻辑归属迁移 + scheduler | `life/story/{director,writer,scheduler,outbox}.py`（逻辑迁移）、checklist 注册、删会话门控 | 前端关闭后 landmark 仍推进（黑盒观测 story_pool 落盘） |
| **2c 角色收拢** | 开口/沉默/预约归角色 + 多渠道路由 | `character/` 决策收拢、BeatAck 五态、StorySignal | fake-clock 四分支测试通过 |
| **2d 卡片与预跑** | 双段卡片 + ProgressSync + 预跑缓存 | `life/story/{cards.py,pool/}`、前端帧（8 节）暂后端先行 | 预跑命中时消费零 LLM 等待；失效重算路径可观测 |
| **3 前端单窗口** | 流视图 + 卡片双段渲染 + 回忆面板 + 拆会话列表 | js2 features/store/ui/protocol 改造 | 刷新恢复尾巴；回忆面板可检索；无"新对话"入口 |
| **4 清理整理** | history 处置、物理搬目录、request_driven→performance 更名 | `routers/history.py` 处置、包移动 | 全量回归（含桌宠/小镇） |

依赖：1 与 2a-2d 并行；2 内部顺序 a→b→c→d；3 依赖 1+2d；4 收尾。
每个 Phase 独立可回滚（git 粒度），不留双轨开关。

## 12. 开放问题（默认值已给，可推翻）

1. 旧 `/api/history` JSON：只读存档保留、不导入记忆。
2. `pipeline`：保留字段、只接受 `request_driven`，其余 400。
3. legacy chat/react 端点：彻底移除。
4. 近期尾巴：50 事件或 24h。
5. notify SSE 与 create_ui：Phase 3 裁撤。
6. 迁移方式：逻辑归属优先，物理搬目录放 Phase 4。
7. beat 保鲜期：+6h。
8. 不在场策略：留存至保鲜期过期归档；bot/bark 触达开关默认关。
9. heartbeat/网格节奏：沿用现网。
10. 预跑深度：1 网格周期（≈2 beat）；预算 = 池深。
11. ProgressSync 频率：随演绎步即时推、200ms 去抖。
12. 缓存失效：导演在 StorySignal 后评估，显著偏离 upcoming 整卡重算。
13. **timeline 读模型（R-timeline 默认方案）**：`record_dialogue_turn` 附带写
    append-only 轮次流水（JSONL，按 channel 分文件），timeline v1 读流水；记忆
    单元级 timeline（语义层）后续另立。
14. 同 channel 多连接：维持现状单流（`try_start_streaming` 拒第二个），多窗口同
    步广播后续另立。

---

## 13. 实施状态与验收记录（2026-09-14，分支 `feat/single-stream-story`）

图例：✓ 已落地并验证 · ◐ 部分落地 · ✗ 未落地（诚实记账，非完成度装饰）

| 需求 | 状态 | 证据 / 缺口说明 |
|---|---|---|
| R1 移除会话列表/新对话/排序 | ✓ | 侧栏改回忆面板（`b5cb3fd`）；新对话按钮与排序条移除 |
| R1 history_store 停写转录 | ✓ | `saveConversation` 停 POST（保留 proactive 副作用）；delete/clear 存根 |
| R1 刷新恢复"近期尾巴"短窗缓存 | ✗ | 未做独立短窗；现状 onRebuild 读旧存档（停写后渐陈旧）。**下一批** |
| R2 timeline API + 回忆面板 | ✓ | `GET /api/memory/timeline` + `memory_recall.js`（分页/高显著标记） |
| R2 回忆关键词搜索 | ✗ | 仅时间轴分页；搜索待做 |
| R3 唯一 WS 接口 + pipeline 收敛 | ✓ | chat 路由退役（`88d18c0`）、react 路由退役（本批）、pipeline 仅 request_driven |
| R3 create_ui / notify SSE 裁撤 | ◐ | **保留**：js2 proactive 仍依赖 SSE notify；并入前端主动性改造批 |
| R4 session 在场化（不触发编剧初始化） | ✗ | `start_dialogue_session` 仍调 `ensure_screenwriter_init`——受 R6.1 牵连（见下） |
| R5 轮次记账 + timeline 流水 | ✓ | `record_dialogue_turn` 挂 journal（写失败不打断） |
| R5 beat 演出轮 provenance 记账 | ◐ | enqueue 路径未带 beat_id 记账；provenance 目前止于账本 |
| R6.1 导演/编剧常驻、删会话门控 | ◐ | **双轨现状**：life/story 常驻链已通（story-tick checklist + landmark→beat，`d953b47`/`3d63c8d`）；但 speak 内部旧导演/编剧机器仍在会话内运行，`ensure_screenwriter_init` 门控未删——删它需先完成 speak"决定说什么"路径退役（R6.3），是剩余工作的主战场 |
| R6.2 landmark→beat 剧情驱动 | ✓ | plan/trigger/surprise 三源挂钩，detail 带 story_beats 计数 |
| R6.4 协议 v1.2 四消息 | ✓ | storybus 契约 + 进程内总线（幂等/保鲜/五态回执） |
| R6.5 不在场留存（保鲜期内 held） | ✓ | 账本 held 态 + sweep 过期归档 |
| R7 角色自管开口（决策层） | ◐ | `BeatOpeningPolicy` 确定性规则版全量接入（perform/hold/silence）；CharacterRuntime 人格化收拢、预约梯子迁移未做 |
| R7 StorySignal → 导演失效 | ✓ | 轮末自动发信号；salience≥0.7 置 director_dirty（`0460e97`） |
| R8 卡片双段 + ProgressSync + WS 帧 + 前端就地刷新 | ✓ | StoryCardStore（大纲冻结）+ `story_card`/`story_progress` 帧 + marker 原位更新（`033622f`/`b5cb3fd`） |
| R9 演绎预跑缓存 | ✗ | director_dirty 失效钩子就位；prewarmer 未上移 life、无前瞻预跑 |
| R10 重启恢复 | ◐ | storybus 按设计无恢复职责 ✓；held beat 重启重投未实现（进程内态，重启即失） |
| §9 测试策略 | ◐ | 契约/决策/帧 26 项单测 ✓；桌宠客户端帧兼容回归未正式化 |
| Phase 4 history 只读化 | ✓ | POST/DELETE 移除，GET 留档（405 断言验证） |
| Phase 4 物理搬目录 | ✗ | directors/screenwriter/story_pool 仍在 speak/request_driven 下——先完成 R6.3 再搬，否则是搬空壳 |

**验收运行**（2026-09-14）：契约单测 26/26 绿；webui 全装配 TestClient 冒烟
（`/`、`/console`、timeline、history 只读 405、react 路由清零）；E2E 链路模拟
（landmark fill → beat → 角色决策 → performed 回执 → 开卡推进）通过。

**剩余工作清单（按依赖序）**：
1. R6.3：speak"决定说什么"路径退役（导演/编剧调用链改挂 life 常驻件）→ 随之删
   `ensure_screenwriter_init` 门控（补齐 R4/R6.1）；
2. R9：prewarmer 上移 `life/story/pool/`，按网格前瞻预跑（director_dirty 已是失效入口）；
3. R7 深水区：预约梯子/沉默阶梯收拢进 CharacterRuntime，人格化 BeatOpeningPolicy；
4. R1 短窗缓存（刷新恢复尾巴）+ R2 关键词搜索；
5. Phase 4 收官：物理搬目录 + react 相关 js2 设置页入口清理 + 桌宠帧兼容回归正式化。
