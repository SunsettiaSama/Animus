# evals/memory_humaneness — 记忆基座评测（双管线）

职能分离（分支 `eval/memory-pipeline-split`）：

- **检索评测管线**（确定性、无 LLM、秒级）：L2 单跳检索质量 + L4 多跳检索链。
  测"记忆取得对不对"——排名依据以这里为准。
- **拟人度管线**（`dialogue/`，多轮对话模拟）：单一固定人格档案 × 记忆基座 ×
  轨迹级多维评判（情感承接/拟人度/记忆运用自然度/主动性）。测"带着记忆聊得
  像不像人"——记忆对错不在此管线评分范围。
- L3 单轮行为基准与 L4 `--full` 全链模式保留为辅助行为刻画（历史资产）。

## 拟人度管线（dialogue/）

```bash
python scripts/memory_dialogue_bench.py --limit 1 --judge heuristic   # 冒烟
python scripts/memory_dialogue_bench.py --bases graph,stack,none --judge llm
python scripts/memory_dialogue_bench.py --user llm --judge llm       # LLM 扮演用户
```

- **人格档案单一固定**（`persona.py`，小澄 v1）：变量只在记忆基座；
- **剧本库**（30 场景 × 8 轮，`scenarios.py`）：预载共同过去 + 预设用户输入 +
  回调锚点（第 i 轮应自然回访的早期事实）+ 情感弧；用户侧可换 LLM 扮演
  （只见历史与用户简笔，不见 Agent 记忆块）；
- **模拟器**逐轮：检索（滚动窗口 query）→ 人格+记忆 → 回复 → **本轮对话写回
  基座**（encode→retrieve 闭环，多轮价值所在）；
- **轨迹级评委**：整段对话 → 五维（`DIALOGUE_DIMENSIONS`），1~5；
  解析链与检索管线评委一致（直解→正则→抢救→降级），报告含
  `judge_fallbacks` 与评委来源占比（llm_expert 占比 = 数据可信度）；
- transcript 先保存再解析；开跑前打印 LLM 调用预算。

成本参考（scripted 用户 + LLM 评委）：场景数 × 基座数 × (轮数 + 1) 次调用；
30 场景 × 5 基座 × 9 ≈ 1350 次。评委走独立的 `--judge-max-tokens`（默认 3072，
轨迹分析 think 很长，1024 会截断）。

## 五档基座光谱

| 基座 | 语义 | 回答"什么问题" |
|---|---|---|
| `none` | 裸 LLM，不注入任何记忆 | 没有记忆时的行为基线 |
| `graph` | event/social 双网混合检索（MemoryService） | 检索式记忆系统的现状水平 |
| `stack` | 增量式 stack 旁路（词面+recency 检索） | 旁路简化方案的水平 |
| `compact` | 全量进上下文，超预算压缩旧记忆、仅留近期原文 | 上下文压缩策略的信息保真度 |
| `full` | 全量裸注入，不检索不压缩 | 信息上界 & 无关记忆噪声的代价 |

## L4 多跳记忆链（multihop）

调研结论：中文+多跳+长期记忆+拟人陪伴四要素全占的公开数据集不存在
（LoCoMo / LongMemEval 为英文且 HF 免认证通道不可拉取），故自产
`data/multihop_cases.jsonl`：100 条（确定性种子），每条**预载 10 条记忆**
（2 条跳记忆 + 8 条干扰，干扰项含实体共享型制造词面竞争），问句需跨两条
记忆才能作答。三种多跳模式借鉴 LoCoMo 类型学：

- `bridge` 实体桥接：宠物生病去的医院 ← 是谁推荐的（两跳拼接）
- `constraint` 约束迁移：用户过敏原 × 餐厅招牌含该过敏原（隐式约束）
- `temporal` 时序比较：两件事各自的时间 → 谁先谁后

命中判定用**跳指纹**（跳记忆文本的唯一切片）：干扰项可与跳记忆共享实体
（真实词面竞争），但不会冒名顶替跳命中。指标：逐跳命中率 / 联合命中率 /
跳 MRR / 干扰占位。检索式基座看"漏跳风险"，注入式基座看"跳在场 + 噪声"。

L4 基线（100 条，top_k=5）：

| 基座 | 逐跳 | 联合 | 干扰占位 | 解读 |
|---|---|---|---|---|
| graph | 0.585 | 0.290 | 3.8/5 | 无向量时退化为 recency 兜底，10 选 5 漏跳严重 |
| stack | 0.830 | 0.660 | 2.5/5 | bridge 1.0 / temporal 0.97 / **constraint 0.0**（过敏原无词面桥，词面检索的原理性盲区） |
| compact | 1.000 | 1.000 | 8.0 | 全在场但 8 条干扰同注入（压缩保留前缀足以识别跳） |
| full | 1.000 | 1.000 | 8.0 | 同上，信息上界 & 噪声代价 |

对比 L2（单跳、每例 1-3 条记忆）graph 1.000 vs stack 0.767——记忆密度上去后
排名反转（stack 0.66 > graph 0.29）：graph 的 recency 兜底在低密度时够用、
高密度下崩塌；stack 的词面过滤在问句含锚词时强、无词面桥时归零。
两条曲线指向同一个改进方向：接入语义向量检索。

## 先保存再解析（LLM 成本保护）

**LLM 原始输出是花钱买的数据**。行为基准运行时把每次 LLM 原文（回复、评委，
含 think，未截断）在解析之前逐条追加到 `<报告目录>/raw_llm.jsonl`——崩溃不丢，
解析 bug 修复后离线重放，永不重烧 API。

```bash
# 场景一：跑分后只发现解析/评判逻辑有 bug → 重放评委原文，0 次 LLM 调用
python scripts/memory_humaneness_rejudge.py --run-dir results/memory_humaneness/<ts> --judge llm

# 场景二：旧版 run 没存评委原文 → 只补调评委（复用已存回复，成本约为全量重跑的一半），
#         补调逐条落盘，中断可续
python scripts/memory_humaneness_rejudge.py --run-dir results/memory_humaneness/<ts> --judge llm

# 场景三：只想用规则评委重算（0 成本）
python scripts/memory_humaneness_rejudge.py --run-dir results/memory_humaneness/<ts> --judge heuristic
```

重评结果写入 `<run-dir>-rejudged/`（含 `judge_replays` / `judge_new_calls` /
`judge_fallbacks` 计数），原 run 目录只读不动。

## 运行

```bash
# L2 检索基准（确定性，改完检索代码后可秒级回归）
python scripts/memory_retrieval_bench.py                       # graph/stack/compact 全量 100 条

# L4 多跳基准（确定性检索评测；--build 重建数据集，种子固定）
python scripts/memory_multihop_bench.py                        # 逐跳/联合命中/干扰占位
python scripts/memory_multihop_bench.py --full --judge llm     # 全链：回复+评判（带 transcript）

# L3 行为基准：先离线冒烟验证管线（确定性回复器，不消耗 API）
python scripts/memory_humaneness_bench.py --fake-llm --limit 6
# 真实运行（LLM 配置读 config/llm_core/config.yaml 或 REACT_TEST_LLM_* 环境变量）
python scripts/memory_humaneness_bench.py --bases graph,stack,compact,full,none --judge llm

# 从 HuggingFace 抓 100 条转换为备用数据集（需联网）
PYTHONPATH=src python -m evals.memory_humaneness.fetch_hf --limit 100
```

日志约定：默认 INFO（阶段耗时、逐用例结果行、滚动均值与 ETA）；
`--verbose` 追加检索命中行/回复全文/评审理由；`--quiet` 只留 WARNING。

## L2 指标（`scripts/memory_retrieval_bench.py`）

数据集每条用例天然是 `(查询, 应命中记忆, 锚点 must_remember)` 三元组：

- **Hit@k / MRR**：锚点出现在前 k 行即命中；
- **SeedR**：多记忆用例的逐 seed 覆盖率；
- **噪声 FP**：`graceful_absence` 负样本（90 正 + 10 负）里检索不该出东西却出了的比例。

当前基线（100 条，JSON 后端、无向量）：graph 1.000 / compact 0.989 / **stack 0.767** ——
stack 纯词面检索在转述型查询（用户接着聊但不重复记忆原词）下会漏，改进路径：
接 embedder 做语义匹配、调 relevance 门槛、或引入兜底策略。这正是 L2 该抓的问题。

## L3 评分量规（1~5）

| 维度 | 考察 |
|---|---|
| memory_coherence | 该想起的是否自然想起、细节准确 |
| human_likeness | 口语、简短、有性格；非客服腔 |
| emotional_attunement | 情绪承接是否得体 |
| non_hallucination | 不编造不存在的记忆（`graceful_absence` 类重点） |
| overall | 整体"像不像记得你的真人" |

L3 产出写入 `results/memory_humaneness/<时间戳>/`（`report.md` 总览表、
分场景差异、逐维 delta、样本摘录）；L2 产出写入 `results/memory_retrieval/<时间戳>/`
（`metrics.json` + 逐用例 `details.jsonl`）。

## 数据集

`data/cases.jsonl`，100 条人工编写（10 类 × 10 条），由 `build_dataset.py` 生成并
经 schema 校验（锚点必须出现在预载记忆文本中，保证可命中）。`fetch_hf.py` 提供从
HuggingFace（empathetic_dialogues 等）在线抓取转换的可选通道。

## 目录

```text
src/evals/memory_humaneness/
├── schema.py            # 用例 schema / 加载 / 校验
├── build_dataset.py     # L3 100 条用例生成器（人工编写）
├── multihop.py          # L4 多跳数据集生成器 + 检索指标
├── fetch_hf.py          # HuggingFace 抓取转换（可选）
├── retrieval_bench.py   # L2 检索质量基准（Hit@k / MRR / 噪声）
├── judge.py             # ExpertJudge（LLM rubric）+ HeuristicJudge（确定性）
├── bases.py             # graph / stack / compact / full / none 五基座
├── prompt.py            # 人设 + 记忆参考 + 历史组装
├── fakes.py             # 离线确定性回复器（--fake-llm 冒烟用）
├── runner.py            # harness：case × base → 记录（transcript 先保存再解析）
├── rejudge.py           # 离线重评：transcript 重放 / 只补调评委
├── report.py            # 聚合 + markdown/json 报告
└── data/                # cases.jsonl（L3）+ multihop_cases.jsonl（L4）
```
