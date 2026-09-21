# speak 拟人度三维评测与八臂管线对比报告

- 日期：2026-09-15（R5 组合臂同日追加）
- 评测代码：`src/evals/speak_humaneness/`（入口 `scripts/speak_humaneness_bench.py`）
- 数据产物：`.react/benchmark/speak_humaneness/main-ablation-20260915/`（十臂统一，80/80）与 `main-20260915`（首轮双臂）
- 画像 ground truth：`.react/persona/built_profile.json`（莉奈娅，revision 2026-05-27）
- 对话 case：`data/workbench/speak_turing/cases.jsonl` 中 8 条（casual_after_work / comfort_setback / first_snow_message / gentle_disagreement / photo_memory / playful_teasing / quiet_companionship / sarcasm_misread），每臂各跑一遍，80 份记录全部完成
- LLM：全部 MiniMax-M3（被测角色 / 用户模拟器 / 评委同源，已知局限）

---

## 1. 背景与指标设计

原始命题是"多跳对话后让对话者反推对方画像，用与人格档案的匹配度当拟人度"。评审结论：该指标只测"是个什么样的人"（人格信息的传达力），测不到"像不像人"（语气/节奏/不硬找话），单独使用会被复读人设的退化策略骗过。因此拆成三个互补维度，各自防一种退化，合成一个总分：

```
拟人度综合 = 0.40 × 画像保真度 + 0.35 × 图灵盲测人率 + 0.25 × 行为自然度   （缺项重归一）
画像保真度 = 0.45 × 机会recall + 0.35 × precision + 0.20 × (风格分/5)      （缺项重归一）
```

- **画像匹配**：盲聊（用户模拟器不知 persona、被要求自然闲聊）→ 对话者以"网友被朋友随口问起"的框架反推画像（不提 AI/评测，允许"没聊到"）→ 评委拿 [真实档案]×[聊天记录]×[网友印象] 三方逐维核对。
- **图灵盲测**：复用 `test.workbench.speak_turing` 的分类评委，`blind_both`（A/B 双盲随机换位）与 `known_user`（已知 USER 判 SPEAKER）各 3 票多数决。
- **行为统计**：纯确定性 transcript 指标，不花评委调用。

## 2. 表头字典

| 表头 | 定义 | 来源 | 范围 |
|---|---|---|---|
| 画像保真度 | 网友反推画像对真实人格档案的忠实程度（合成式，见上式） | 画像匹配评委 | 0~1，越高越好 |
| 机会recall | 在"聊天确实触及"的维度里，被网友正确还原的比例；未触及维度不计入分母，避免短对话被结构性压分 | 画像匹配评委，7 维（身份与经历/性格特质/人际与情感表达/价值观与底线/思维方式/说话风格/动机与软肋） | 0~1 |
| precision | 网友画像中非编造比例 = 1 − false_claims/主张总数；惩罚脑补 | 画像匹配评委 | 0~1 |
| 风格分 | 评委对"网友对说话风格的描述"与档案 dialogue 切片的贴合度 | 画像匹配评委 | 1~5 |
| 矛盾率 | 被触及维度中网友画像与档案明显矛盾的比例 | 画像匹配评委 | 0~1，越低越好 |
| blind人率 | blind_both 协议下角色被判"真人"的 case 比例（3 票多数决） | 图灵评委 | 0~1 |
| known人率 | known_user 协议下角色被判"真人"的 case 比例 | 图灵评委 | 0~1 |
| 行为自然度 | 确定性扣分合成：空回复/机器人腔/复读开头/回声复述/反问比偏离 0.45/句长过于均一/长篇大论 | transcript 计算 | 0~1 |
| 综合分 | 上文拟人度综合公式 | — | 0~1 |
| 均长 | 角色回复平均字符数（行为统计成分之一，单独列出用于"太满"归因） | transcript 计算 | 字 |
| 沉默/预约 | 角色行使沉默权 / 写下"预约下一拍"的轮次数（仅 direct_silence 臂有机制） | 端口事件计数 | 次 |
| p50 | 单轮 speak 生成耗时中位数 | transcript wall_ms | ms |

## 3. 八臂定义

所有臂共用同一角色 LLM、同一 persona 注入（`_compose_bundle` → persona_distill）、同一份 case 与评委；差异全部在 `agent/soul/soul/speak/responders/request_driven/layers.py` 的动态层汇合点，由环境变量 `SPEAK_EVAL_CARD_FAMILY` 门控（生产不设此变量，行为不变）。

| 臂名 | 管线 | 提示词里有什么 | 注入决策 |
|---|---|---|---|
| request_driven（三角色全量） | 新主线（导演/编剧/角色） | 导演卡+剧情卡+记忆/分享全量 | 编剧写进 plot_flow（现状架构） |
| rd_dir_only（导演卡独存） | 同上 | 只留导演/节奏卡（处境笔记、临场状态、舞台信息） | 同上，剧情族被清空 |
| rd_writer_only（剧情卡独存） | 同上 | 只留剧情卡（故事线/此刻情景/pass_info）+记忆/分享 | 同上，导演族被清空 |
| rd_softplot（软约束剧情） | 同上 | 剧情卡降格为软约束措辞 + 显式注入"对方在剧情中的位置（对方发言优先）" | 同上 |
| rd_dynsched（阈值版导演调度） | 同上 | 节奏卡出清（同 writer） | 导演策略代理：记忆截断至 2 条；分享仅在开口欲≥60 注入 |
| rd_dynsched_llm（导演 LLM 调度） | 同上 | 节奏卡出清（同 writer） | 导演 LLM 带对话近况逐条判定记忆/分享注入（"宁缺毋滥"倾向） |
| direct（直通无卡） | 直通旁路（最新管线） | 无动态层卡片 | 无（角色直面用户消息） |
| direct_silence（直通+沉默自约） | 直通旁路 | 无卡片 + 自主权块：可只回「……」沉默；可写"预约：…"自约下一拍（存入上下文、下一拍回显） | 无；预约与沉默由角色自行行使 |
| rd_combo（软剧+导演v1组合） | 同上 | 软约束剧情（同 rd_softplot） | 导演 LLM v1 判定（只见对话近况，原"宁缺毋滥"prompt） |
| rd_combo_v2（软剧+新导演v2组合） | 同上 | 软约束剧情（同 rd_softplot） | 新导演 v2：判定时喂入编剧线程产出的剧情材料做对齐；prompt 以"该 unit 对本轮交互的影响"为核心，逐类写明双向权衡（记忆：精准接话↔剧情沉浸下降；分享：新鲜感↔打断当前场景），不预设注入/拒绝立场 |

## 4. 结果总表（按综合分降序）

| # | 臂 | 画像保真度 | 机会recall | precision | 风格分 | 矛盾率 | blind人率 | known人率 | 行为自然度 | **综合分** | 均长 | 沉默 | 预约 | p50(ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 软剧+导演v1组合 | 0.899 | 0.883 | 0.983 | 3.3 | 0.000 | 0.38 | **0.62** | 0.887 | **0.722** | 55 | – | – | 4598 |
| 2 | 直通无卡 | 0.683 | 0.559 | 0.958 | 3.0 | 0.000 | **0.50** | 0.25 | 0.910 | 0.692 | 77 | – | – | 5932 |
| 3 | 软约束剧情 | 0.849 | 0.807 | 0.953 | 3.5 | 0.000 | 0.25 | 0.38 | 0.920 | 0.680 | 71 | – | – | 3232 |
| 4 | 剧情卡独存 | **0.908** | **0.920** | 1.000 | 3.2 | 0.000 | 0.12 | **0.62** | 0.873 | 0.639 | 53 | – | – | 5294 |
| 5 | 导演卡独存 | 0.647 | 0.614 | 0.988 | 2.8 | 0.029 | 0.38 | 0.50 | 0.914 | 0.636 | 76 | – | – | 3974 |
| 6 | 软剧+新导演v2组合 | 0.873 | 0.798 | 0.991 | **4.0** | 0.000 | 0.12 | 0.50 | 0.911 | 0.633 | 73 | – | – | 4649 |
| 7 | 三角色全量 | 0.777 | 0.722 | **1.000** | 3.8 | 0.000 | 0.12 | 0.38 | 0.904 | 0.603 | **104** | – | – | 5236 |
| 8 | 直通+沉默自约 | 0.564 | 0.437 | 0.978 | 2.3 | 0.000 | 0.25 | 0.50 | **0.927** | 0.545 | 60 | 1 | 0 | 3447 |
| 9 | 导演LLM调度v1 | 0.655 | 0.639 | 1.000 | 2.2 | 0.000 | 0.00 | 0.38 | 0.926 | 0.528 | 65 | – | – | 3000 |
| 10 | 阈值版导演调度 | 0.515 | 0.417 | 0.988 | 2.4 | 0.021 | 0.00 | 0.38 | 0.910 | 0.433 | 65 | – | – | 3516 |

### 逐 case 综合分矩阵

| case | 全量 | 剧情 | LLM调度 | 软剧 | 导演卡 | 直通 | 沉默自约 |
|---|---|---|---|---|---|---|---|
| casual_after_work | **0.94** | 0.63 | 0.26 | 0.60 | 0.61 | **0.94** | 0.50 |
| comfort_setback | **0.63** | 0.60 | 0.64 | 0.61 | 0.27 | 0.46 | 0.24 |
| first_snow_message | 0.61 | 0.64 | **0.65** | 0.63 | 0.57 | 0.39 | 0.54 |
| gentle_disagreement | 0.61 | 0.58 | 0.61 | **0.77** | 0.57 | 0.61 | 0.26 |
| photo_memory | 0.53 | 0.58 | 0.62 | **0.64** | 0.60 | 0.61 | 0.60 |
| playful_teasing | 0.64 | 0.95 | 0.64 | 0.99 | 0.59 | **0.99** | 0.87 |
| quiet_companionship | 0.62 | 0.53 | 0.56 | 0.63 | 0.88 | **0.89** | 0.75 |
| sarcasm_misread | 0.25 | 0.60 | 0.25 | 0.58 | **1.00** | 0.63 | 0.58 |

## 5. 分轮发现

### R1：主线 vs 直通（首轮 8×2）
- 三角色全量人格传达更强（画像 0.777 vs 0.683，precision 1.000 零编造、零矛盾），但盲测被识破率高（12.5% vs 50%）；行为统计归因：均长 104 vs 77 字，"过度完整/过于工整"是评委点名的 AI 特征。
- 分 case 模式：全量赢情绪支持/氛围（comfort_setback、first_snow），输玩笑/安静/反讽——问题不是"不像人"而是"太用力"。

### R2：卡片族消融（R1 基础 + 2 臂）
- **人格传达主力是编剧的剧情卡片**：剧情卡独存画像 recall 0.920 全场最高；导演卡独存 0.614。
- **"太满"是两族卡片叠加的放大效应**：均长全量 104 → 单族 53~76。
- **两族卡片各有毒药场景**：剧情卡毒死安静陪伴（0.53）与反讽修复（0.60）；导演卡毒死玩笑（banter 0.59）。没有全局最优族 → 需要场景自适应调度。

### R3：设计臂（阈值调度 / 软约束剧情）
- **软约束剧情成为 rd 族最优（0.680）**：验证了"用户在剧情中没有位置"假设——加"对方在剧情中的位置、对方发言优先"后，玩笑 0.99、分歧 0.77、哀伤 0.64 均修复，同时画像 0.849 与行为 0.920 保持高位。唯一未修复：安静陪伴（产出量控制问题，非措辞问题）。
- **阈值版导演调度全场最差（0.433）**：待分享事项与记忆卡是角色自我暴露的主载体，按固定阈值门控会让人格传达崩塌（recall 0.417，两个 case 画像 0.06）。证伪"简单砍注入降干扰"。

### R4：正经版导演调度 / 角色沉默自约
- **导演 LLM 调度（0.528）**：比阈值版大幅回升（comfort_setback 画像 1.0 vs 0.06），行为自然度 0.926，但仍不敌编剧注入（recall 0.639 vs 0.920）。归因：① 导演判定只看对话近况，看不到剧情语境，决策信息少于编剧；② 判定 prompt 带"宁缺毋滥"保守倾向，把分享（人格主载体）大量拒掉（风格分 2.2 全场最低）。
- **直通+沉默自约（0.545）**：机制打通（沉默 1 次、预约 0 次落盘可查），但 4~6 轮友好闲聊里角色几乎不使用沉默权——沉默的价值场景（长对话/无聊话题/重复追问/被冒犯）本 harness 未提供。综合分下滑主要来自个案噪声与自主权说明块的元指令开销；方向性收益存在（安静陪伴 0.75 优于软剧 0.63，first_snow 0.54 优于直通 0.39）。

### R5：组合臂（软约束剧情 × 两版导演调度）
- **软剧+导演v1组合 = 0.722，全场第一，首次超过直通（0.692）**。软框架与导演过滤产生了正向叠加：软框架保住"对方发言优先"（修复剧情卡独存的场景失败），导演过滤把回复瘦身到 55 字（与剧情卡独存同级精炼），同时人格载体保留度反而高于软剧单臂（画像 0.899 vs 0.849，blind 0.38 vs 0.25，known 0.62）。个案上 casual 0.99、sarcasm 0.91、playful 0.94；短板仍是安静陪伴（0.52）。
- **软剧+新导演v2组合 = 0.633**，未超过 v1 组合。v2（剧情对齐 + 中性权衡 prompt）注入更慷慨：风格分 4.0 全场最高、precision 0.991、反讽修复 0.92 全族最佳，但回复变长（73 字）、盲测通过率回落（0.12），综合被拉回三角色全量的画像强/盲测弱区间。两版导演实际落在权衡谱两端：v1 偏"松弛"（当前综合权重 0.35×blind 奖励这一端），v2 偏"人格在线"。v1 组合的 casual 0.99 与 v2 的 0.64 这类大分差在 N=8 下需谨慎解读。
- 两线程交互的实现说明：评测层在注入汇合点把编剧线程写入 state 的剧情材料（outline+flow）同步喂给 v2 判定器，模拟导演/编剧跨线程读取；生产化时对应"导演持有时间轴 + 读编剧剧情槽位"的架构。

## 6. 结论与架构建议

1. **当前最优形态是"软约束剧情 + 导演注入过滤"（rd_combo，0.722）**：软框架解决"用户在剧情中没有位置"，导演过滤解决"太满"，两者叠加同时保住人格传达（画像 0.899）与松弛感（55 字、blind 0.38）。rd 族由此首次超过直通臂。
2. **人格传达的信息源排序**：剧情卡片 ≫ 分享/记忆卡 > 导演卡。任何调度方案若削减前两者的注入量，画像保真度先受损。
3. **剧情卡的正确形态是软约束 + 用户位置**（rd_softplot 验证），编剧生成端应把"对方位置"写进剧情本身。
4. **注入决策权的权衡谱**：v1（偏拒绝）→ 松弛、盲测友好；v2（剧情对齐+中性权衡）→ 人格/风格最强（4.0/5）但盲测回落。导演 prompt 的"影响描述"决定臂落在谱的哪一端，这本身就是产品可调的旋钮；若目标是综合均衡，v1 与 v2 之间存在中间档（如只对"与当前剧情无关的记忆"收紧、对分享放宽）。
5. **沉默/自预约**：提示词层协议基本不会被模型主动使用；产品化应让角色输出接入 `character_rhythm_schedule` 的时间轴槽位（导演持时间轴、角色可写入）。验证需要压力场景 case 或静默窗口协议。
6. **主动性（多对多/预约开口）在本 harness 中结构性缺席**：一问一答的 inbound 驱动下，导演主动开口被用户让位机制压制，idle 阶梯到不了点。补测方案：末轮后挂 60~120s 静默窗口，统计主动开口率/时点合理性/话题命中率。

## 7. 局限

- N=8 case、单轮采样：方向性结论可信，数值间小幅差异（<0.1）不构成排序依据；图灵单项 1~4/8 的差异噪声很大。
- 评委/模拟器/被测同为一个模型（MiniMax-M3），同源偏置未分离；`raw_llm.jsonl` 全量落盘，可换评委离线重放（rejudge）。
- photo_memory（哀伤话题）多次触发用户模拟器空输出（累计重试 5 次才全通过），是模拟器侧压力点。
- 消融在提示词汇合点实现（env 门控），非服务架构级的真实管线分叉；`rd_dynsched_llm` 的导演判定是每轮一次独立 LLM 调用（缓存同候选），与生产内嵌导演 Agent 的行为可能有差。

## 8. 生产化落地（2026-09-17）

评测结论已整合进 `agent.soul.speak`（request_driven）：

- **剧情软约束 + 用户位置成为生产默认**（R3/R5 结论）：`layers.py` 剧情卡头改为"参考剧情（软约束）"，并固定注入"对方在剧情中的位置"注记；编剧 `_CRAFT` 增加对应书写守则（unit 不得越过对方发言推进）。
- **导演注入门控 v1/v2 生产化**（`responders/request_driven/directors/unit_gate.py`）：编剧提案、导演复核——门控在编剧异步写线内运行（线程隔离，角色热路径零 LLM），判定失败保持编剧原提案。环境变量 `REACT_SPEAK_UNIT_GATE=v1|v2`（默认 off）选择版本；v2 喂入编剧剧情材料做对齐，prompt 为中性双向权衡（不预设立场）。
- **编剧自由查询记忆**：`Screenwriter.memory_search` 端口直连 `MemoryService.search`（hybrid/recent），产出"对方记忆"材料块（`materials.py`），不重建检索基座；Soul 层经 `attach_screenwriter_memory_search` 挂载。
- **ContextProvider 协议**（`orchestrator/context_provider.py`）：环境材料提供者抽象（`kind`/`snapshot`），编剧为默认 provider；游戏内容等可经 `SpeakService.register_context_provider` 封包接入，热路径（`_director_dynamic_schedule`）只认协议快照。
- **前端管线切换**：收敛门放开为 `request_driven | direct`（`webui/speak_pipeline_gate.py`）；设置页 Speak Pipeline 下拉恢复可选，`/ws/agent/run` 支持会话中途 `pipeline` 帧（复检收敛门后生效）；前端 `features/speak_pipeline.js`（localStorage + `speak:pipeline` 事件）。

新增单测：`src/test/soul/speak/test_unit_gate_and_providers.py`（门控过滤/缓存/故障回退、provider 优先级与接管、软约束头、编剧记忆富化与门控钩子）。speak 套件与改造前基线一致（29F/345P/17E → 29F/353P/17E，passed 增量全部来自新测试；仅 1 处旧头断言随软约束化更新）。

### 追加（2026-09-17 第二批：沉睡/唤醒 + life 事件源 + E2E）

- **speak 沉睡/唤醒**：`SoulService.start()` 只构造 speak 不启线程（默认沉睡）；`wake_speak()`（幂等、加锁）在对话 WS session_open（`/ws/agent/run`、`/ws/speak/run`）与 `speak_run_turn`/`start_dialogue_session` 接入点唤醒；`/api/speak/status` 新增 `speak_awake`。E2E 实测：webui 就绪后 `speak_awake=false`，WS 接入后转 true。
- **编剧事件源（life→speak 演化通道）**：`LifeManager.current_landmark_briefs()`（phase=experiencing/due/just_done）→ `attach_life_event_port` → coordinator 材料 `life_event_briefs`/`life_everyday` → WritingMaterials 渲染"角色亲历事件"块；无事件时显式注入"只是在过日常，不要编造任务感"。编剧 `_CRAFT` 同步增加事件感/日常感守则；大纲/剧情卡片产出与预热池（story pool）不动。
- **引擎 think 剥除**：MiniMax-M3 会在 content 前置 `<think>…</think>`，生产链路此前无防护（E2E 抓到 answer 混入英文思考）。`SpeakLLMEngine` 出口统一剥除（generate + 流式缓冲过滤）。
- **E2E 验证**（`/ws/agent/run` 真机）：request_driven 与 direct 均可聊、人设在线、中途 `pipeline` 帧切换生效；遗留两点均为既有问题——request_driven 的 `turn_finish.answer` 常为空、回复经异步 speak_event 延迟一拍送达（与 2026-08 speak_turing live 空回复同模式）；guidance planner 偶发 JSON 解析异常（有降级路径）。
- 本批单测：`test_speak_dormancy_and_life_events.py`（沉睡幂等、landmark phase 窗口、everyday 渲染、coordinator 注入）。speak 套件 29F/359P/17E（基线不变）。

### 追加（2026-09-17 第三批：评测↔生产 1:1 对齐）

- **REACT_SPEAK_RHYTHM_CARDS=off**（`layers.py`）：动态层不出导演/节奏卡（处境笔记、临场状态、舞台信息）——rd_combo 优胜形态的最后一块拼图；与评测消融臂共用同一份出清字段表。生产默认 on（行为不变）。
- **判定 prompt 单源**：评测 `unit_judge.py` 的 v1/v2 system prompt 改为 import 生产 `directors/unit_gate.py`，评测与生产永不漂移。
- **评测 runtime 接生产装配**：`LiveSpeakHumanenessRuntime` 直构 SpeakService 时同样读 `REACT_SPEAK_UNIT_GATE`——评测可用纯生产 env 复现生产管线。
- **纯生产 env 验证**（8 case，无任何评测 hook）：`RHYTHM_CARDS=off + UNIT_GATE=v1` 达到画像 0.751 / precision 0.99 / 风格 3.5（人格在线 ✓），但综合 0.525 低于 rd_combo 的 0.722，差值主要来自 blind 0/8（vs 3/8）与均长 69 字（vs 55）。
- **残余非 1:1 点（已定位）**：评测臂的门控在**每次角色生成的提示词组装点**同步过滤（热路径内 LLM）；生产门控挂在**编剧异步写线**（线程隔离要求），编剧当轮不落笔时该轮注入不经门控 → 回复更满、更易被盲测识破。彻底 1:1 需在编排 fast 通道做逐轮门控（待议：可在 orchestrator fast 事件中预判、角色回合读缓存判决）。另注：photo_memory/playful 单例画像 0.06 为评委方差（历史多次出现），N=8 下差值解读需谨慎。

## 9. 复现

```bash
python scripts/speak_humaneness_bench.py                                   # 主线 vs 直通（新目录）
# 八臂（同一输出目录续跑，records.jsonl 为聚合单元，断点自动续）：
python scripts/speak_humaneness_bench.py --responders rd_dir_only     --card-family director     --output-dir <dir>
python scripts/speak_humaneness_bench.py --responders rd_writer_only  --card-family writer      --output-dir <dir>
python scripts/speak_humaneness_bench.py --responders rd_dynsched     --card-family dynsched    --output-dir <dir>
python scripts/speak_humaneness_bench.py --responders rd_dynsched_llm --card-family dynsched_llm --output-dir <dir>
python scripts/speak_humaneness_bench.py --responders rd_softplot     --card-family softplot    --output-dir <dir>
python scripts/speak_humaneness_bench.py --responders direct_silence  --card-family charsilence --output-dir <dir>
python scripts/speak_humaneness_bench.py --responders rd_combo      --card-family combo     --output-dir <dir>
python scripts/speak_humaneness_bench.py --responders rd_combo_v2   --card-family combo_v2  --output-dir <dir>

python -m pytest src/test/evals/test_speak_humaneness.py -q              # 离线 11 项
python -m pytest src/test/soul/speak/ -q --continue-on-collection-errors # 改动前后 29F/345P/17E 逐位一致（遗留坏测试，与本评测无关）
```

产物文件：`transcripts`（含在 records.jsonl）、`raw_llm.jsonl`（画像抽取/核对原始输出，可 rejudge）、`records.jsonl`（逐记录）、`summary.json`、`report.md`。
