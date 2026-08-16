#!/usr/bin/env python3
"""角色侧真实 LLM 冒烟：看新提示词下能否正常扮演（主体性 / 接话抉择 / 不全盘附和）。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


SCENARIOS = (
    {
        "id": "busy_interrupt",
        "title": "打断手头事：期待拖一拖 / 一边做一边回",
        "user": "在吗在吗！快回我，你现在到底在干嘛？",
    },
    {
        "id": "plot_relevant",
        "title": "贴剧情提问：期待推进大纲，不全盘附和",
        "user": "别拧了，直接撬开不更快？听我的，用力撬。",
    },
    {
        "id": "unwanted_chat",
        "title": "不合时宜闲聊：期待短回或不愿搭话",
        "user": "哎你晚上想吃火锅还是烧烤？咱们约一下呗～",
    },
)


def _sep(title: str) -> None:
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}", flush=True)


def _load_llm(args: argparse.Namespace):
    from config.llm_core.config import LLMConfig
    from infra.llm.llm import OpenAILLM

    cfg_path = ROOT / "config" / "llm_core" / "config.yaml"
    cfg = LLMConfig.from_yaml(str(cfg_path)) if cfg_path.is_file() else LLMConfig()
    api_key = (
        args.api_key
        or os.environ.get("SPEAK_SMOKE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or cfg.api_key
        or ""
    ).strip()
    model = (args.model or os.environ.get("SPEAK_SMOKE_MODEL") or cfg.model or "").strip()
    base_url = (
        args.base_url
        or os.environ.get("SPEAK_SMOKE_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or cfg.base_url
        or ""
    ).strip()
    if not api_key or not model:
        raise SystemExit("missing api_key/model：检查 config/llm_core/config.yaml 或 --api-key/--model")
    print(f"model={model}")
    print(f"base_url={base_url or '(default)'}")
    return OpenAILLM(
        LLMConfig(
            backend="openai",
            model=model,
            api_key=api_key,
            base_url=base_url or None,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
    )


def _base_system() -> str:
    from agent.soul.speak.responders.request_driven.orchestrator.blocks.system.role import (
        build_role,
    )

    persona = (
        "【身份】你是莉奈娅（Linnea），妖精族换生灵、博物向观察者。"
        "说话短句、带自然比喻，不端着；动手时注意力常还在物件上。"
        "当下你在帐篷标本台前，正用书签边缘试探金属锁扣的旋转方向；"
        "露米蹲在帐帘旁警戒。晨光渐亮，时间紧。"
    )
    return f"{build_role('inbound')}\n\n{persona}"


def _build_prompt(user_text: str):
    from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
        DynamicLayerMaterials,
        DynamicLayerSchedule,
    )
    from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (
        RoleContextView,
    )
    from agent.soul.speak.responders.request_driven.prompt import build_role_prompt

    view = RoleContextView(
        session_id="character-role-live",
        history_distilled=(),
        working_turns=(),
    )
    channel = (
        "【交互通道｜远程文字】你通过通信设备与对方发消息；对方不在你身边。"
        "你一边做自己这边正在做的事（写入 body action），一边发文字（speak）。\n"
        "叙事标注 mode=user_utterance"
    )
    return build_role_prompt(
        view,
        user_text=user_text,
        materials=DynamicLayerMaterials(session_id="character-role-live"),
        schedule=DynamicLayerSchedule(reason="character_role_live"),
        interaction_channel=channel,
        plot_outline_text=(
            "当前目标：确认锁扣可沿横纹末端方向旋开，不伤蜡膜与第十八格针尖对齐。\n"
            "步骤：1) 书签边缘抵住锁扣；2) 沿横纹暗示方向缓旋，感受阻力变化；"
            "3) 若阻力松动则继续，否则改换角度再试。"
        ),
        plot_flow_text=(
            "此刻：指尖捏着书签，锁扣刚偏转约两度，阻力仍在；"
            "露米耳尖朝你偏了一度，帐外灌木无新动静；晨光越来越亮。"
        ),
        presence_mood="专注，略紧",
        presence_brief="锁扣差一点就能松，不该被闲聊扯开注意力。",
        presence_speak_desire=42,
        presence_fate_tendency="克制开口",
        user_identity="远方文字往来的熟人",
        user_activity="正在与你文字往来",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Character role live smoke")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument(
        "--only",
        default="",
        help="只跑某个 scenario id：busy_interrupt / plot_relevant / unwanted_chat",
    )
    args = parser.parse_args()

    from agent.soul.speak.llm.engine import SpeakLLMEngine

    _sep("load live LLM")
    engine = SpeakLLMEngine(_load_llm(args))
    base = _base_system()

    _sep("base_system（身份壳）")
    print(base)

    scenarios = SCENARIOS
    if args.only.strip():
        scenarios = tuple(s for s in SCENARIOS if s["id"] == args.only.strip())
        if not scenarios:
            raise SystemExit(f"unknown scenario id: {args.only}")

    for i, case in enumerate(scenarios, start=1):
        prompt = _build_prompt(case["user"])
        system = f"{base}\n\n{prompt.system_extra}".strip()
        _sep(f"{i}) {case['title']}  [{case['id']}]")
        print(f"USER: {case['user']}")
        print("\n--- system 关键片段（主体性 / 协议）---")
        for needle in ("【主体性】", "【回复协议】", "【大纲 unit", "【情景 unit"):
            idx = system.find(needle)
            if idx >= 0:
                print(system[idx : idx + 280])
                print("…")
        print("\n--- LLM raw ---")
        raw = engine.generate(case["user"], system=system).text
        print(raw)
        print("\n--- 粗读 ---")
        low = raw.lower()
        has_body = "<body action>" in low
        has_speak = "<speak>" in low
        print(f"含 body action={has_body}  含 speak={has_speak}  长度={len(raw)}")

    _sep("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
