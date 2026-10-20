"""R2.3 成长报表：从事件流水 + 快照重建 G1–G5 / F1–F7 / H1·H2·H4 与 Q1–Q8 判定。

纯函数模块（输入文件/数据、输出 dict + markdown），供 CLI
``scripts/memory_growth_report.py`` 与回放框架（R6）共用。

口径声明（与 PRD 2.2/第七节一致）：
- 生产"命中率"默认口径 = H2 采纳率；H1 为分母口径（召回非空率）；
- H4 图路命中只进 growth 模板统计，不与 H1/H2 混算；
- E3 剂量安全区是"单例预载干扰数"口径，对生产全库规模仅方向性参照。
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# E3 剂量-响应的安全档位（部署剂量 8；16 条起纯语义崩塌）——仅方向性参照
_DOSE_SAFE = 8
_DOSE_RISK = 16


def load_events(events_path: Path | str, *, include_rotated: bool = True) -> list[dict]:
    """按序读事件（轮转旧代在前）；坏行跳过。"""
    path = Path(events_path)
    files: list[Path] = []
    if include_rotated:
        rotated = Path(str(path) + ".1")
        if rotated.exists():
            files.append(rotated)
    if path.exists():
        files.append(path)
    events: list[dict] = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    events.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
    return events


def load_snapshots(snapshot_dir: Path | str) -> list[dict]:
    """按文件名（时间戳前缀）排序读快照。"""
    directory = Path(snapshot_dir)
    if not directory.is_dir():
        return []
    out: list[dict] = []
    for f in sorted(directory.glob("*_growth_snapshot.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def load_growth_stats(growth_stats_path: Path | str | None) -> dict:
    if not growth_stats_path:
        return {}
    path = Path(growth_stats_path)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _date_of(ts: str) -> str:
    return str(ts or "")[:10]


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _latest(snapshots: list[dict]) -> dict | None:
    return snapshots[-1] if snapshots else None


# ── 漏斗 F1–F7 ───────────────────────────────────────────────────────────


def _build_funnel(events: list[dict]) -> dict:
    units_by_source: dict[str, set[str]] = defaultdict(set)
    annotated_promote: set[str] = set()
    annotated_decided: set[str] = set()
    submitted: set[str] = set()
    submitted_rejected: set[str] = set()
    node_of_unit: dict[str, list[str]] = defaultdict(list)  # life_event_id → node_ids
    created_nodes: list[str] = []
    created_node_ts: dict[str, int] = {}
    linked_nodes: set[str] = set()
    parent_linked_nodes: set[str] = set()
    node_edge_types: dict[str, set[str]] = defaultdict(set)
    recalled_nodes: set[str] = set()
    unit_session: dict[str, str] = {}
    node_unit: dict[str, str] = {}

    outcome_counts: dict[str, int] = defaultdict(int)
    for idx, e in enumerate(events):
        kind = e.get("event")
        if kind == "unit_created":
            uid = str(e.get("unit_id") or "")
            if uid:
                units_by_source[str(e.get("source") or "?")].add(uid)
                session = str(e.get("session_id") or "")
                if session:
                    unit_session[uid] = session
        elif kind == "unit_annotated":
            uid = str(e.get("unit_id") or "")
            if e.get("annotation_decided"):
                annotated_decided.add(uid)
            if e.get("promote_to_memory"):
                annotated_promote.add(uid)
            outcome_counts[str(e.get("outcome") or "?")] += 1
        elif kind == "promote_submitted":
            uid = str(e.get("unit_id") or "")
            submitted.add(uid)
            if not e.get("allowed"):
                submitted_rejected.add(uid)
        elif kind == "node_created":
            nid = str(e.get("node_id") or "")
            if nid:
                created_nodes.append(nid)
                created_node_ts[nid] = idx
                life_id = str(e.get("life_event_id") or "")
                if life_id:
                    node_of_unit[life_id].append(nid)
                    node_unit[nid] = life_id
        elif kind == "edge_added":
            for endpoint in (str(e.get("from_id") or ""), str(e.get("to_id") or "")):
                pos = created_node_ts.get(endpoint)
                if pos is not None and pos < idx:
                    linked_nodes.add(endpoint)
                    node_edge_types[endpoint].add(str(e.get("edge_type") or ""))
            to_id = str(e.get("to_id") or "")
            if (
                str(e.get("edge_type") or "") == "related_to"
                and to_id in created_node_ts
                and created_node_ts[to_id] < idx
            ):
                parent_linked_nodes.add(to_id)
        elif kind == "recall_recorded":
            nid = str(e.get("node_id") or "")
            if nid:
                recalled_nodes.add(nid)

    f1_units: set[str] = set().union(*units_by_source.values()) if units_by_source else set()
    f1 = len(f1_units)
    f2 = len(annotated_promote)
    f3 = len(submitted)
    f3_pass = len(submitted - submitted_rejected)
    f4_units = {u for u, ns in node_of_unit.items() if ns}
    f4 = sum(len(ns) for ns in node_of_unit.values())
    f5_any = len(linked_nodes)
    f5_parent = len(parent_linked_nodes)

    # F7：跨会话再命中——节点被创建会话以外的 session 检索命中（G3 核心证据）
    node_hit_sessions: dict[str, set[str]] = defaultdict(set)
    for e in events:
        if e.get("event") == "retrieval_performed":
            session = str(e.get("session_id") or "")
            if not session:
                continue
            for row in e.get("results") or []:
                if isinstance(row, dict):
                    nid = str(row.get("id") or "")
                else:
                    nid = str(row)
                if nid:
                    node_hit_sessions[nid].add(session)
    cross_session_nodes: set[str] = set()
    for nid, sessions in node_hit_sessions.items():
        life_id = node_unit.get(nid)
        home = unit_session.get(life_id or "") if life_id else None
        if home and sessions - {home}:
            cross_session_nodes.add(nid)

    f4_unit_ids = f4_units
    f6 = len({n for n in created_nodes if n in recalled_nodes})
    f7_pool = {n for n, life in node_unit.items() if life in f4_unit_ids}
    f7 = len({n for n in cross_session_nodes if n in f7_pool})

    conversions = {
        "F2/F1 标注擢升率": _ratio(f2, f1),
        "F3/F2 提交率": _ratio(f3, f2),
        "F4/F1 入图率": _ratio(f4, f1),
        "F4u/F2 单元入图率": _ratio(len(f4_unit_ids & {u for u in submitted}), f2),
        "F5/F4 建边率(任一边)": _ratio(f5_any, len(created_nodes)),
        "F5p/F4 选父率(related_to 父边)": _ratio(f5_parent, len(created_nodes)),
        "F6/F4 首次recall率": _ratio(f6, len(created_nodes)),
        "F7/F4 跨会话再命中率": _ratio(f7, len(f7_pool) or len(created_nodes)),
    }
    bottleneck = None
    valid = {k: v for k, v in conversions.items() if v is not None}
    if valid:
        bottleneck = min(valid.items(), key=lambda kv: kv[1])

    return {
        "F1_units_created": f1,
        "F1_by_source": {k: len(v) for k, v in sorted(units_by_source.items())},
        "F2_annotated_promote": f2,
        "F2_annotated_decided": len(annotated_decided),
        "F2_outcomes": dict(sorted(outcome_counts.items())),
        "F3_submitted": f3,
        "F3_filter_rejected": len(submitted_rejected),
        "F3_passed": f3_pass,
        "F4_nodes_created_from_units": f4,
        "F4_units_ingested": len(f4_unit_ids),
        "F5_nodes_linked_any": f5_any,
        "F5_nodes_with_parent_edge": f5_parent,
        "F6_nodes_recalled": f6,
        "F7_cross_session_rehit_nodes": f7,
        "F7_pool": len(f7_pool),
        "conversions": conversions,
        "bottleneck": {"stage": bottleneck[0], "rate": bottleneck[1]} if bottleneck else None,
        "_created_nodes_total": len(created_nodes),
    }


# ── 成长 G1–G5 ───────────────────────────────────────────────────────────


def _build_growth(events: list[dict], snapshots: list[dict]) -> dict:
    daily: dict[str, dict[str, int]] = defaultdict(
        lambda: {"units": 0, "nodes": 0, "edges": 0, "forgotten": 0, "recall": 0, "retrievals": 0}
    )
    edges_by_type: dict[str, int] = defaultdict(int)
    rumination_rewrites = 0
    rumination_edges = 0
    collapses = 0
    collapse_units_merged = 0
    for e in events:
        kind = e.get("event")
        day = _date_of(str(e.get("ts") or ""))
        if kind == "unit_created":
            daily[day]["units"] += 1
        elif kind == "node_created":
            daily[day]["nodes"] += 1
        elif kind == "edge_added":
            daily[day]["edges"] += 1
            edges_by_type[str(e.get("edge_type") or "?")] += 1
        elif kind == "node_forgotten":
            daily[day]["forgotten"] += int(e.get("count") or 0)
        elif kind == "recall_recorded":
            daily[day]["recall"] += 1
        elif kind == "retrieval_performed":
            daily[day]["retrievals"] += 1
        elif kind == "rumination_rewrite":
            rumination_rewrites += 1
            rumination_edges += int(e.get("new_edges") or 0)
        elif kind == "collapse":
            collapses += 1
            collapse_units_merged += len(e.get("participant_ids") or [])

    node_created_total = sum(d["nodes"] for d in daily.values())
    edge_added_total = sum(d["edges"] for d in daily.values())
    forgotten_total = sum(d["forgotten"] for d in daily.values())

    curve: list[dict] = []
    cum_nodes = cum_edges = 0
    for day in sorted(daily):
        row = daily[day]
        cum_nodes += row["nodes"] - row["forgotten"]
        cum_edges += row["edges"]
        curve.append(
            {
                "date": day,
                "units": row["units"],
                "nodes_created": row["nodes"],
                "edges_added": row["edges"],
                "forgotten": row["forgotten"],
                "retrievals": row["retrievals"],
                "cum_nodes_alive": cum_nodes,
                "cum_edges": cum_edges,
                "cum_edge_node_ratio": round(cum_edges / cum_nodes, 4) if cum_nodes else 0.0,
            }
        )

    snap_series = [
        {
            "ts": s.get("ts"),
            "node_count": s.get("node_count"),
            "edge_count": s.get("edge_count"),
            "edge_node_ratio": s.get("edge_node_ratio"),
            "avg_degree": s.get("avg_degree"),
            "orphan_rate": s.get("orphan_rate"),
            "tier": s.get("nodes_by_tier"),
            "vector_infra": s.get("vector_infra_enabled"),
        }
        for s in snapshots
    ]

    return {
        "G1_scale": {
            "units_created": sum(d["units"] for d in daily.values()),
            "nodes_created": node_created_total,
            "edges_added": edge_added_total,
            "nodes_forgotten": forgotten_total,
            "daily_curve": curve,
        },
        "G2_structure": {
            "edges_by_type": dict(sorted(edges_by_type.items())),
            "events_edge_node_ratio": _ratio(edge_added_total, node_created_total),
            "snapshot_series": snap_series,
            "latest": {
                k: _latest(snapshots).get(k) for k in ("node_count", "edge_count", "edge_node_ratio", "avg_degree", "orphan_rate")
            } if snapshots else None,
        },
        "G3_strength": {
            "recall_events": sum(d["recall"] for d in daily.values()),
            "recall_profile_latest": (_latest(snapshots) or {}).get("recall_count_profile"),
            "rehearsal_profile_latest": (_latest(snapshots) or {}).get("rehearsal_count_profile"),
        },
        "G4_reconstruction": {
            "rumination_rewrites": rumination_rewrites,
            "rumination_new_edges": rumination_edges,
            "collapses": collapses,
            "collapse_units_merged": collapse_units_merged,
        },
        "G5_decay": {
            "forgotten": forgotten_total,
            "forget_rate": _ratio(forgotten_total, node_created_total),
            "survival_ratio": (
                round(1 - forgotten_total / node_created_total, 4) if node_created_total else None
            ),
        },
    }


# ── 命中 H1 / H2 / H4 ────────────────────────────────────────────────────


def _build_retrieval(events: list[dict], growth_stats: dict) -> dict:
    by_entry: dict[str, dict] = defaultdict(lambda: {"total": 0, "nonempty": 0})
    total = 0
    nonempty = 0
    for e in events:
        if e.get("event") != "retrieval_performed":
            continue
        entry = str(e.get("entry") or "?")
        total += 1
        by_entry[entry]["total"] += 1
        results = e.get("results") or []
        if results or int(e.get("result_count") or 0) > 0:
            nonempty += 1
            by_entry[entry]["nonempty"] += 1

    adoption_events = 0
    adopted_events = 0
    injected_total = 0
    spilled_total = 0
    for e in events:
        if e.get("event") != "adoption":
            continue
        adoption_events += 1
        injected = int(e.get("injected_count") or 0)
        injected_total += injected
        spilled_total += int(e.get("spilled_count") or 0)
        if injected > 0:
            adopted_events += 1

    h4_templates = {
        tid: {
            "uses": s.get("uses"),
            "reports": s.get("reports"),
            "hit_count": s.get("hit_count"),
            "avg_score": round(s.get("score_sum", 0) / s["reports"], 4) if s.get("reports") else 0.0,
        }
        for tid, s in (growth_stats or {}).items()
        if isinstance(s, dict)
    }
    h4_with_reports = {t: v for t, v in h4_templates.items() if (v["reports"] or 0) > 0}

    return {
        "H1_retrievals_total": total,
        "H1_nonempty_rate": _ratio(nonempty, total),
        "by_entry": {k: {**v, "nonempty_rate": _ratio(v["nonempty"], v["total"])} for k, v in sorted(by_entry.items())},
        "H2_adoption_events": adoption_events,
        "H2_adopted_rate": _ratio(adopted_events, adoption_events),
        "H2_avg_injected_per_turn": round(injected_total / adoption_events, 3) if adoption_events else None,
        "H2_avg_spilled_per_turn": round(spilled_total / adoption_events, 3) if adoption_events else None,
        "H4_template_stats": h4_with_reports,
    }


# ── Q1–Q8 判定 ───────────────────────────────────────────────────────────


def _build_questions(funnel: dict, growth: dict, retrieval: dict, snapshots: list[dict]) -> dict:
    conv = funnel["conversions"]

    # Q2：网络变密还是只变大（需要 ≥2 个时点：快照序列或日曲线）
    ratios: list[float] = [s["edge_node_ratio"] for s in growth["G2_structure"]["snapshot_series"] if s["edge_node_ratio"] is not None]
    densifying: bool | None = None
    if len(ratios) >= 2:
        # 含 0 起步：0 → 正增长本身就是"变密"的证据
        densifying = ratios[-1] > ratios[0]
    else:
        curve = growth["G1_scale"]["daily_curve"]
        valid = [c["cum_edge_node_ratio"] for c in curve if c["cum_nodes_alive"] > 0]
        if len(valid) >= 2:
            densifying = valid[-1] > valid[0]

    # Q3：用进废退是否发生
    recall_profile = growth["G3_strength"]["recall_profile_latest"] or {}
    q3_evidence = {
        "recall_events": growth["G3_strength"]["recall_events"],
        "recalled_nodes": funnel["F6_nodes_recalled"],
        "created_nodes": funnel["_created_nodes_total"],
        "first_recall_rate": conv.get("F6/F4 首次recall率"),
        "multi_recall_share_latest_snapshot": recall_profile.get("multi_share"),
    }
    q3 = bool(q3_evidence["recalled_nodes"] > 0 and (q3_evidence["first_recall_rate"] or 0) > 0)

    # Q5：遗忘速率
    g5 = growth["G5_decay"]

    # Q6：剂量安全区（方向性参照）
    latest = _latest(snapshots) or {}
    node_count = latest.get("node_count")
    if node_count is None:
        node_count = funnel["_created_nodes_total"] - (g5["forgotten"] or 0)
    if node_count is None or node_count <= _DOSE_SAFE:
        band = "safe"
    elif node_count < _DOSE_RISK:
        band = "caution"
    else:
        band = "risk"

    # Q7：tier 分布（short 占比 + 膨胀趋势）
    tier_series = [s.get("nodes_by_tier") or {} for s in snapshots]
    short_share = None
    short_trend = None
    def _short_share(t: dict) -> float | None:
        total = sum(t.values()) if t else None
        return round(t.get("short_term", 0) / total, 4) if total else None
    if tier_series:
        short_share = _short_share(tier_series[-1])
        if len(tier_series) >= 2:
            first, last = _short_share(tier_series[0]), _short_share(tier_series[-1])
            if first is not None and last is not None:
                short_trend = round(last - first, 4)

    # Q8：模板统计分化
    h4 = retrieval["H4_template_stats"]
    scored = [v["avg_score"] for v in h4.values()]
    q8 = None
    if len(scored) >= 2:
        q8 = {
            "templates_with_reports": len(scored),
            "max_avg": max(scored),
            "min_avg": min(scored),
            "differentiated": (max(scored) - min(scored)) > 0.05,
        }

    return {
        "Q1_funnel_bottleneck": funnel["bottleneck"],
        "Q1_conversion_rates": conv,
        "Q2_network_densifying": {
            "answer": densifying,
            "edge_node_ratio_series": ratios or None,
            "evidence": "快照/日曲线的边/节点比首尾对比；null=时点不足无法判定",
        },
        "Q3_use_it_or_lose_it": {"answer": q3, "evidence": q3_evidence},
        "Q4_cross_session_recall": {
            "answer": (funnel["F7_cross_session_rehit_nodes"] > 0),
            "cross_session_rehit_nodes": funnel["F7_cross_session_rehit_nodes"],
            "pool": funnel["F7_pool"],
            "rate": conv.get("F7/F4 跨会话再命中率"),
        },
        "Q5_forgetting": {
            "forgotten": g5["forgotten"],
            "forget_rate": g5["forget_rate"],
            "survival_ratio": g5["survival_ratio"],
        },
        "Q6_distractor_dose": {
            "node_count": node_count,
            "band": band,
            "caveat": "E3 安全区为单例预载干扰数口径（8/16），对生产全库规模仅方向性参照",
        },
        "Q7_tier_distribution": {
            "latest_tier": tier_series[-1] if tier_series else None,
            "short_term_share": short_share,
            "short_term_share_delta": short_trend,
            "swelling": bool(short_trend is not None and short_trend > 0),
        },
        "Q8_template_differentiation": q8,
    }


# ── 汇总与渲染 ───────────────────────────────────────────────────────────


def build_growth_report(
    events: list[dict],
    snapshots: list[dict],
    *,
    growth_stats: dict | None = None,
) -> dict:
    funnel = _build_funnel(events)
    growth = _build_growth(events, snapshots)
    retrieval = _build_retrieval(events, growth_stats or {})
    questions = _build_questions(funnel, growth, retrieval, snapshots)
    ts_list = [str(e.get("ts") or "") for e in events if e.get("ts")]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "events": len(events),
            "snapshots": len(snapshots),
            "first_ts": min(ts_list) if ts_list else None,
            "last_ts": max(ts_list) if ts_list else None,
        },
        "funnel": funnel,
        "growth": growth,
        "retrieval": retrieval,
        "questions": questions,
    }


def _md_table(rows: list[tuple], header: tuple) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for row in rows:
        lines.append("| " + " | ".join("—" if v is None else str(v) for v in row) + " |")
    return "\n".join(lines)


def render_report_md(metrics: dict) -> str:
    funnel = metrics["funnel"]
    growth = metrics["growth"]
    retrieval = metrics["retrieval"]
    q = metrics["questions"]
    win = metrics["window"]

    out: list[str] = ["# 记忆成长观测报告", ""]
    out.append(
        f"- 生成时间：{metrics['generated_at']}；事件 {win['events']} 条 / 快照 {win['snapshots']} 份"
        f"（{win['first_ts']} → {win['last_ts']}）"
    )
    out.append("- 口径：H1=检索非空率，H2=采纳率（注入 Speak），H4=图路命中（growth 模板统计）；离线 Hit@k 与生产口径不可直接互比")

    out += ["", "## 一、擢升漏斗 F1–F7", ""]
    out.append(
        _md_table(
            [
                ("F1 体验单元产生", funnel["F1_units_created"], ""),
                ("F2 标注擢升（promote=true）", funnel["F2_annotated_promote"], funnel["conversions"].get("F2/F1 标注擢升率")),
                ("F3 提交（经 sleep filter）", f"{funnel['F3_passed']}/{funnel['F3_submitted']}", funnel["conversions"].get("F3/F2 提交率")),
                ("F4 入图节点/单元", f"{funnel['F4_nodes_created_from_units']}/{funnel['F4_units_ingested']}", funnel["conversions"].get("F4/F1 入图率")),
                ("F5 建边（任一/父边）", f"{funnel['F5_nodes_linked_any']}/{funnel['F5_nodes_with_parent_edge']}", funnel["conversions"].get("F5/F4 建边率(任一边)")),
                ("F6 首次 recall", funnel["F6_nodes_recalled"], funnel["conversions"].get("F6/F4 首次recall率")),
                ("F7 跨会话再命中", funnel["F7_cross_session_rehit_nodes"], funnel["conversions"].get("F7/F4 跨会话再命中率")),
            ],
            ("漏斗级", "计数", "转化率"),
        )
    )
    if funnel["F1_by_source"]:
        out.append(
            f"\nF1 按来源：{funnel['F1_by_source']}；F2 判定 outcome 分布：{funnel['F2_outcomes']}"
        )

    out += ["", "## 二、成长五维 G1–G5", ""]
    g1 = growth["G1_scale"]
    out.append(
        f"- **G1 规模**：单元 {g1['units_created']}，节点 {g1['nodes_created']}，边 {g1['edges_added']}，遗忘 {g1['nodes_forgotten']}"
    )
    g2 = growth["G2_structure"]
    latest = g2["latest"] or {}
    out.append(
        f"- **G2 结构**：边类型 {g2['edges_by_type']}；最新快照 节点 {latest.get('node_count')} / 边 {latest.get('edge_count')}"
        f" / 边节点比 {latest.get('edge_node_ratio')} / 平均度 {latest.get('avg_degree')} / 孤儿率 {latest.get('orphan_rate')}"
    )
    g3 = growth["G3_strength"]
    out.append(
        f"- **G3 强度**：recall 事件 {g3['recall_events']}；最新快照 recall 分布 {g3['recall_profile_latest']}；rehearsal 分布 {g3['rehearsal_profile_latest']}"
    )
    g4 = growth["G4_reconstruction"]
    out.append(
        f"- **G4 重构**：反刍改写 {g4['rumination_rewrites']} 次（新增边 {g4['rumination_new_edges']}）；交会折叠 {g4['collapses']} 次（合并 {g4['collapse_units_merged']} 单元）"
    )
    g5 = growth["G5_decay"]
    out.append(f"- **G5 遗忘**：软删 {g5['forgotten']}（forget_rate {g5['forget_rate']}，存活率 {g5['survival_ratio']}）")
    curve = g1["daily_curve"]
    if curve:
        out += ["", "### 每日曲线", ""]
        out.append(
            _md_table(
                [
                    (
                        c["date"], c["units"], c["nodes_created"], c["edges_added"],
                        c["forgotten"], c["retrievals"], c["cum_nodes_alive"],
                        c["cum_edges"], c["cum_edge_node_ratio"],
                    )
                    for c in curve
                ],
                ("日期", "单元", "新节点", "新边", "遗忘", "检索", "存活节点(累计)", "累计边", "边/节点比"),
            )
        )

    out += ["", "## 三、命中 H1 / H2 / H4", ""]
    out.append(
        f"- **H1**：检索 {retrieval['H1_retrievals_total']} 次，非空率 {retrieval['H1_nonempty_rate']}"
    )
    if retrieval["by_entry"]:
        out.append(
            "- 分入口："
            + "；".join(
                f"{k} {v['total']} 次（非空 {v['nonempty_rate']}）"
                for k, v in retrieval["by_entry"].items()
            )
        )
    out.append(
        f"- **H2 采纳**：{retrieval['H2_adoption_events']} 轮，采纳率 {retrieval['H2_adopted_rate']}，"
        f"平均注入 {retrieval['H2_avg_injected_per_turn']} 条/轮（溢出 {retrieval['H2_avg_spilled_per_turn']}）"
    )
    h4 = retrieval["H4_template_stats"]
    out.append(
        f"- **H4 图路命中（growth 模板统计）**：{len(h4)} 个模板有反馈"
        + (
            "（" + "；".join(f"{t}: avg={v['avg_score']} hits={v['hit_count']}/{v['reports']}" for t, v in h4.items()) + "）"
            if h4
            else "（尚无反馈积累）"
        )
    )

    out += ["", "## 四、设计合理性判定 Q1–Q8", ""]
    out.append(
        _md_table(
            [
                ("Q1 擢升瓶颈", (q["Q1_funnel_bottleneck"] or {}).get("stage"), (q["Q1_funnel_bottleneck"] or {}).get("rate")),
                ("Q2 网络变密（否=只变大）", q["Q2_network_densifying"]["answer"], f"序列 {q['Q2_network_densifying']['edge_node_ratio_series']}"),
                ("Q3 用进废退发生", q["Q3_use_it_or_lose_it"]["answer"], f"首次recall率 {q['Q3_use_it_or_lose_it']['evidence']['first_recall_rate']}"),
                ("Q4 跨会话想起", q["Q4_cross_session_recall"]["answer"], f"{q['Q4_cross_session_recall']['cross_session_rehit_nodes']}/{q['Q4_cross_session_recall']['pool']}（rate {q['Q4_cross_session_recall']['rate']}）"),
                ("Q5 遗忘速率", f"存活率 {q['Q5_forgetting']['survival_ratio']}", f"forget_rate {q['Q5_forgetting']['forget_rate']}"),
                ("Q6 剂量安全区", q["Q6_distractor_dose"]["band"], f"库规模 {q['Q6_distractor_dose']['node_count']}（{q['Q6_distractor_dose']['caveat']}）"),
                ("Q7 tier 单调膨胀", q["Q7_tier_distribution"]["swelling"], f"short 占比 {q['Q7_tier_distribution']['short_term_share']}（Δ {q['Q7_tier_distribution']['short_term_share_delta']}）"),
                ("Q8 模板统计分化", (q["Q8_template_differentiation"] or {}).get("differentiated"), (q["Q8_template_differentiation"] or {}).get("max_avg")),
            ],
            ("判定问题", "结论", "关键证据"),
        )
    )
    out += ["", "## 五、快照序列", ""]
    series = growth["G2_structure"]["snapshot_series"]
    if series:
        out.append(
            _md_table(
                [
                    (
                        str(s["ts"])[:19], s["node_count"], s["edge_count"],
                        s["edge_node_ratio"], s["avg_degree"], s["orphan_rate"],
                        s["vector_infra"],
                    )
                    for s in series
                ],
                ("时点", "节点", "边", "边/节点比", "平均度", "孤儿率", "向量基建"),
            )
        )
    else:
        out.append("（无快照——sleep 尚未运行，或 telemetry 在运行期被关闭）")
    out.append("")
    return "\n".join(out)


def write_report(out_dir: Path | str, metrics: dict) -> Path:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    report_path = directory / "report.md"
    report_path.write_text(render_report_md(metrics), encoding="utf-8")
    return report_path
