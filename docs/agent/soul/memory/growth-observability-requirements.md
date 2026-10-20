# 记忆系统成长性观测与生产接线需求（对齐稿）

> 状态：**Phase 1–4 已实施（2026-09-25）**——R1–R6 全量落地，R5 回归锁 36 测试全绿；
> 交付物与运行方式见文末"实施状态"节。D1–D7 决策点仍待逐条拍板（实现按文档建议档位）。
> 背景：2026-09 记忆系统全面调研（架构 / 检索链路 / 评测体系），
> 事实依据见 `docs/agent/soul/memory/memory-benchmark-report.md` 与本文第一节的问题清单。
> 目标一句话：**把记忆系统接入真实生产管线的观测闭环，让"成长性"从架构声明变成可测量的事实。**

---

## 一、背景：调研发现的问题清单

下列编号（P1–P6）在后续需求中反复引用。

| # | 问题 | 证据 | 后果 |
|---|---|---|---|
| P1 | 生产检索链路零埋点 | `retriever.py` / `graph/query.py` / `emergence/spread/service.py` / `facade/service.py` 全链路无日志、无指标 | "线上命中如何"无法回答 |
| P2 | growth 引擎生产未接线 | `src/infra/retrieval/__init__.py` 的 `get_default_rewriter()` 纯内存模板、不落盘、不接 LLM；`report()` 在生产零调用（docstring 自述"生产命中反馈接入是后续步骤"） | 模板自进化闭环断裂，`config/infra/retrieval.yaml` 的 growth 组是死配置 |
| P3 | 擢升门不可观测 | `unit_layer/promote/policy.py:29` 仅认 agent 显式标注；无入图率统计 | 对话次数 → 图规模的映射完全不可知，可能长期不增长而不被发现 |
| P4 | tier 层级迁移是死代码 | `base_node.py:69 promote_to_long()` 全仓无调用方 | short 层单调膨胀风险，且无数据证实或证伪 |
| P5 | 默认后端无向量基建 | JSON 后端默认构造 `enabled=False` 的 MemoryInfraService（`facade/build.py`） | 归档选父退化为最近节点列表、episode 跨场景连边失效、semantic/hybrid 缺向量增强——语义边长不出来 |
| P6 | 无真实案例与长程验证 | 全部实验 ≤12 条记忆/例、人工合成数据集、无生产 telemetry（benchmark 报告第六节自认） | "能否长成复杂记忆网络"停留在设计推断 |

**本需求只解决 P1/P2/P3 的观测与接线，以及 P6 的验证手段；P4（tier 迁移机制）与 P5（向量基建启用）记录为观测对象但不改造，见"非目标"。**

---

## 二、术语与语义对齐

实施前必须对齐的核心定义。**这一节是本文档的对齐重点，任何一条不同意都请在评审时指出。**

### 2.1 "成长"的五个维度

"记忆系统能成长" 不是单一命题，拆成五个可分别测量的维度：

| 维度 | 定义 | 主要观测量 |
|---|---|---|
| G1 规模成长 | 节点数、边数随对话量单调上升 | 节点/边计数曲线（按 network、node_type、edge_type、tier 分桶） |
| G2 结构成长 | 网络变密而不仅是变大 | 边/节点比、平均度、孤儿节点率、选父率 vs 自立率、跨 episode 连边数 |
| G3 强度成长 | 被用进废退（激活公式的回忆增强项） | recall_count / rehearsal_count 分布随时间演化、同一节点被跨会话再次命中的比例 |
| G4 重构成长 | 旧记忆被改写、合并、编织 | 反刍改写次数、反刍新增边数、collision 折叠次数、叙事编织边数 |
| G5 衰减/遗忘 | 冗余被修剪 | 软删除数、遗忘速率（存活曲线）、高 recall 节点的幸存率 |

**"长成复杂记忆网络"的可操作判据 = G1 与 G2 同时为正**（只有 G1 为正是"堆日志"，不是"长网络"）。

### 2.2 "命中"的四个层级（生产 vs 离线的关键区别）

离线评测的 Hit@k 有 ground truth 锚点；生产查询没有。生产命中必须分层定义：

| 层级 | 名称 | 判定 | 可得性 |
|---|---|---|---|
| H1 | 召回（yield） | 检索返回非空 | 确定性，埋点即得 |
| H2 | 采纳（injection） | 结果通过 budget/去重门槛，实际注入 Speak 上下文 | 确定性，注入侧埋点 |
| H3 | 引用（usage） | 模型回复内容实际使用了该记忆 | 需采样 LLM 判定（成本项，默认不做，见 D2） |
| H4 | 图路命中（graph-path hit） | rewriter 产出的 entities 命中种子 / 束搜索经边触达新节点 | 确定性，即 growth `report()` 的 `HitSignal` 语义 |

**口径声明：默认报表中的"生产命中率"= H2 采纳率（H1 作分母时称召回率）；H3 仅采样研究用；H4 专属于 growth 模板统计，不与 H1/H2 混算。**

### 2.3 擢升漏斗（入图率的精确语义）

```text
F1 体验单元产生（按 source: dialogue / compression / collision / narrative / surprise / ...）
F2 agent 显式标注 promote_to_memory（annotation_decided=True）
F3 擢升提交（submit_experience，经 sleep filter 后）
F4 入图成功（LLM 路由 event/social，节点落库）
F5 建边（ExperienceArchiver 选父成功 vs 自立；社交邻域合并）
F6 首次 recall（节点被任何检索触达）
F7 跨会话再命中（G3 的核心证据）
```

"入图率"默认指 **F4/F1**；漏斗各级转化率全部入库，瓶颈定位靠逐级比值。

### 2.4 观测不改变行为原则（passive telemetry）

所有埋点必须满足：同步开销趋近于零（内存队列 + 异步落盘）、写入失败静默降级（不炸主链路）、**关闭开关后检索与写入结果与现状逐位一致**（回归测试锁定，见 R5.1）。观测系统 bug 的最坏后果是丢观测数据，不允许是丢记忆或改变检索排序。

---

## 三、目标与非目标

### 目标

1. **生产管线接入**：growth 反馈闭环在生产真正接通（统计先行，LLM 造模板分级开关控制）。
2. **成长可观测**：记忆全生命周期事件流水 + 快照/报表，G1–G5 五维度、F1–F7 漏斗、H1/H2/H4 命中全部可从数据直接回答。
3. **回归保护**：观测与接线不改变现有行为，有确定性测试锁。
4. **真实案例验证**：用真实形态的会话驱动**完整生产管线**（非评测基座），产出一份"设计合理性判定报告"。

### 非目标（明确排除，防止范围蔓延）

- 不改记忆数据模型、检索算法、打分权重（观测对象，不是改造对象）；
- 不实现 short→long tier 迁移（P4）——只观测 tier 分布暴露问题，机制另立需求；
- 不负责启用/搭建向量基建（P5）——观测需区分"有向量/无向量"两种形态并分别报告，但基建启用是部署决策；
- 不做 WebUI 可视化（默认产出文件 + CLI 报表；是否上 UI 见 D5）；
- 不动 `src/evals/` 评测基座（生产观测与离线评测是两套口径，禁止混用）。

---

## 四、需求分解

### R1 记忆生命周期事件流水（MemoryTelemetry）

**现状**：生命周期动作散落在 memory worker、心跳、sleep 等异步路径，事后无法重建"什么时候发生了什么"。

**需求**：

- R1.1 统一事件类型（首版清单，允许实施中增补但需同步更新本文档）：

| 事件 | 触发点（预计触点） | 关键字段 |
|---|---|---|
| `unit_created` | `unit_layer/manage/log.py` 热日志写入 | source、salience、annotation 状态 |
| `unit_annotated` | promote 判定处（`promote/policy.py`） | 是否标注、决策来源 |
| `promote_submitted` | `promote/dispatch.py` → `io/life/gateway.py` | unit_id、filter 结果 |
| `node_created` | `graph/node/create/experience.py`、`archive.py` | network、node_type、tier、parent_node_id（自立时为空） |
| `edge_added` | archive 选父、episode 子图、叙事编织、反刍、社交合并 | edge_type、from/to、来源路径 |
| `recall_recorded` | `node/maintain/recall.py`（record_recall_batch） | node_id 批、触发入口 |
| `rumination_rewrite` | `rumination/writer.py` | 改写节点、新增边数 |
| `collapse` | `unit_layer/manage/collapser.py` | 参与单元、新 unit_id |
| `node_forgotten` | `node/maintain/forget.py` | node_id、当时 activation |
| `compression_block` | `hub/stack.py ingest_compression_block` | 产出的 unit 数 |
| `session_closed` | `dialogue/pipeline.py close_dialogue` | 轮数、终局单元数 |

- R1.2 存储：append-only JSONL，**复用 `HeartbeatTickLog` 的既有模式**（线程锁、单代轮转、坏行容忍、尾部读，`heartbeat/tick_log.py` 已验证）；路径 `.react/telemetry/memory_events.jsonl`，单代上限默认 5MB。
- R1.3 写入侧：进程内单队列、后台单线程消费（挂 `SoulWorkers` 或独立轻线程，实施时定）；队列满丢弃最旧事件并计数，**永不阻塞调用方**。
- R1.4 配置：`soul memory telemetry` 配置组（enabled 默认 true、目录、轮转上限）；关闭时零事件产生、零对象构造。

**验收**：跑一段包含"对话写入→擢升→检索→心跳反刍→sleep 遗忘"的完整流程后，事件流水可完整重放上述顺序，无缺类型、无乱序因果（ts 单调）。

### R2 成长快照与报表（GrowthSnapshot）

**现状**：图的规模/密度只能临时写脚本查 store，没有时间序列。

**需求**：

- R2.1 每日快照（挂在现有 sleep 流程末尾，`sleep/service.py`）：节点数（network × node_type × tier）、边数（edge_type）、边/节点比、平均度、孤儿率、recall_count / rehearsal_count 分布分位数、tier 分布、**当前向量基建形态（有/无 embedding）**——P5 要求两种形态的数字必须可区分。
- R2.2 快照存储：`.react/telemetry/snapshots/` 按日 JSON；快照以 store 实际状态为准（防事件流水与真实状态漂移，见风险 3）。
- R2.3 报表生成：CLI 脚本（`scripts/memory_growth_report.py`）从事件流水 + 快照重建任意时间窗的 G1–G5 曲线与 F1–F7 漏斗，输出 `results/memory_growth/<run>/report.md` + `metrics.json`（产物格式对齐 `results/` 既有约定）。

**验收**：对同一段回放，报表能直接回答：入图率（F4/F1）、选父率（F5 建边中非自立占比）、边/节点比变化方向、被跨会话再次命中的节点数（F7）、遗忘数与幸存者 recall 分布。

### R3 生产检索埋点（命中观测，P1）

**现状**：三条生产检索入口 + recall 全部无观测。

**需求**：

- R3.1 覆盖入口（全部走 R1 的异步通道，同一事件类型 `retrieval_performed`）：

| 入口 | 触点 |
|---|---|
| A 工具检索 | `adapters/soul_tao/tools/memory_search.py` → `facade/service.py search` |
| B Speak 点查询 | `emergence/spread/service.py _run_point_query` |
| C compose 检索 | `speak/responders/request_driven/composer/domain/retrieve.py` |
| D recall / recall_social | `facade/service.py` 对应方法 |

- R3.2 事件字段：入口标识、query 原文、rewriter 改写结果（query/entities/命中的 template_id/是否 fallback）、各路召回明细（precise / beam_walk / associative / wander 各自条数与 top 分数）、最终 top-k 的 node_id 与分数、耗时 ms。
- R3.3 采纳信号：注入 Speak 上下文的记忆行数（budget 门槛前后对比），即 H2 的直接数据源。
- R3.4 不采集：不记向量本体、不外发任何数据（query 原文仅落本地 `.react`，见风险 2）。

**验收**：任取一次生产对话，能在事件流水中找到该轮 B/C/D 事件，且字段足以离线复算当轮的 H1（非空）与 H2（注入数）。

### R4 growth 引擎生产接线（P2）

**现状**：`get_default_rewriter()` 纯内存、无反馈；growth 的统计/退役/造模板三段全部休眠。

**需求**：

- R4.1 统计先行：生产 rewriter 构造改为带 `GrowthEngine`（stats 落盘 `.react/retrieval/growth_stats.json`，复用既有持久化），`report()` 在入口 B 的点查询完成后回调（hits 语义 = H4 图路命中：种子命中 + 束搜索经边触达的节点，映射为 `HitSignal(id, score)`）。
- R4.2 分级开关：统计（`growth.enabled`）与 LLM 造模板（`growth.authoring_enabled`）**解耦为两档**；生产默认仅开统计，authoring 默认关（现状配置两者默认 true，接线时改为"统计开、authoring 关"，是否放开见 D4）。
- R4.3 退役闭环：统计样本足够后允许 builtin 之外模板自然退役（既有逻辑，无需新开发，只随接线激活）。
- R4.4 失败安全边界不变：growth 任何异常不外溢检索主链路（既有 try/except 语义保持，回归测试锁定）。

**验收**：生产运行一段时间后 `growth_stats.json` 中各模板的 uses/hit_count 持续累积且按模板分化（不同 template_id 的均分可比较）；关闭 authoring 时无 LLM 调用产生。

### R5 回归测试

**需求**（与 R1–R4 同步交付，测试位置对齐 `src/test/memory/`、`src/test/infra/retrieval/` 既有风格）：

- R5.1 行为不变锁：telemetry 全开与全关两种形态下，同一输入的检索结果（node_id 序列 + 分数）逐位一致——参照 `test_rewriter_ablation.py` 的 off 臂逐位对比手法。
- R5.2 事件完备性：对 2.3 漏斗的每一级，用伪造 store/worker 断言"动作发生 ⇒ 对应事件入队且字段正确"。
- R5.3 故障容忍：telemetry 落盘路径不可写时，检索与记忆写入功能不受影响（进程不抛错、结果正确）。
- R5.4 漏斗一致性：报表脚本从事件流水重放的计数 == 直接查 store 的计数（抽样对账）。
- R5.5 growth 接线锁：`get_default_rewriter()` 带 growth 统计、无 authoring LLM；`report()` 异常不影响检索返回（扩展 `src/test/infra/retrieval/` 既有 46 测）。

### R6 真实案例运行（设计合理性验证，P6）

**需求**：

- R6.1 回放框架：一个驱动器把多轮会话灌入**完整生产管线**（真实 SoulService 装配：Memory worker、心跳、sleep、擢升、Speak compose——不是 evals 的基座替身），同时采集 R1–R3 全量观测。**两种回放模式**：
  - **模式 甲（有 ground truth）**：用可控剧本（先用 `evals/.../dialogue/data/scenarios.jsonl` 30 剧本，或对齐后另建），在剧本中埋"后续轮应想起第 N 轮记忆"的检查点——这样**生产形态下也能算真 Hit@k**，打通离线口径（2.2）与生产口径。
  - **模式 乙（真实会话）**：回放真实用户会话记录（数据源见 D3），无 ground truth，产出 H1/H2 观测与 G1–G5 曲线。
- R6.2 判定问题清单（"设计是否合理"就等于能否回答这组问题，全部来自报表而非人工翻数据）：

| # | 问题 | 对应观测 |
|---|---|---|
| Q1 | 擢升漏斗哪一级是瓶颈？各级转化率是否 > 0？ | F1–F5 |
| Q2 | 随轮数增加，网络是变密还是只变大？ | G2（边/节点比趋势） |
| Q3 | "用进废退"真的发生吗？ | G3（recall_count 增长、跨会话再命中） |
| Q4 | 会话写入的记忆，后续会话想得起来吗？ | 模式甲的跨会话 Hit@k（F6/F7） |
| Q5 | 遗忘速率合理吗（7 天半衰期下存活曲线）？ | G5 |
| Q6 | 记忆库规模处于 E3 剂量安全区吗（干扰 ≤8）？ | 快照节点规模 |
| Q7 | tier 分布是否单调膨胀（P4 的实证）？ | 快照 tier 分布 |
| Q8 | 模板统计是否分化、有无模板该退役？ | growth_stats |

- R6.3 产出：一份"设计合理性判定报告"（`results/memory_growth/<run>/report.md`），Q1–Q8 逐条给出数字结论。

**验收**：模式甲完整跑通 30 剧本 × 若干会话，报告自动生成，Q1–Q8 无"数据缺失"项。

---

## 五、实施阶段（每阶段可独立验收、独立回滚）

| 阶段 | 内容 | 依赖 |
|---|---|---|
| Phase 1 | R1 事件流水 + R2 快照/报表（纯旁路观测，风险最低） | 无 |
| Phase 2 | R3 检索埋点 + R4 growth 接线 | Phase 1 的异步通道 |
| Phase 3 | R5 回归锁（实际与 Phase 1/2 同步编写，此阶段收口全量跑） | Phase 1/2 |
| Phase 4 | R6 回放框架 + 模式甲跑通 + 判定报告 | Phase 1–3 |
| Phase 5（可选） | 模式乙真实会话回放 | D3 数据源落实 |

---

## 六、待对齐决策点（执行前需要拍板）

| # | 决策 | 选项与建议 |
|---|---|---|
| D1 | 生产"命中率"的默认口径 | 建议 H2 采纳率；H1 作分母口径并存 |
| D2 | H3 引用信号（LLM 采样判定回复是否用到记忆）是否做 | 有 API 成本；建议首版不做，模式甲里用 ground truth 替代 |
| D3 | 模式乙的真实会话数据源 | a) 现有 `.react` 内会话记录导出 b) 人工提供对话语料 c) 外部数据集（LoCoMo 类）翻译。需指定 |
| D4 | growth 的 authoring（LLM 造模板）生产默认档位 | 建议先关，统计跑两周看分化再开 |
| D5 | 观测呈现形态 | 建议先文件 + CLI 报表；WebUI 面板另立需求 |
| D6 | P4（tier 迁移）/ P5（向量基建）是否趁接线一并处理 | 建议不并：本需求保持纯观测，避免"改机制"与"上观测"混淆归因 |
| D7 | 事件流水保留策略 | 建议单代 5MB × 2 代 + 快照永久；是否要更久 |

---

## 七、风险与边界

1. **热路径性能**：入口 B（Speak 点查询）在每轮对话关键路径上。埋点只允许"构造 dict + 入队"，落盘全部异步；回归测试含耗时断言（同步附加 < 1ms 量级）。
2. **隐私**：query 原文与记忆内容进本地事件流水（`.react/telemetry/`），无外发；但文件含对话内容，保留策略（D7）需用户知情。
3. **流水与图状态漂移**：事件流水是增量视角，进程崩溃/多进程写可能漂移；对账以 R2.1 快照（直接查 store）为准，报表交叉校验（R5.4）。
4. **观测悖论**：recall 埋点本身会因 record_recall_batch 改变节点强度——埋点必须放在"记录强化"这一既有动作之后、且不额外触发强化，保证观测不注入反馈（R5.1 的逐位一致锁覆盖此点）。
5. **与离线评测口径混用**：生产 H1/H2 与离线 Hit@k 不是同一量纲（2.2 已声明），文档与报表必须显式标注口径，禁止直接横向比数。

---

## 八、预计触点清单（实施前的地图，非最终范围）

```text
新增  src/agent/soul/memory/telemetry/          事件流水 + 快照（对齐 heartbeat/tick_log 模式）
新增  scripts/memory_growth_report.py            报表 CLI
新增  src/test/memory/telemetry/                 R5 测试
改动  src/agent/soul/memory/facade/build.py      装配 telemetry（含 enabled=False 直通）
改动  src/agent/soul/memory/facade/service.py    入口 A/D 埋点
改动  src/agent/soul/memory/emergence/spread/service.py   入口 B 埋点 + report() 回调
改动  src/agent/soul/speak/.../composer/domain/retrieve.py 入口 C 埋点
改动  src/infra/retrieval/__init__.py            get_default_rewriter 接 growth 统计
改动  config/soul/memory/service.yaml + config/infra/retrieval.yaml   telemetry / growth 分级开关
改动  各生命周期触发点（R1.1 表）                 发事件
```

---

## 九、整体验收（"成长性被观测到"的完成定义）

1. 一段真实的长期运行（或 Phase 4 回放）后，一条命令产出成长报告，G1–G5、F1–F7、H1/H2/H4 全部有数；
2. 报告能对 Q1–Q8 给出数字结论，其中 Q2（网络变密）与 Q4（跨会话想起）有明确的是/否答案；
3. 回归测试全绿，telemetry 关闭时系统行为与现状逐位一致；
4. growth_stats 持续累积且模板间出现分化（P2 闭环接通的证明）。

---

## 十、实施状态（2026-09-25，Phase 1–4 交付）

### 交付物

| 需求 | 交付 | 位置 |
|---|---|---|
| R1 事件流水 | `MemoryTelemetry`（异步队列 + 单代轮转 + 坏行容忍读口），11 类生命周期事件全接线 | `src/agent/soul/memory/telemetry/`（events/config/telemetry） |
| R1.1 触发点 | life 侧（log/orchestrator/hub/pipeline）+ memory 侧 store 收口包装 | `telemetry/store_hooks.py` 于 `facade/build.py` 装配 |
| R2 快照 | sleep 末尾 hook（`SleepService(snapshot_hook=...)`），以 store 为准 | `telemetry/snapshot.py`、`facade/build.py` |
| R2.3 报表 | CLI + 可导入模块（漏斗/五维/命中/Q1–Q8） | `telemetry/report.py`、`scripts/memory_growth_report.py` |
| R3 检索埋点 | 入口 A（facade search）/ B（spread 点查询，含各路召回明细）/ C（compose，含 90/10 分支）/ D（recall 与 recall_social）；H2 采纳在 compose_bridge | 各入口文件 + `telemetry/events.py` |
| R4 growth 接线 | `get_default_rewriter()` 带 GrowthEngine（stats 落盘 `.react/retrieval/growth_stats.json`，llm=None）；入口 B 完成后 `report()` 回报 H4 图路命中（实体种子 + 束搜索触达）；authoring 默认关 | `infra/retrieval/__init__.py`、`emergence/spread/service.py`、`config/infra/retrieval.yaml` |
| R5 回归锁 | 36 测试：行为不变锁（B/C 入口逐位一致）、事件完备性、故障容忍、漏斗一致、growth 接线锁、回放框架保护 | `src/test/memory/telemetry/` |
| R6 回放（模式甲） | 生产装配驱动器（JSON 后端 MemoryService + Life 编排器 + sleep 巩固 + 入口 B/D/A），内置 6 会话剧本含跨会话探针，确定性伪 LLM 或真实 LLM | `scripts/memory_growth_replay.py` |

运行方式：

```bash
python scripts/memory_growth_replay.py --tag smoke      # 回放 + 自动产出判定报告（默认伪 LLM）
python scripts/memory_growth_report.py                  # 对 .react/telemetry 出报表
python -m pytest src/test/memory/telemetry/ -q          # 36 项回归锁
```

### 与 R1.1 表格的两处字段级偏差（实现时确定）

1. `node_forgotten` 不含"当时 activation"——store 的 forget_scan 只返回 id 列表，
   预扫激活度会使扫描翻倍；遗忘速率由 G5 存活曲线承担，单点激活度不补。
2. `recall_recorded` 不含"触发入口"——store 层 on_recall 无法区分调用方；
   入口归因由相邻的 `retrieval_performed`（B/C/D 各自带 entry 字段）在报表侧对账完成。

### 首轮回放（伪 LLM、6 会话、无向量形态）暴露的机制发现

- **F1→F2 是最大瓶颈**（标注擢升率 0.5）：未标注轮的体验只进热日志不入图，擢升宽度完全取决于上游标注行为（P3 实证）。
- **跨会话建边依赖 interactor 一致性**：会话闭合单元的 anchor 若回退 session_id 作 interactor，归档侧 interactor 过滤会挡死跨会话选父（图只变大不变密）。回放通过钉住 interactor 恢复建边（F5 建边率 1.0）后，Q2=网络变密 True。生产需确认 channel→interactor 绑定在所有写入路径生效。
- **无向量形态下 H4 恒为零**：束搜索/实体种子依赖向量基建，JSON 默认后端下 growth 模板统计不会分化（Q8=False 属结构性结果，非 bug）——P5 启用前不应据 Q8 判断模板质量。
- 剧本规模下 Q3（用进废退）/Q4（跨会话想起）/ground-truth Hit@k（6/6）均为正，小库检索健康。

### 未做（对应第五阶段与 D 决策）

- 模式乙（真实会话回放）待 D3 数据源落实；
- authoring（LLM 造模板）默认关，待统计分化证据后按 D4 放开；
- P4（tier 迁移）/P5（向量基建启用）按 D6 未纳入，本需求保持纯观测。
