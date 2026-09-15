#!/usr/bin/env python3
"""干扰剂量-响应消融：注入 0/2/4/8/16/32 条干扰记忆，度量联合命中的衰减曲线。

直接回答"注入干扰记忆是否有害、害多少、随剂量如何变化"。
确定性、无 LLM。用法（cwd = 仓库根，语义/干扰臂需 LLMs 环境或任一 torch 可用环境）::

    D:/anaconda/envs/LLMs/python.exe scripts/memory_dosage_ablation.py
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from evals.memory_humaneness.ablation import (
    KGInterfereBase,
    KGBM25Base,
    KGSemanticBase,
    KGStore,
    ablation_factory,
)
from evals.memory_humaneness.multihop import (
    build_multihop_cases,
    validate_multihop,
)

DOSES = [0, 2, 4, 8, 16, 32]
ARMS = ("kg_bm25", "kg_semantic", "kg_interfere")


def make_factory(kind: str):
    if kind in ("kg_interfere", "kg_semantic"):
        from evals.memory_humaneness.ablation import BGEEmbedder
        try:
            emb = BGEEmbedder()
            emb.embed_query("预热")
            return ablation_factory(kind, embedder=emb)
        except Exception as exc:
            print(f"[warn] BGE 不可用（{str(exc)[:60]}），{kind} 降级代理")
    return ablation_factory(kind)


def joint_hit_for_case(factory, case, dose: int, top_k: int = 5) -> bool:
    base = factory()
    hops = [case.memories[h["memory_index"]] for h in case.hops]
    distractors = [m for m in case.memories if m.get("role") == "distractor"]
    # 剂量不足时循环扩充干扰池（过滤答案实体，保持不歧义）
    pool: list[dict] = []
    i = 0
    while len(pool) < dose:
        m = distractors[i % len(distractors)]
        suffix = f"（补充记录{i // max(1, len(distractors)) + 1}）" if i >= len(distractors) else ""
        pool.append({"text": m["text"] + suffix, "focus": m["focus"] + suffix[:4],
                     "emotion": m["emotion"], "valence": m["valence"],
                     "days_ago": m["days_ago"]})
        i += 1
    for m in hops + pool[:dose]:
        base.ingest(m["text"], focus=m.get("focus", ""), emotion=m.get("emotion", ""),
                    valence=m.get("valence", "neutral"), days_ago=m.get("days_ago"))
    block = base.recall(case.question, top_k=top_k)
    lines = list(block.entries or [])
    all_keys = [h.get("key", "") for h in case.hops]
    return all(any(k and k in line for line in lines) for k in all_keys)


def main() -> None:
    cases = build_multihop_cases()
    problems = validate_multihop(cases)
    if problems:
        raise SystemExit("数据集校验失败")
    cases = cases[:60]  # 60 例 × 6 剂量已足够读出趋势

    factories = {arm: make_factory(arm) for arm in ARMS}
    curves: dict[str, dict[int, float]] = {arm: {} for arm in ARMS}

    for arm in ARMS:
        for dose in DOSES:
            hits = sum(
                1 for case in cases
                if joint_hit_for_case(factories[arm], case, dose)
            )
            curves[arm][dose] = round(hits / len(cases), 3)
            print(f"{arm:<14} dose={dose:>2}  联合命中={curves[arm][dose]:.3f}", flush=True)

    print("\n剂量-响应曲线（联合命中率）")
    print(f"{'剂量':>4} " + " ".join(f"{a:>14}" for a in ARMS))
    for dose in DOSES:
        print(f"{dose:>4} " + " ".join(f"{curves[a][dose]:>14.3f}" for a in ARMS))


if __name__ == "__main__":
    main()
