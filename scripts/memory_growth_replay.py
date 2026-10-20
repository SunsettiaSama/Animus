#!/usr/bin/env python3
"""记忆成长回放（R6 模式甲）：把多轮会话灌入**完整生产管线**并产出 Q1–Q8 判定报告。

与 evals 基座的区别：这里驱动真实装配——``build_memory_service``（JSON 后端）、
Life 体验编排器（擢升门/热日志/交会折叠）、memory worker、sleep 巩固（含快照）、
Speak 入口 B 点查询与入口 D recall——观测全部来自 R1–R3 事件流水。

剧本含跨会话检查点（probe）：后续会话的提问应想起早期会话写入的记忆，
从而在生产形态下计算**有 ground truth 的 Hit@k**（打通离线/生产口径）。

LLM 两种模式：
  --llm fake（默认）：确定性伪 LLM（路由/归档选父/Skill1 编写），离线可复现；
  --llm real        ：走 config/llm_core 的生产 LLM（需可用 API 配置）。

示例（cwd = 仓库根）::

    python scripts/memory_growth_replay.py --tag smoke
    python scripts/memory_growth_replay.py --sessions-extra 2 --llm real
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ── 剧本（模式甲）：跨会话检查点 = 生产形态的 ground truth ────────────────


@dataclass
class ReplayTurn:
    user_text: str
    salience: float = 0.4
    promote: bool = False
    annotate: bool = False
    probe_anchors: list[str] = field(default_factory=list)  # 非空 = 探针轮（应想起锚点）


@dataclass
class ReplaySession:
    session_id: str
    turns: list[ReplayTurn]


def builtin_scenarios() -> list[ReplaySession]:
    """6 会话剧本：前 3 会话写入（部分轮显式标注擢升），后 3 会话跨会话探针。"""
    return [
        ReplaySession("replay-s1", [
            ReplayTurn("我今天领养了一只橘猫，取名叫年糕", 0.8, promote=True, annotate=True),
            ReplayTurn("它特别怕吹风机，一开就躲沙发底下", 0.6),
            ReplayTurn("对了，我下周三要去拔智齿", 0.7, promote=True, annotate=True),
            ReplayTurn("最近的雨下个没完", 0.2),
        ]),
        ReplaySession("replay-s2", [
            ReplayTurn("我把阳台改成了小花园，种了薄荷和罗勒", 0.7, promote=True, annotate=True),
            ReplayTurn("年糕今天把我的多肉碰倒了两盆", 0.6),
            ReplayTurn("我升职了！成了小组负责人", 0.9, promote=True, annotate=True),
        ]),
        ReplaySession("replay-s3", [
            ReplayTurn("我开始学滑板了，摔了两次", 0.5),
            ReplayTurn("我妈生日快到了，她喜欢山茶花", 0.8, promote=True, annotate=True),
            ReplayTurn("周三拔牙之后脸肿了两天", 0.4),
        ]),
        ReplaySession("replay-s4", [
            ReplayTurn("还记得我养的猫吗，它叫什么来着", 0.5, probe_anchors=["年糕"]),
            ReplayTurn("我阳台种的香料长势怎么样你还记得吗", 0.5, probe_anchors=["薄荷", "罗勒"]),
        ]),
        ReplaySession("replay-s5", [
            ReplayTurn("我上次跟你说的工作上的好事是什么", 0.5, probe_anchors=["升职", "负责人"]),
            ReplayTurn("我妈生日我该送什么花，你记得她的喜好吗", 0.5, probe_anchors=["山茶花"]),
        ]),
        ReplaySession("replay-s6", [
            ReplayTurn("我拔智齿是哪天来着", 0.5, probe_anchors=["周三", "智齿"]),
            ReplayTurn("我在学的那个新运动是什么", 0.5, probe_anchors=["滑板"]),
        ]),
    ]


# ── 确定性伪 LLM（--llm fake） ────────────────────────────────────────────


class ReplayFakeLLM:
    """按 system 提示分发的确定性 LLM：路由 / 归档选父 / Skill1 编写。"""

    def __init__(self) -> None:
        self.calls = 0

    def generate_messages(self, messages) -> str:
        self.calls += 1
        system = str(messages[0].content)
        user = str(messages[1].content) if len(messages) > 1 else ""
        if "记忆路由系统" in system:
            return json.dumps({"network": "event", "reason": "replay-route"}, ensure_ascii=False)
        if "记忆归档系统" in system:
            return self._archive(user)
        if "体验编写器" in system:
            return json.dumps(
                {
                    "perception": "",
                    "narration": "",
                    "action_content": "",
                    "emotion_label": "平静",
                    "valence": "neutral",
                    "salience": 0.6,
                    "salience_note": "",
                },
                ensure_ascii=False,
            )
        return "{}"

    @staticmethod
    def _archive(user: str) -> str:
        m = re.search(r"语义候选父节点：\s*\n\s*1\.\s*id=(\S+)\s+score", user)
        parent = m.group(1) if m else "none"
        raw = re.search(r"体验原文：\s*\n(.+)", user)
        focus = (raw.group(1).strip()[:12] if raw else "回放体验")
        return json.dumps(
            {
                "focus": focus,
                "subjective_statement": (raw.group(1).strip()[:80] if raw else focus),
                "label": "",
                "parent_node_id": parent,
                "parent_reason": "replay-semantic-place" if parent != "none" else "",
                "emotion": "平静",
                "valence": "neutral",
                "base_activation": 0.6,
            },
            ensure_ascii=False,
        )


# ── 最小 Presence 替身（真实 PresenceState，其余面收窄） ──────────────────


class MinimalPresence:
    def __init__(self):
        from agent.soul.presence.state.presence_state import PresenceState

        self._PresenceState = PresenceState
        self.states: dict[str, object] = {}

    def _state(self, session_id: str):
        return self.states.setdefault(session_id, self._PresenceState())

    def snapshot(self, session_id: str):
        return SimpleNamespace(state=self._state(session_id))

    def ingest(self, event) -> None:
        # 回放不驱动 Presence 内部演化；工作记忆经 set_working_memory 进 affect
        pass

    def set_working_memory(self, session_id: str, text: str) -> None:
        state = self._state(session_id)
        if text.strip():
            state.affect.append(f"（工作记忆）{text[:120]}")

    def on_unit_ingested(self, unit, log) -> None:  # 回放不驱动 Presence 演化
        pass

    def sync_life_bundle(self, bundle) -> dict:
        return {}

    def bind_life_experience(self, stack) -> None:
        pass


class SerialWorker:
    """同步串行 worker：回放要确定性（无跨线程时序）。"""

    def __init__(self):
        self.executed = 0

    def enqueue(self, fn) -> None:
        self.executed += 1
        fn()


# ── 驱动器 ───────────────────────────────────────────────────────────────


def run_replay(
    *,
    workspace: Path,
    llm,
    scenarios: list[ReplaySession],
) -> dict:
    from agent.soul.memory.telemetry import (
        MemoryTelemetryConfig,
        configure_memory_telemetry,
        get_memory_telemetry,
        reset_memory_telemetry,
    )
    from agent.soul.memory.facade.build import build_memory_service
    from agent.soul.memory.io.life.adapter import LifeMemoryPortAdapter
    from agent.soul.life.experience.hub.stack import LifeExperienceStack
    from agent.soul.memory.domain import ActivationCue

    configure_memory_telemetry(
        MemoryTelemetryConfig(enabled=True, dir=str(workspace / "telemetry"))
    )
    try:
        svc = build_memory_service(
            llm, storage_backend="json", json_root=str(workspace / "soul_db")
        )
        svc.set_worker(SerialWorker())

        presence = MinimalPresence()
        stack = LifeExperienceStack(
            str(workspace / "life"),
            memory_port=LifeMemoryPortAdapter(svc.life_io),
        )
        stack.bind_presence(presence)

        probes: list[dict] = []
        interactor = "replay-user"

        for s_idx, session in enumerate(scenarios):
            # 同一用户跨会话：把 interactor 钉在 dialogue session 上（等价生产
            # 的 channel 绑定；不钉的话 anchor 会回退 session_id，归档侧
            # interactor 过滤会挡死跨会话选父——这本身就是一个可观测发现）
            state = stack.dialogue.open_session(session.session_id)
            state.session.interactor_id = interactor
            for t_idx, turn in enumerate(session.turns):
                is_probe = bool(turn.probe_anchors)
                stack.record_dialogue_turn(
                    session_id=session.session_id,
                    user_text=turn.user_text,
                    agent_text="嗯，我在听，你继续说。",
                    salience=turn.salience,
                    promote_to_memory=turn.promote,
                    annotation_decided=turn.annotate,
                )
                # 入口 B：Speak 点查询（生产路径；探针轮的命中即 ground truth 判定）
                result = svc.emergence.spread.query_hybrid_sync(
                    ActivationCue(
                        session_id=session.session_id,
                        interactor_id=interactor,
                        user_text=turn.user_text,
                        agent_text="",
                        turn_index=t_idx,
                    )
                )
                if is_probe:
                    merged = " || ".join(result.merged_lines())
                    # 入口 D / A 互补判定：recall 与工具检索
                    recalled = " || ".join(svc.recall(turn.user_text, top_k=5).entries)
                    searched = json.dumps(
                        svc.search("hybrid", query=turn.user_text, top_k=5),
                        ensure_ascii=False,
                    )
                    probes.append(
                        {
                            "session_id": session.session_id,
                            "turn_index": t_idx,
                            "query": turn.user_text,
                            "anchors": turn.probe_anchors,
                            "hit_point_query": any(a in merged for a in turn.probe_anchors),
                            "hit_recall": any(a in recalled for a in turn.probe_anchors),
                            "hit_search": any(a in searched for a in turn.probe_anchors),
                            "any_hit": any(
                                a in (merged + recalled + searched) for a in turn.probe_anchors
                            ),
                        }
                    )
            stack.close_dialogue(session.session_id)
            # 每会话后跑一次 sleep 巩固 → 遗忘/聚类/快照（R2.1 时点序列）
            svc.run_sleep(tick_id=f"replay:{s_idx + 1}")

        telemetry = get_memory_telemetry()
        telemetry.flush(timeout=10.0)

        # ground-truth Hit@k（模式甲核心产出）
        hit_any = sum(1 for p in probes if p["any_hit"])
        hit_point = sum(1 for p in probes if p["hit_point_query"])
        hit_recall = sum(1 for p in probes if p["hit_recall"])
        hit_search = sum(1 for p in probes if p["hit_search"])
        ground_truth = {
            "probes": len(probes),
            "hit_any": hit_any,
            "hit_rate_any": round(hit_any / len(probes), 4) if probes else None,
            "hit_rate_point_query": round(hit_point / len(probes), 4) if probes else None,
            "hit_rate_recall": round(hit_recall / len(probes), 4) if probes else None,
            "hit_rate_search": round(hit_search / len(probes), 4) if probes else None,
            "detail": probes,
        }
        return ground_truth
    finally:
        reset_memory_telemetry()


def build_final_report(workspace: Path, out_dir: Path, ground_truth: dict) -> Path:
    from agent.soul.memory.telemetry.report import (
        build_growth_report,
        load_events,
        load_growth_stats,
        load_snapshots,
        render_report_md,
        write_report,
    )

    telemetry_dir = workspace / "telemetry"
    events = load_events(telemetry_dir / "memory_events.jsonl")
    snapshots = load_snapshots(telemetry_dir / "snapshots")
    growth_stats = load_growth_stats(".react/retrieval/growth_stats.json")
    metrics = build_growth_report(events, snapshots, growth_stats=growth_stats)
    metrics["ground_truth_hit_at_k"] = ground_truth

    report_path = write_report(out_dir, metrics)
    # 追加模式甲专属段落（ground truth + 口径）
    md_extra = [
        "",
        "## 六、跨会话 ground-truth 命中（模式甲检查点）",
        "",
        f"- 探针 {ground_truth['probes']} 条：任意入口命中 {ground_truth['hit_any']}"
        f"（Hit@k={ground_truth['hit_rate_any']}）",
        f"- 分入口：点查询 {ground_truth['hit_rate_point_query']}"
        f" / recall {ground_truth['hit_rate_recall']}"
        f" / 工具检索 {ground_truth['hit_rate_search']}",
        "- 口径：锚点为早期会话写入记忆的原文切片，判定为字符串包含（与离线 L2 同硬度）",
        "",
    ]
    with open(report_path, "a", encoding="utf-8") as f:
        f.write("\n".join(md_extra))
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="记忆成长回放（R6 模式甲）")
    parser.add_argument("--tag", default="", help="run 标签（默认时间戳）")
    parser.add_argument("--workspace", default="", help="工作区目录（默认 .react/replay/<tag>）")
    parser.add_argument("--out-root", default="results/memory_growth", help="报告输出根目录")
    parser.add_argument("--llm", choices=["fake", "real"], default="fake")
    args = parser.parse_args()

    tag = args.tag.strip() or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    workspace = Path(args.workspace) if args.workspace else ROOT / ".react" / "replay" / tag

    if args.llm == "fake":
        llm = ReplayFakeLLM()
    else:
        try:
            from infra.llm import build_default_llm  # type: ignore

            llm = build_default_llm()
        except Exception as exc:  # pragma: no cover
            print(f"[replay] real LLM 不可用：{exc}", file=sys.stderr)
            return 2

    print(f"[replay] 工作区：{workspace}")
    ground_truth = run_replay(workspace=workspace, llm=llm, scenarios=builtin_scenarios())
    out_dir = Path(args.out_root) / tag
    report_path = build_final_report(workspace, out_dir, ground_truth)

    print(
        f"[replay] ground-truth Hit@k={ground_truth['hit_rate_any']}"
        f"（{ground_truth['hit_any']}/{ground_truth['probes']} 探针）"
    )
    print(f"[replay] 报告：{report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
