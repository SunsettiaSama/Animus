# 单窗口永续对话 + 剧情自主（记忆即历史 · life 出剧情 · 角色自管开口 · speak 只扮演）— 需求文档

- 状态：**已实施（部分）v7**（2026-09-14；v1 单窗口 → v2 导演编剧迁 life → v3 角色自管
  开口/卡片双段/预跑 → v4 缺口修补+分层定稿 → v5 实施与验收记录 → v6 独立验收
  对账 → v7 预约轴提前演化 + 编剧时间叙事 + 前端时间轴排布，见第 13 节）
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
| R1 移除会话列表/新对话/排序 | ✓ | v7 补充批次收口：`history_list.js` 删除（`#sidebar-list` 单写者=回忆面板，双写消除）、Landing"新对话"按钮与"最近对话"列表移除、`initHistoryLists` 装配摘除；`startNew` 仅作 boot 进入工作区的入口保留 |
| R1 history_store 停写转录 | ✓ | `saveConversation` 停 POST（保留 proactive 副作用）；delete/clear 存根 |
| R1 刷新恢复"近期尾巴"短窗缓存 | ✓ | v7：boot/startNew 拉 `/api/memory/timeline` 近 30 条回填（轮次纯文本气泡 + story 事件条混排）；失败静默不阻塞连接 |
| R1 前端时间轴排布（v7 新增） | ✓ | 日期分隔条（今天/昨天/M月D日）+ 剧情事件条（`timeline-story`，时间轴一等公民非气泡）+ `#msgs` 全部插入面挂分隔钩子；recall 面板 story 条目分支 |
| R2 timeline API + 回忆面板 | ✓ | `GET /api/memory/timeline` + `memory_recall.js`（分页/高显著标记） |
| R2 回忆关键词搜索 | ✗ | 仅时间轴分页；搜索待做 |
| R3 唯一 WS 接口 + pipeline 收敛 | ◐ | chat/react 路由退役（`88d18c0`/`5d0b30f`）✓；pipeline 收敛门已归位（v6 修复批次）：`/ws/agent/run`（js2 实连口）与 `/ws/speak/run` 共用 `webui/speak_pipeline_gate.py` 单点门，会话中途改 pipeline 亦复检，4 项回归锁定。"唯一对外"口径明确：前端经 Agent 顶层口（Speak/Worker 分类），speak 直连口供桌宠等客户端；create_ui/notify SSE 保留（并入前端主动性改造批），reset/page_enter/trace 待裁撤评估 |
| R3 create_ui / notify SSE 裁撤 | ◐ | **保留**：js2 proactive 仍依赖 SSE notify；并入前端主动性改造批 |
| R4 session 在场化（不触发编剧初始化） | ✓ | 同步门控已拆（`5d0b30f` 后批次）：`start_dialogue_session` 只恢复生命线；重连补推移除；实测 WS 连接 0.02s |
| R5 轮次记账 + timeline 流水 | ✓ | `record_dialogue_turn` 挂 journal（写失败不打断） |
| R5 beat 演出轮 provenance 记账 | ✓ | v7：performed ack → `append_event` 落 timeline 流水（kind=story，beat_id/card_id/landmark_id/occurred_at 随条目）——前端时间轴与回忆面板据此呈现 |
| R6.1 导演/编剧常驻、删会话门控 | ✓ | life/story 常驻链（story-tick checklist）；会话门控已拆。**旧编剧机器已本体级断供**（Screenwriter.init_presence 总阀，story_autonomy 开关默认开，ANIMUS_STORY_AUTONOMY=0 应急回滚） |
| R6.2 landmark→beat 剧情驱动 | ✓ | plan/trigger/surprise 三源挂钩，detail 带 story_beats 计数 |
| R6.3 speak"决定说什么"路径退役 | ✓ | **链路已拆除（v7 补充批次）**：story_autonomy 开关退役删除，四供能点改为结构性退役——编剧样张入口 `ensure_screenwriter_init` 永久 no-op（仅为旧编排器签名保留）、`_schedule_screenwriter_init`/预热回填删除、`arm_enter_greeting` 摘编剧调度、导演交接 `_on_director_character_handoff` 一律丢弃归档（`story_retired`）、Screenwriter.init_presence 总阀常闭返回空输出。物理目录搬移仍归 Phase 4；开场白承接待做 |
| R6.7 预约轴提前演化 + 编剧时间叙事（v7 新增） | ✓ | 导演/编剧挂在预约轴上为 agent 规划具体生活：story-tick 内演化过场（后台单飞）扫 `upcoming_landmarks(3600)` **提前 1h 走完 fill**（情节先发生，开口仍按预约时刻）；`LandmarkScreenwriter` 确定性整形（"HH:MM了。接着HH:MM那件事，……"时间明确 + 前情串联，llm_compose 缝留后续）；`EvolutionPool` 预跑池（池深即预算、到点零等待出货）；确定性 `beat-lm-<id>` 跨路径幂等（到点触发/提前演化/echo 重启恢复互斥不开两次口）；performed 落流水闭环 |
| R6.4 协议 v1.2 四消息 | ✓ | storybus 契约 + 进程内总线（幂等/保鲜/五态回执） |
| R6.5 不在场留存（保鲜期内 held） | ✓ | 账本 held 态 + sweep 过期归档；held 改期重投（`96caa69` `redeliver_held`，新 beat_id 原叙事溯源） |
| R7 角色自管开口（决策层） | ◐ | `BeatOpeningPolicy` 确定性规则版全量接入（perform/hold/silence）；**决策件已迁 `speak/performance` 旁路管线**（policy/FrameGate/CharacterMemoryBuffer，v7 补充批次），wiring 桥退位为投递适配；CharacterRuntime 人格化收拢、交互账本/节奏阶梯迁移未做（R7 深水区） |
| speak/performance 旁路管线（v7 补充新增） | ✓ | 新包 `speak/performance/`：`policy`（开口决策+帧闸，自 request_driven/character 迁入）+ `buffer`（角色记忆缓冲迁入）+ `performer`（**BeatPerformer 旁路引擎**：beat → 决策 → 帧闸 → 表演端口 → 逐渠道 ack，全部构造注入可整体 fake）；表演端口 = `enqueue_agent_outbound`（OutboundManager → bus 纯运输）；5 项管线契约测试锁定 |
| 时间轴窗口上下文（v7 补充新增） | ✓ | **上下文唯一历史语义**：注入上下文 = 沿时间轴最近 K 条（轮次+剧情事件混排，`timeline.py:recent_window` + `format_window_lines`，K=20），**与轮次机制无关**；经 `speak.inject_timeline_window` 走 page_temp/compose 既有注入缝（页 key 固定 `timeline-window`，同代替换不累积）；刷新点 = 进房（`start_dialogue_session`）+ 轮末记账（`soul_dialogue.record_pending_turn`）；剧情事件带剧情时戳注入（`[HH:MM] ◐ …`），与时间轴呈现同构 |
| timeline 分段缓存文件（v7 补充新增） | ✓ | **按条数分段落盘（1k 条/段，硬编码可调）**：段文件 `<channel>.<序号>.jsonl` 零填滚动，旧版单文件兼容读；前端 timeline API 与 speak 注入同读此文件——**web 与本地文件天然对齐，聊天触发时双方都优先从本地文件注入** |
| life→speak 握手协议（v7 补充新增） | ✓ | 先确认再通信（不等待、不全量）：`speak.story_gate_open()` 两个硬条件——① speak 服务已打开且有激活会话（`has_active_dialogue`）；② 30 分钟无唤醒即睡眠（`_SPEAK_SLEEP_AFTER_SEC` 硬编码，可调）。唤醒点 = 进房/发言/输入脉冲（`mark_speak_wake` 三处）；门关闭 → performer HOLD → life 账本 held（不在场留存），唤醒后改期重投续演 |
| 剧情意向不置顶（v7 补充新增） | ✓ | beat 被抑制/沉默时落 `story_intent` 流水（"她打算开始：…"，按 landmark 去重防重投重复）并刷新 speak 窗口——聊天进行中进入剧情**不打断、卡片不置顶**，只让角色知道她打算做什么，开口时机角色自决；前端时间轴/回忆面板以"意向"标签区分（▷） |
| presence 待分享压入（v7 补充新增） | ✓ | 进房时 life **无在途事件**（ledger pending/held 空 + 预跑池空）→ `presence.pop_top_share_intents(limit=2)` 弹出近期期望分享内容，作为 extra lines 随时间轴窗口一并注入上下文；有在途事件则不注入（剧情链即将压入） |
| R7 StorySignal → 导演失效 | ◐ | 轮末自动发信号机制在位（`0460e97`）；但生产调用点（`soul_dialogue.py:46-50`）不传 `salience_hint`，恒默认 0.3 < 0.7——director_dirty 在真实轮次为**死分支**（仅单测传 0.9 可达）。v6 验收降级 |
| R8 卡片双段 + ProgressSync + WS 帧 + 前端就地刷新 | ✓ | StoryCardStore（大纲冻结）+ `story_card`/`story_progress` 帧 + marker 原位更新（`033622f`/`b5cb3fd`） |
| R9 演绎预跑缓存 | ◐ | **预约轴版已落地**（v7）：T-1h 演化入池、到点出货零 LLM 等待、director_dirty 整池失效重估、echo 路径零成本重出稿（重启丢池自愈）；仍缺：网格前瞻预跑（≈2 beat）、speak 旧 prewarmer 上移 `life/story/pool/`（物理归 Phase 4）、缓存命中率可观测 |
| R10 重启恢复 | ◐ | storybus 按设计无恢复职责 ✓；held beat 重启重投未实现（进程内态，重启即失） |
| §9 测试策略 | ◐ | storybus 八文件 **61/61 绿**（v7 补充回归批：真 SpeakService 装配的握手门 3 项——唤醒/激活/30min 睡眠边界、时间轴窗口注入 3 项——混排行/同代替换/空窗、跨段分页 1 项、意向刷新 1 项）；桌宠客户端帧兼容回归未正式化 |
| §5.3/5.4 依赖与组装规则 | ◐ | 无违禁 import（speak↛life/story、storybus 零依赖、webui 不入 life 内部）✓；§5.4 未按字面：`_ensure_story_service` 返回 None，改 `wiring.ensure_story_runtime` 懒挂（heartbeat/adapters 首次触发，无启动序装配）——"service 零改动、增量为零"两条达成；§5.3 规则表未列 heartbeat/adapters → wiring 依赖，应补记 |
| Phase 4 history 只读化 | ✓ | POST/DELETE 移除，GET 留档（405 断言验证） |
| Phase 4 物理搬目录 | ✗ | directors/screenwriter/story_pool 仍在 speak/request_driven 下；R6.3 断供已完成（`96caa69`），搬迁前置条件（不搬空壳）就绪 |

**验收运行**（2026-09-14）：契约单测 26/26 绿；webui 全装配 TestClient 冒烟
（`/`、`/console`、timeline、history 只读 405、react 路由清零）；E2E 链路模拟
（landmark fill → beat → 角色决策 → performed 回执 → 开卡推进）通过。
v6 对账重跑 storybus 全量 **32/32 绿**（含回归 6 用例）。

**真实服务实测**（2026-09-14，`python src/run.py --port 8310`，LLM=MiniMax-M3
远程）：五阶段全绿、无浏览器连接时 `speak_initialized=True`（常驻成立）；
WS `session_open` → 真实对话轮（outline/speak/agent_typing/finish →
turn_finish 回答正常），连接耗时 0.02s（门控拆除生效）；编剧 LLM 在轮次
完成后才后台跑完（`screenwriter_outline` 日志，热路径无阻塞）；该轮已落
`/api/memory/timeline`（时间轴记账闭环）。

**回归与实测补充**（2026-09-14 晚）：
- 回归用例 `test_proactivity_regression.py`（6 项）：时间帧单开口不变量
  （FrameGate 同帧第二拍拒绝/跨渠道独立/下一帧恢复）、帧内收敛（任何批次
  后无 pending 悬案）、主动会话 payload 契约、预约改期（held→下一拍重投→
  performed，旧条目终态归档）、断供开关默认值与应急通道；
- 真实链路实测（8310，本体阀版）：**旧编剧产出全日志 0 条**
  （screenwriter_outline/opening/units/pool-full 均无）；静默在场 90s 无
  server_initiated 轮；用户即时回应正常带人格（时间轴落
  "在呢，刚把屏幕点亮。怎么了，是不是跑图跑累了？"）；
- **已知取舍**：开场旁白（enter opening）随编剧断供不再生成——开场问候
  待角色侧 greeting 路径或 life beat 承接（列入剩余清单 1）。

**独立验收对账**（v6，2026-09-14，@`96caa69`，§13 全表逐项核对代码现状）：
- 方法：每行声明取文件:行号级证据；storybus 单测重跑；前端/路由与后端分两路
  系统性核查（含违禁 import 全量 grep）。
- 状态修正 3 行：R1 会话列表 ✓→◐（侧栏双写）、R3 唯一 WS ✓→◐（实连口无门）、
  R7 StorySignal ✓→◐（salience 死分支）；§9 计数 26→32。
- 补记未披露缺口：① `#sidebar-list` 双写——`memory_recall.js:54` 与
  `history_list.js:64` 同容器，boot 序必触发 `historyChanged` 覆盖回忆面板；
  ② pipeline 收敛门落在前端不使用的 `/ws/speak/run`，js2 实连 `/ws/agent/run`
  （`routers/agent.py` 读 pipeline 不校验）——**已于同日修复，见下**；
  ③ 生产 StorySignal 恒默认
  salience 0.3（`wiring/story.py:485`），≥0.7 失效判定生产不可达。

**v6 修复批次**（2026-09-14，前端→speak 路由收敛）：
- 新增 `webui/speak_pipeline_gate.py`：pipeline 收敛门单点实现（唯一合法值
  `request_driven`）；
- `/ws/agent/run` session_open 加门（js2 实连口此前无校验；门在 soul 解析前，
  纯协议检查）；
- `/ws/speak/run` 会话中途 pipeline 字段补复检（原为裸赋值可绕过收敛）；
- js2 `http_api.js` WS_PATHS 注释正名：speakRun 非 legacy（桌宠等直连客户端
  在用），两口同门；agentRun 为单窗口实连口（Speak/Worker 分类）；
- 回归 `test_speak_pipeline_gate.py` 4 项：门单测 + 两口 TestClient WS
  （非法拒绝先于 soul 解析、合法穿透至 Soul 检查）；webui+storybus 合跑
  75 项 74 绿——`test_speak_delivery_hub` 存量失败 1 项与本批无关
  （stash 后 HEAD 同样失败）；现有客户端零误伤（桌宠/`speak_ws.py`/js2
  均默认 `request_driven`）。

**v7 批次**（2026-09-14，导演/编剧挂预约轴 + 时间轴呈现）：
- 需求口径：导演/编剧在 **agent 预约的 landmark 进行时**规划具体生活；与
  heartbeat 上既有预约（landmark 预约轴 `scheduled_at` + story-tick）联合
  实现；**提前 1 小时演化**避免用户侧延迟；编剧必须**说明白什么时间发生
  了什么、并串起前情**；前端按**时间轴**排布（不再只是逐轮 transcript）。
- 后端：`life/story/writer.py`（LandmarkScreenwriter）、`life/story/pool.py`
  （EvolutionPool 预跑池）、`life/manager.py`（`evolve_upcoming_landmarks`
  提前走完 fill / `done_landmarks_for_tell` echo 素材）、`service.py` 两
  offload 口、`wiring/story.py`（story-tick 内演化过场单飞 + `_on_advance`
  performed 落流水 + 卡片预告同步 + 确定性 `beat-lm-<id>`）、storybus
  （BeatDraft 可选 beat_id）、`memory/timeline.py`（`append_event` 事件条目，
  轮次/事件同流混排）。
- 前端：`ui/chat/timeline.js`（日期分隔 + 剧情事件条）、bubbles/speak_stream
  全插入面挂分隔钩子、conversation 启动时 timeline 尾巴回填（`startNew` →
  `onTimelineRestore`）、recall 面板 story 分支、main.css 时间轴样式区。
- 验证：storybus 40/40（含新 8 项）；webui 42/43（1 项存量失败与本批无关
  ——stash 对比 HEAD 同样失败）；js2 全部改动文件 `node --check` 通过；
  soul+life 大套件 36 失败/32 收集错误经 stash 对比**与本批零差异**
  （HEAD 存量：`orchestrator.guidance` 模块缺失引发的收集污染，另有
  screenwriter/compose 等存量失败——R6.3 断供后旧机器测试自然失效，应随
  Phase 4 物理搬迁一并清理）。

**v7 补充批次**（2026-09-14，speak 侧：旁路管线 + 旧链路拆除）：
- 新建 `speak/performance/` 旁路表演管线（对应 storybus 新设计过程）：
  `policy`（BeatOpeningPolicy/FrameGate/OpeningDecision，自
  `request_driven/character/beat_policy.py` 迁入）+ `buffer`
  （CharacterMemoryBuffer，自 character 迁入）+ `performer`
  （BeatPerformer 引擎——决策/帧闸/表演端口/回执口全部构造注入，
  wiring 的 SpeakBeatInboxBridge 退位为投递适配）；
- 旧链路取消：story_autonomy 开关模块删除（无双轨），四供能点结构性
  退役（详见 R6.3 行）；`character` 包旧位置两文件删除，runtime/包出口
  改引 performance；
- 边界记账：`interaction.py`（交互账本）与 `directors/rhythm_schedule.py`
  （节奏阶梯）与旧对话提示词路径深度交织，**不迁**（R7 深水区随
  CharacterRuntime 人格化一并收拢）；CharacterRuntime 本体仍留旧包
  （对话轮生成主路径，Phase 4 随包搬迁）；
- 验证：storybus 45/45（新增 5 项管线契约）；storybus+webui 合跑 87 绿；
  soul+life 大套件 36 失败集与 HEAD stash 对比**逐项一致（零新增回归）**。

**v7 补充批次（续）**（2026-09-14，web 门面收口 + 时间轴窗口上下文）：
- 门面：`history_list.js` 删除——`#sidebar-list` 单写者=回忆面板（双写
  隐患消除）；Landing"新对话"大按钮与"最近对话"列表移除（区块改"工具
  直达"）；`initHistoryLists`/`bindLanding` CTA/`historyListSafeSnapshot`
  装配面全部摘除；`conversation.startNew` 仅保留 boot 进工作区职能；
- 上下文语义：**有且仅有沿时间轴的最近 K 条注入上下文，与轮次无关**
  （实现见"时间轴窗口上下文"行）；
- 验证：storybus 49/49；soul+life 大套件失败集与 HEAD 对比逐项一致
  （零新增回归）；js2 改动 `node --check` 通过；门面静态验证——
  `#sidebar-list` 全仓单写者。

**v7 补充批次（续 2）**（2026-09-15，缓存文件化 + 握手协议 + 剧情意向）：
- timeline 分段缓存：按条数 1k/段落盘（滚动 + 旧文件兼容读）——web 与
  本地文件对齐，聊天触发时前端（timeline API 尾巴恢复）与 speak（窗口
  注入）都优先从本地文件读；
- 握手协议：`story_gate_open` 两个硬条件（speak 激活 + 30min 无唤醒睡眠，
  硬编码），performer 决策接入；门关不等待——beat 入账本 held，唤醒后
  改期重投（复用 R6.5/R7.2 机制）；
- 剧情意向不置顶：hold/silence beat → `story_intent` 流水（landmark 去重）
  + 窗口刷新——聊一半进剧情不打断，"她打算开始做什么"进上下文，开口
  时机角色自决；
- presence 待分享：进房无在途事件时弹 2 条期望分享压入上下文（有事件则
  让位剧情链）；
- 初始化对齐确认：进房初始化已全部来自新链路（时间轴窗口 + life 在途
  事件 + presence 待分享）；旧编剧/导演初始化已在前批拆除（init_presence
  常闭、交接丢弃），剩余 DirectorCoordinator/OrchestratorThread 构造体
  随 Phase 4 物理搬迁移除；
- 验证：storybus 54/54；soul+life 大套件失败集与 HEAD 对比逐项一致
  （零新增回归）。
- 记账偏差（非缺口）：§5.4 懒挂替代启动序装配（见上表）；R8 前端帧经 kind
  透传实现（`workspace.js` 路由），`protocol/frames.js` 字面未扩展（其为出站
  构造器，不涉下行）；R1 刷新现状实为 `startNew` 清空消息区——比 v5 所记
  "读旧存档"更空（onRebuild 仅点历史项/proactive 开窗触发）。
- 工作区无关物：`src/evals/memory_humaneness` 基准（其 README 自述属
  `eval/memory-pipeline-split` 分支职能）与 `demos/metroidvania/` 为独立
  工作流未提交物，不计入本需求验收，建议分离处置。

**剩余工作清单（按依赖序，v7 修订）**：
1. R6.3 收尾：开场白承接（角色 greeting / life beat——编剧链路已拆除，
   enter opening 不再生成）；
2. R7 深水区：交互账本（`character/interaction.py`）与节奏阶梯
   （`directors/rhythm_schedule.py`）迁入 performance 并收拢进
   CharacterRuntime，人格化 BeatOpeningPolicy；生产 StorySignal 带轮末
   真实 salience（≥0.7 失效判定目前生产不可达——v7 的整池重估同受此限）；
3. R9 收尾：网格前瞻预跑（≈2 beat）、speak 旧 prewarmer 上移
   `life/story/pool/`、编剧 `llm_compose` 缝接 LLM 润色、演化/命中率可观测；
4. R3 收尾：create_ui/notify SSE 裁撤（前端主动性改造批）+
   reset/page_enter/trace 伴随端点处置评估；
5. R2 关键词搜索 + 前端时间轴深化（小时段分组、story 条目就地展开、
   beat 元数据帧归组）；
6. Phase 4 收官：物理搬目录（request_driven 剧情机器 → life/story，
   performance 旁路管线已是新落点）+ react 相关 js2 设置页入口清理 +
   桌宠帧兼容回归正式化 + 清理 HEAD 存量红测试
   （`orchestrator.guidance` 收集污染、screenwriter/compose 断供后失效用例、
   `test_speak_delivery_hub` 离线持久化失败）。
