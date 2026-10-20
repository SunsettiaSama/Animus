#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""端到端演示：《星陨之痕》无头运行 → 感知协议层 → life 入账 → 守灯人 NPC 对话。

数据流：
  node demos/metroidvania/perception/harness.js（无头跑完整局，含与 NPC 交谈）
    → MetroidvaniaBridge（NDJSON）
    → PerceptionBus（翻译：视觉模型 > 规则叙事）
    → life：GamePerceptionInbound → ExperienceUnit(source=game) → 虚拟账本
    → speak：npc_talk → SpeakService.run_turn → 台词回注游戏弹窗

用法（仓库根目录执行）：
  python scripts/starfall_perception_demo.py                # 离线（脚本 LLM，零依赖网络）
  python scripts/starfall_perception_demo.py --live         # NPC 用真 LLM（config/llm_core/config.yaml）
  python scripts/starfall_perception_demo.py --keep         # life 目录保留（默认用临时目录）
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def _load_live_llm():
    from config import paths
    from config.llm_core.config import LLMConfig
    from infra.llm.llm import LLM

    cfg = LLMConfig.from_yaml(paths.llm_config_yaml)
    if not (cfg.model and cfg.api_key and cfg.base_url):
        raise SystemExit("--live 需要可用的 config/llm_core/config.yaml（model/api_key/base_url）")
    return LLM(cfg)


def main() -> int:
    parser = argparse.ArgumentParser(description="星陨之痕 × 感知协议层 端到端演示")
    parser.add_argument("--live", action="store_true", help="NPC 使用真 LLM（默认离线脚本 LLM）")
    parser.add_argument("--keep", action="store_true", help="保留 life 目录（默认临时目录）")
    parser.add_argument("--life-dir", default="", help="指定 life 目录")
    parser.add_argument("--scenario", default="story", help="harness 剧本（默认 story）")
    args = parser.parse_args()

    _utf8_stdio()
    from agent.perception.bus import PerceptionBus  # noqa: F401 — 触发包导入自检
    from agent.perception.gamebridge import MetroidvaniaBridge, NpcDialogueBridge
    from agent.perception.gamebridge.metroidvania import demo_available
    from agent.perception.narrate import RuleNarrator
    from agent.perception.runtime import build_lite_runtime, drive_bridge
    from agent.perception.vision import load_vision_narrator

    if not demo_available():
        raise SystemExit("未找到 demos/metroidvania（请在仓库根目录运行）")

    life_dir = args.life_dir or (tempfile.mkdtemp(prefix="perception-demo-") if not args.keep
                                 else str(_REPO_ROOT / ".react" / "perception-demo"))
    Path(life_dir).mkdir(parents=True, exist_ok=True)

    # 翻译器：视觉模型（若 vision.yaml 启用）> 规则叙事；NPC 大脑：--live 用真模型
    translator = load_vision_narrator() or RuleNarrator()
    llm = _load_live_llm() if args.live else None

    runtime = build_lite_runtime(life_dir, llm=llm, translator=translator)
    npc_bridge = NpcDialogueBridge(
        runtime.speak_turn,
        npc_name=runtime.npc_name,
        session_id=runtime.session_id,
        channel_id=runtime.channel_id,
    )

    print("=" * 72)
    print("感知协议层 · 端到端演示")
    print(f"  life 目录   {life_dir}")
    print(f"  事件翻译器  {runtime.bus.translator.name}{'（视觉模型未启用，规则兜底）' if translator.name == 'rule' else ''}")
    print(f"  NPC 大脑    {'真 LLM' if llm is not None else '离线脚本 LLM'}")
    print("=" * 72)

    bridge = MetroidvaniaBridge(scenario=args.scenario)
    try:
        summary = drive_bridge(
            bridge=bridge,
            bus=runtime.bus,
            npc_bridge=npc_bridge,
            on_packet=lambda p: print(f"  [感知|{p.translator}] {p.narrative}"),
        )
    finally:
        bridge.stop()

    # ── 结果汇报 ──
    print("\n" + "=" * 72)
    print("① 游戏事件（harness → 协议层）")
    for kind, count in summary.events.most_common():
        print(f"   {kind:<18} ×{count}")
    print(f"   harness errors: {summary.errors}")

    print("\n② 守灯人台词（speak 回注游戏）")
    for line in summary.npc_lines:
        print(f"   「{line}」")
    for line in summary.reactive_lines:
        print(f"   （主动）「{line}」")

    print("\n③ life 入账（游戏亲历 → ExperienceUnit）")
    units = runtime.stack.log.recent()
    by_source: dict[str, int] = {}
    for unit in units:
        by_source[unit.source] = by_source.get(unit.source, 0) + 1
    print(f"   热日志单元：{len(units)} 个，按 source 分布：{by_source}")
    for unit in units[-5:]:
        print(f"   [{unit.source}] {unit.situation.narration[:60]}")

    from agent.soul.life.virtual.chronicle import VirtualChronicleStore

    chronicle = VirtualChronicleStore(life_dir).recent_days(days=1)
    game_entries = [e for e in chronicle if e.kind.value == "game_event"]
    print(f"\n④ 虚拟账本 game_event 条目：{len(game_entries)}")
    for entry in game_entries[-5:]:
        print(f"   [{entry.kind.value}] {entry.summary[:60]}")

    print("\n⑤ speak 侧读到的游戏事件简报（life 事件口）")
    for brief in runtime.bus.game_event_briefs():
        print(f"   [{brief['phase']}] {brief['intention']}——{brief['narrative'][:50]}")

    print("\n⑥ NPC 对话作为 dialogue 经验（speak → life 出站；会话闭合时落账）")
    closed = runtime.stack.close_dialogue(runtime.session_id)
    if closed is not None:
        print(f"   对话经验已落账：[{closed.source}] {closed.situation.narration[:70]}")
    else:
        print("   （无对话经验落账：会话为空）")

    ok = (
        summary.errors == 0
        and summary.events.get("game_start", 0) >= 1
        and summary.events.get("npc_talk", 0) >= 1
        and len(summary.npc_lines) >= 1
        and any(u.source == "game" for u in units)
    )
    print("\n" + ("✅ 端到端链路跑通" if ok else "❌ 链路不完整，检查上方日志"))
    if not args.keep and not args.life_dir:
        shutil.rmtree(life_dir, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
