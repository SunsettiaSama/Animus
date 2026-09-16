# speak 拟人度三维评测

对 `agent.soul.speak` 的管线做**拟人度**评测。单一体感的"像不像人"拆成三个互补维度，
每个维度只能被特定的退化策略骗过，三者合起来才闭环：

| 维度 | 测什么 | 防哪种退化 | 评委 |
|---|---|---|---|
| ① 画像匹配 | 聊完后对方能还原出"是个什么样的人" | 人格漂移 / 人设不自洽 / 风格传达失败 | LLM（抽取 + 逐维核对） |
| ② 图灵盲测 | 过程中"像不像人" | 模板化共情 / 过度完整 / 机械追问 | LLM 分类投票（复用 speak_turing） |
| ③ 行为统计 | 过程量的确定性指标 | 空回复 / 机器人腔 / 复读 / 查户式反问 | 无（纯 transcript 计算） |

## ① 画像匹配（本包新增）

1. **盲聊**：`DynamicUserSimulator`（不知 persona、被要求自然闲聊）与被测管线多跳对话 4~6 轮；
2. **框架伪装抽取**：让对话者以"刚认识的网友，朋友随口问起"的口吻反推画像
   （`identity / facts / traits / style / values / interests / boundaries / impression`），
   不提 AI/评测/模拟，允许空数组（没聊到就是没聊到）；
3. **逐维核对**：评委拿到 [真实档案]×[聊天记录]×[网友印象] 三方，对 7 个维度独立判
   `opportunity`（聊天是否触及）/ `captured`（触及下是否被正确捕捉）/ `contradicted`（是否矛盾），
   另判 `false_claims`（编造）与 `style_score`（风格贴合 1~5）；
4. **画像保真度** = `0.45*recall_covered + 0.35*precision + 0.20*(style/5)`，缺项重归一。

Ground truth 为 `.react/persona/built_profile.json`（7 维映射见 `persona_target.py`）。
`recall_covered` 只在**被触及**的维度上计算，避免"5 轮闲聊聊不到动机/软肋"被结构性压分。

## ② 图灵盲测

直接复用 `test.workbench.speak_turing` 的 `CategoricalDialogueJudge`：
`known_user`（判 SPEAKER）与 `blind_both`（A/B 双盲随机换位）各 3 票多数决。

## ③ 行为统计（`behavior.py`）

`empty_rate / robotic_marker_rate / repeated_opener_rate / echo_rate / question_ratio / len 统计`，
加权扣分到 `naturalness ∈ [0,1]`（权重见 `behavior_naturalness`，反问比健康带 0.45）。

## 综合

```
拟人度 = 0.40*画像保真度 + 0.35*blind_both人率 + 0.25*行为自然度   （缺项重归一）
```

## 跑法

```bash
python scripts/speak_humaneness_bench.py --limit 1                 # 双管线单 case 冒烟
python scripts/speak_humaneness_bench.py --case-ids casual_after_work,playful_teasing
python scripts/speak_humaneness_bench.py                           # 全量 50 case
```

产物（`.react/benchmark/speak_humaneness/<run>/`）：`transcripts-<pipeline>.jsonl`、
`raw_llm.jsonl`（画像抽取/核对全部原始输出，可 rejudge）、`records.jsonl`、`summary.json`、`report.md`。
中断后原样重跑即续（`--resume` 默认开）。

## 管线对照

`request_driven`（三角色分治：导演/编剧/角色，3935dec 重构，当前默认管线）
vs `direct`（直通单角色旁路，f4a2383 引入的最新管线：帧内零前置 LLM 调用，不启动导演席位线程）。
注意时间线上 `direct` 才是最新管线；两者走同一 `_compose_bundle`（同一份 persona_distill），
差异纯在编排层。`legacy_qa` 虽在 router 注册但 `normalize_speak_responder` 不可达，未纳入。
