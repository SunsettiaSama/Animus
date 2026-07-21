# Speak 三导演小样

独立于 `agent.soul.speak` 的架构沙盒：验证 **节奏 / 拼接 / 回复** 三导演是否足够，以及画像该喂给谁。

**不 import** `agent.soul.speak`。结论成熟后再考虑回灌 soul。

---

## 模块结构

```text
demo/speak/
├── run.py                   # CLI 入口
├── contracts/               # 纯 DTO / Protocol（零业务依赖）
├── stage/                   # 舞台状态 + capture_stage 快照
├── directors/
│   ├── rhythm/              # 门控 / 弧 / 临场计算 / 复盘
│   ├── compose/             # recipe + assemble
│   └── reply/               # 写台词 + 打字机
├── runtime/                 # runner / beat / poller / clock / delivery / share / on_scene_pump
├── io/                      # inbound / outbound / llm / review_store
└── shell/                   # console / fixtures / materials
```

依赖方向：`shell/run → runtime → directors → stage`；共用 `contracts`；`io` 只被 runtime/shell 使用。

隐喻：**大型舞台剧**。用户与 agent 都是台上角色；`StageState` 是持续管理的舞台；每拍冻结成 `StageSnapshot` 交给节奏导演。

### 舞台快照重点字段

| 字段 | 含义 |
|---|---|
| `history` | 最近场次对白 |
| `agent_status` | agent 当下态 |
| `share_queue` | **待分享事件队列** |
| `affect` | **情感程度**（intensity / label） |
| `cast.user` / `cast.agent` | **短角色卡**（给节奏看戏） |
| `idle_ms` / `trigger` | 调度节拍（user / poll） |

完整人格长文仍走拼接→回复；节奏只看短角色卡 + 队列 + 情感 + 场次。

---

## 三导演边界

| 导演 | 职责 | 禁止 |
|---|---|---|
| **节奏** | 看舞台快照，控制是否开口 / 分段 / 等待 | 写角色台词 |
| **拼接** | 从舞台取人格/画像/待分享，拼 system | 生成用户可见正文 |
| **回复** | 唯一写台词 | 改门控 |

```text
StageState ──capture──► StageSnapshot ──► RhythmDirector
                │                              │
                └──── Compose ◄────────────────┘（仅 speak/brew）
                              └─► Reply ─► Delivery

PollTick 循环问节奏：多数 listen/hold；队列/情感升温才开口
```

原则：

- **主动性 = 衰减概率轮询 + 软指令节奏**，不是第四导演。
- **对话弧 / 开口门控必须软指令驱动**；禁止情感 intensity、urgency、idle 数值阈值。
- 轮询：**掷骰问节奏，放行再拼接+回复**；快照里只给自然语言标签与时钟事实。

---

## 怎么跑

```bash
python -m demo.speak.run
python -m demo.speak.run --live              # 脚本后：根号衰减概率轮询（FakeClock）
python -m demo.speak.run --poll --fast-poll --poll-seed 1
python -m demo.speak.run --interactive --poll --fast-poll
python -m demo.speak.run --mode llm --live   # 真实 LLM + 衰减轮询
python -m demo.speak.run --sleep
```

轮询：按 `--poll-check` 掷骰，概率从 `--poll-p-start` **根号衰减**到 `--poll-p-end`（`--poll-curve linear` 为旁路），越过 `--poll-horizon` 后停止。

---

## 与 soul 九导演的映射

| soul 现状 | 小样归属 |
|---|---|
| Outline + TurnDelivery + SpeakGate | → **节奏** |
| ModuleInject + ComposeDirector / decide_plan + Memory/Share 注入意图 | → **拼接**（规则） |
| 主 LLM / `run_session_turn`（本应如此） | → **回复** |
| UserIntent | 节奏附属字段（`intent`） |
| SocialArm / Interrupt / 纯启发式 MemoryInject | 信号或 Session 规则；不成导演 |

---

## 从 LLM 试跑得到的观察

1. 节奏导演能单独产出合理 `wait_ms` / `reason`，不必写正文。  
2. 若不把「三导演边界」注入回复侧，模型会把画像误说成「人格导演」——说明 **架构元知识属于拼接材料，不是角色人格**。  
3. 三个导演 + Delivery 已够主链路；继续堆导演只会重复 soul 的病。

---

## 取向

1. 三个导演够主链路；其余降为信号 / 规则 / 执行器。  
2. **活人感 = 轮询节奏导演**，不是再堆「主动导演」。  
3. 拼接第一版用规则；节奏与回复可接 LLM。  
4. 用户/轮询回合：先节奏门控，仅 `speak/brew` 再拼接+回复（分享交接要求顺序）。  
5. 回灌 soul：按此形状重铺，而不是继续加导演。
