# infra.retrieval — 检索引擎基座

`src/infra/retrieval` 提供检索侧的引擎实现：**结构化查询改写（rewriter）、成长型模板引擎（growth）、kmeans 入口定位（locator）、语义束搜索遍历（walker）**。

## 分层契约

- **只做检索，数据层无关**：端口只认通用类型——`(id, vector)`、`(to_id, weight)`、`HitSignal(id, score)`；不 import 任何 KG / memory / soul 类型。
- **知识库/文档接入属数据层职责**（PDF 等非结构化文档的解析、切块、向量化都在数据层完成），数据层通过同一端口对接本包。
- 上层（`agent.soul.memory`、评测、未来的知识库）只管调用，不实现检索算法。

## 结构化改写：RewriteResult 的消费契约

纯文本改写只服务向量路（= stack 形态的退化）。图检索的价值链是"精确种子 → 边约束遍历"，所以 rewriter 的主产物是**种子级信号**：

| 字段 | 消费方（graph 侧接线时映射） |
|---|---|
| `entities` | SeedResolver 精确种子（实体词面匹配） |
| `query` | 向量路 `embed_query` 输入 |
| `terms` | 关键词路 / BM25 / wander focus_keywords |
| `time_window` / `time_window_days` | activation 时间过滤 |
| `frame` | 检索 profile 提示（recall / verify / …） |

模板 pattern 带捕获组（`还记得(.+?)吗` → 实体）；`intent="verify"` 时 frame 强制为 verify（验真 profile 分流用）。

## 切词降级链（三级）

1. `jieba.posseg`（HMM=False，确定性，懒加载）；
2. fallback：正则切分（CJK 连续段成短语 + 英文词 + 数字），无词性——实体只剩捕获组，精度降档；
3. 改写结果为空 → 回退原文 strip（`used_original_fallback=True`），绝不产出空 query。

降级记 WARNING 日志；`backend()` 暴露当前档位。

## 成长型模板引擎（growth）

```
rewrite → report(result, hits) → 滚动统计（uses/hit_count/score_sum，持久化 growth_stats.json）
  → 样本 ≥ min_samples 且均分 < hit_threshold 且冷却过且有 LLM
  → 后台线程（ThreadLease，owner=infra.retrieval.growth）调 LLM 造新模板
  → 校验（可编译 + 必须含捕获组）→ 入库 trial（source=grown）
  → 持续低效（< retire_threshold）→ 退役
```

判据是**图路命中**；一切异常吞在内部，不外溢检索主链路。无 LLM 构造 = 纯统计惰性。LLM 只需满足 `generate(prompt) -> str`（BaseLLM / aux 槽位皆可）。

## KMeans 入口定位（locator）

管线前置的快速定位：`fit(entries)` 做规模检测——N > `scale_threshold`（默认 1 万）才 kmeans（K=`centers` 默认 1000，单位归一 + k-means++ + 固定种子，numpy）；否则 flat 直通。`route(query_vector, top_m=4)` 返回最近 top_m 质心的成员并集（对应 graph 侧 `member_ids_near_cores` 的用法）。增量超 `refit_drift_ratio` 时 `should_refit()` 提示重建。未 fit 时 route 返回空 + `status()` 显式暴露（不静默降级）。

## 语义束搜索遍历（walker）

KG 检索的"流向"控制：入口种子沿查询语义相似度最高的方向流动——

```
步分 = w_semantic·cos(query, 邻点向量) + w_edge·边权 − hop_decay·hop
每跳：扩展 beam 内候选的邻居 → 去重 → 保留 top beam_width → 收集至 max_nodes 预算
```

对比 `GraphTraversal.bfs` 的盲扩散（纯边权乘法、无查询感知）。全程确定性。端口：`out_edges(node_id) -> [(to_id, weight)]`、`node_vector(node_id) -> list[float] | None`。

## 配置与装配

`config/infra/retrieval.yaml` ↔ `src/config/infra/retrieval_config.py`（rewriter / growth / locator / walk 四段 + `store_root`）。

```python
from infra.retrieval import build_rewriter, SemanticBeamWalker, SemanticLocator

rewriter = build_rewriter(store_root=".react/retrieval", llm=None)  # llm 注入后才启用造模板
rr = rewriter.rewrite("你还记得我们上次一起去的那家拉面店吗")
# rr.query / rr.terms / rr.entities / rr.time_window / rr.frame
...  # 检索后：rewriter.report(rr, [HitSignal(id, score), ...])
```

## 评测

```bash
python scripts/memory_rewriter_ablation.py --limit 20   # 底座 × {off,l0} 矩阵 + kg_walk 臂
pytest src/test/infra/retrieval src/test/evals/test_rewriter_ablation.py -q
```

`retrieval_bench.evaluate_base(base_or_factory, cases, query_rewriter=...)` 与 `HumanenessHarness(query_rewriter=...)` 均为可选参数，默认 None 行为与历史一致。

全量矩阵（90 例，TF-IDF 代理，Hit@k）结论：

| 底座 | off | l0 | Δ |
|---|---|---|---|
| kg_bm25 / kg_semantic / kg_spread | 0.556 | 0.556 | ±0 |
| **kg_walk（束搜索+实体种子）** | 0.556 | **0.633** | **+0.078** |

- 纯文本臂零变化是**构造性**的：query 保留剥框架后的原文表层，文本匹配层（BM25/字符 bigram）自行切词——改写器丢词拼串曾造成 -0.067，已按数据修正；
- kg_walk 是唯一也是最大的正收益臂：rewriter 的价值全在 `entities`→精确种子 这条图路上，验证了"结构化改写服务 KG，而非面向 stack 的文本清洗"；
- 检索评测已滤 `NO_MEMORY_HINT` 行再判 FP（与 L3 行为评测同语义），负样本全臂 FP=0。
