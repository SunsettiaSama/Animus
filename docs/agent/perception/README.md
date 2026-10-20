# 感知协议层（agent.perception）

> 游戏/仿真世界 ⇄ agent.soul 之间的桥梁。世界里发生的事情，以流畅自然语言
> 的形态进入 soul 的 **life 层**，成为 agent 亲历经验的一部分；speak 侧的
> 角色因此"活在自己的世界里"。

## 一图流

```
┌─ 采集端（游戏侧）───────────┐      ┌─ 感知协议层（src/agent/perception）────────────┐      ┌─ soul 侧 ────────────────────────────┐
│ 《星陨之痕》无头 harness     │ NDJSON│  MetroidvaniaBridge（进程/协议管理）            │      │ life 层                                │
│  帧级 diff → GamePerception ├─────▶│  PerceptionBus                                 │─────▶│  GamePerceptionInbound                 │
│  PerceptionScene 快照        │ 事件 │   ├─ 翻译：VisionNarrator（高成本视觉模型，    │ 自然 │   → ExperienceUnit(source=game)        │
│  NPC 交互(npc_talk)          │      │   │        暂时占位) > RuleNarrator（兜底）    │ 语言 │   → 热日志 + 虚拟账本(game_event)      │
│                              │ ◀────│   ├─ RecentPacketStore（近期包，读模型）      │      │   → Presence 同步                     │
│  弹窗/Toast 显示台词         │ 台词 │  NpcDialogueBridge → speak 回合 → 回注        │      │ speak 层                               │
└──────────────────────────────┘      └───────────────────────────────────────────────┘      │  life 事件口 + ContextProvider(game)   │
                                                                                             │  NPC（守灯人·烛）= soul 的游戏化身     │
                                                                                             └───────────────────────────────────────┘
```

## 模块

| 模块 | 职责 |
|---|---|
| `protocol.py` | **协议本体**：`GamePerceptionEvent`（结构化事件）/ `PerceptionScene`（现场快照）/ `PerceptionPacket`（自然语言包）/ `PerceptionTranslator`（翻译器协议）。采集端 NDJSON 的 `kind` 与 `GameEventKind` 一一对应 |
| `narrate.py` | `RuleNarrator`：确定性规则叙事（离线兜底、测试基线） |
| `vision.py` | `VisionNarrator`：**高成本视觉模型占位翻译器**（多模态 LLM，事件 JSON + 现场摘要 + 可选画面截帧 → 严格 JSON 叙事）。配置在 `config/llm_core/vision.yaml`，未启用/失败自动回退规则叙事 |
| `bus.py` | `PerceptionBus`：翻译 → 存储 → 订阅者 → life 入账；故障隔离（翻译失败回退、life 抖动不断流） |
| `store.py` | `RecentPacketStore`：近期包缓存，`briefs()` 产出 speak life 事件口形状 |
| `speak_provider.py` | `GameContextProvider`（kind="game"）：注册进 `SpeakService.register_context_provider`，把游戏现场作为角色环境材料 |
| `gamebridge/` | 具体游戏桥：`metroidvania.py`（node 子进程 + NDJSON）、`npc.py`（NPC ↔ speak） |
| `runtime.py` | 装配：`build_lite_runtime`（离线可跑的最小 soul）+ `attach_full_soul`（生产 SoulService）+ `drive_bridge`（e2e 驱动） |

## 协议要点

1. **一切经历皆自然语言**：`PerceptionPacket.narrative` 必须是流畅的完整句子；
   life 层不做二次改写，结构化原始数据走 `evidence` 归因。
2. **翻译器可替换**：当前默认视觉模型占位（`vision.yaml` 启用后生效），
   未来专用事件→叙事翻译器实现同一 `PerceptionTranslator` 协议即可热换。
3. **时间**：ISO-8601 UTC；桥以接收时刻打点，`frame` 保留游戏帧号。
4. **截帧可选**：`image_b64`（PNG base64）随事件携带，无头采集可为空。

## life 层接入点（soul 侧）

- 新增 `ExperienceSource.game`（归入 `VIRTUAL_SOURCES`）与
  `VirtualChronicleKind.game_event`：游戏事件与叙事/意外同路入虚拟账本。
- `LifeExperiencePipeline.ingest_game_beat(beat)` / `LifeExperienceStack.ingest_game_beat`
  / `SoulService.ingest_game_perception(beat)`：写入入口。
- 读取三通道：
  - `SoulService.attach_game_event_briefs(port)`：游戏简报并入 speak 的
    life 事件口（渲染为"[正在经历/刚经历完] …"）；
  - `SoulService.register_speak_context_provider(GameContextProvider(...))`：
    环境材料封包（仓库预留的"游戏内容"接入点）；
  - 既有链路自动受益：热经验、Presence 同步、记忆擢升策略不变。

## 运行

```bash
# 端到端演示（离线，零网络依赖；仓库根执行）
python scripts/starfall_perception_demo.py

# NPC 用真 LLM（读 config/llm_core/config.yaml）
python scripts/starfall_perception_demo.py --live

# 启用高成本视觉翻译器：编辑 config/llm_core/vision.yaml
#   enabled: true / model: glm-4.5v / api_key / base_url

# 单测（含 node e2e，无 node 自动跳过）
pytest src/test/agent/perception -q
```

## demo 侧（demos/metroidvania）

- `js/npc.js`：守灯人 NPC（`N` 地图字符，靠近按 **Enter** 交谈）。
  浏览器直开时有静态兜底台词；接桥后台词由 soul 产出。
- `perception/harness.js`：无头采集端（`node perception/harness.js`），
  stdout NDJSON 事件流、stdin 接收 `npc_line` 台词回注。

## 后续

- [ ] 专用事件→叙事翻译器替换视觉模型占位（协议不变）
- [ ] 浏览器实机模式：canvas 截帧 → `image_b64`，视觉模型看图翻译
- [ ] 接入 webui 拓扑（`/ws/speak/run` + `SpeakWsClient`，同桌宠/小镇模式）
- [ ] 游戏事件参与交会折叠（`COLLISION_SOURCES`）与记忆擢升策略调优
