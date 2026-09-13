#!/usr/bin/env python3
"""还原角色本轮可能收到的 composer / 编排材料，并打印原始提示词。

默认打满所有槽位（占位符），让外壳原文和装配顺序可见。
  python scripts/dump_character_composer_prompt.py
  python scripts/dump_character_composer_prompt.py --empty
  python scripts/dump_character_composer_prompt.py --mode proactive --extras
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


from agent.soul.speak.responders.request_driven.character.context import (  # noqa: E402
    REMOTE_TEXT_CHANNEL,
    context_cards_from_narrative,
)
from agent.soul.speak.responders.request_driven.character.contracts import (  # noqa: E402
    NarrativeSnapshot,
)
from agent.soul.speak.responders.request_driven.character.units import (  # noqa: E402
    CharacterContextUnit,
    CharacterHelpObservationUnit,
)
from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (  # noqa: E402
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (  # noqa: E402
    RoleContextView,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.system.role import (  # noqa: E402
    build_role as _ROLE_TEXT,
)
from agent.soul.speak.responders.request_driven.orchestrator.assemble import (  # noqa: E402
    APPEND_CONTINUE_CHARACTER,
    APPEND_CONTINUE_INSTRUCTION,
    build_turn_system,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.layer import (  # noqa: E402
    SpeakGuidanceLayer,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.runtime.context.render import (  # noqa: E402
    _DISTILL_LEAD,
    _WM_LEAD,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.runtime.memory.render import (  # noqa: E402
    _MEMORY_LEAD,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.runtime.social import (  # noqa: E402
    INITIATIVE_PROMPT,
    render_enter_greeting_block,
    render_silence_break_block,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.persona.api import (  # noqa: E402
    SpeakPersonaLayer,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.scene.api import (  # noqa: E402
    SpeakSceneLayer,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.system.layer import (  # noqa: E402
    SpeakSystemLayer,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.system.output_format import (  # noqa: E402
    SpeakOutputFormat,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.system.role import (  # noqa: E402
    build_role,
)
from agent.soul.speak.responders.request_driven.orchestrator.bundle import (  # noqa: E402
    SpeakPromptBundle,
)
from agent.soul.speak.responders.request_driven.prompt import (  # noqa: E402
    build_role_prompt,
)
from agent.soul.speak.session.manage.types import (  # noqa: E402
    EnterGreetingTurnSpec,
    SilenceBreakTurnSpec,
)
from agent.soul.speak.session.queue.types import InterruptContext  # noqa: E402


HR = "=" * 72
SUB = "-" * 72


def _banner(title: str) -> None:
    print(f"\n{HR}")
    print(title)
    print(HR)


def _block(title: str, body: str) -> None:
    print(f"\n{SUB}")
    print(title)
    print(SUB)
    text = body if body.strip() else "（空）"
    print(text)


def _print_static_templates() -> None:
    _banner("1. 代码里写死的原始提示词")
    _block("system.role / inbound  （orchestrator/blocks/system/role.py）", _ROLE_TEXT("inbound"))
    _block("system.role / proactive", _ROLE_TEXT("proactive"))
    _block(
        "远程文字通道  （character/context.py，进 narrative.interaction_channel）",
        REMOTE_TEXT_CHANNEL,
    )
    _block("对话蒸馏头  （guidance/runtime/context/render.py）", _DISTILL_LEAD)
    _block("工作记忆头", _WM_LEAD)
    _block("长期记忆预览头  （guidance/runtime/memory/render.py）", _MEMORY_LEAD)
    _block("弱主动引导  （guidance/runtime/social.py，进 social_blocks）", INITIATIVE_PROMPT)
    greeting = render_enter_greeting_block(
        EnterGreetingTurnSpec(
            session_id="demo",
            elapsed_sec=12,
            angle="「{进房话头角度}」",
            thought="",
            dialogue_compressed="「{近期对话脉络}」",
        )
    )
    _block("进房问候块（social_blocks）", greeting)
    silence = render_silence_break_block(
        SilenceBreakTurnSpec(
            session_id="demo",
            elapsed_sec=40,
            angle="「{静默承接角度}」",
            thought="",
            dialogue_compressed="「{近期对话脉络}」",
        )
    )
    _block("静默打破块（已默认关闭，模板仍在）", silence)
    share = (
        "你心里有想与用户分享的事情；是否分享、何时分享由你自行决定"
        "（可用 state:share 或指向索引查阅详情）。 "
        "分享摘要：「{分享摘要}」。"
    )
    _block("分享队列预览  （guidance/runtime/share_prompt.py）", share)
    _block("角色续写  （assemble.py，append 轮才加）", APPEND_CONTINUE_CHARACTER)
    _block("compose 续写（角色路径不用）", APPEND_CONTINUE_INSTRUCTION)
    _block(
        "compose 输出协议（角色路径故意丢掉）",
        SpeakOutputFormat().render_prompt(),
    )
    _block(
        "CharacterAgentHost 默认 system（每轮会被 set_system 覆盖）",
        "你是对话中的角色个体。按回复格式开口；具体办事交给后台分流。",
    )
    _block(
        "往来账本头  （character/interaction.py render_for_character）",
        "你们之间已经发生的往来如下。据此自然延续，不要装作没听过或没说过。",
    )
    _block(
        "动态层空回落  （layers.py，没有任何 dyn_blocks 时）",
        "（无输出——动态层不再含指令或回落文案，空即空。）",
    )
    _block(
        "动态层有材料时的头",
        "（已移除——动态层只输出材料小节，头部指令全部上移 system role。）",
    )
    unit = CharacterContextUnit(title="故事线", body="「{卡片正文}」")
    help_u = CharacterHelpObservationUnit(observation="「{后台回传}」")
    _block("Agent Unit 卡片外壳", unit.render())
    _block("后台回传外壳", help_u.render())


def _print_catalog() -> None:
    _banner("2. 角色可能收到的内容目录（按来源）")
    rows = [
        ("A 编排 bundle", "system.role", "身份/通道/本拍怎么回", "几乎每轮"),
        ("A 编排 bundle", "persona.identity", "人格自叙 distill", "有 Persona 才有"),
        ("A 编排 bundle", "persona.presence", "此刻心情句", "有 instant_mood"),
        ("A 编排 bundle", "persona.relational", "对话者画像", "memory 拉到 portrait"),
        ("A 编排 bundle", "scene.world_scene", "所处场景（第二人称）", "Storyview 命中"),
        ("A 编排 bundle", "guidance.control_arc", "对话引导自然段", "导演 control"),
        ("A 编排 bundle", "guidance.recall_preview", "长期记忆浮现预览", "memory similar"),
        ("A 编排 bundle", "guidance.share_preview", "待分享队列预览", "share 非空"),
        ("A 编排 bundle", "guidance.social_blocks", "进房/弱主动/静默", "social 武装"),
        ("A 编排 bundle", "guidance.context_distill", "已压缩对话脉络", "有蒸馏"),
        ("A 编排 bundle", "guidance.working_memory", "未压缩近轮对白", "有近轮"),
        ("A 编排 bundle", "interrupt 附加", "打断上下文", "出站中又来用户"),
        ("A 编排 bundle", "recent_brew_lines", "勿重复 brew 文案", "brew 队列非空"),
        ("A 编排 bundle", "append 续写", "只续 <speak>", "session_state=append"),
        ("B ComposeManager", "RoleContextView.history_distilled", "对话轨迹压缩", "无账本时回落"),
        ("B ComposeManager", "RoleContextView.working_turns", "对话轨迹未压缩", "无账本时回落"),
        ("B ComposeManager", "materials.memory_*", "可调度记忆库存", "编剧 schedule 才压入"),
        ("B ComposeManager", "materials.share_texts", "可调度分享库存", "编剧 schedule 才压入"),
        ("B ComposeManager", "materials.director_memory_*", "pass_info 背景", "schedule.pass_info"),
        ("C 叙事快照", "plot_outline / plot_flow", "故事线 / 此刻情景", "编剧 ready"),
        ("C 叙事快照", "director_*", "手头/内心/过渡/姿态", "可执行 unit 绑定"),
        ("C 叙事快照", "presence_*", "心情/开口欲/简述", "presence card"),
        ("C 叙事快照", "user_identity / activity", "对方舞台", "narrative card"),
        ("C 叙事快照", "interaction_channel", "远程文字通道 + 本拍形态", "每轮"),
        ("C 叙事快照", "interaction_record_text", "往来账本", "有交互才写"),
        ("C 叙事快照", "scene_event", "临场事件（无 plot_flow 才用）", "回落"),
        ("D 角色静态层", "protocol", "<speak> 交付协议", "每轮"),
        ("D 角色静态层", "对方刚发来的消息", "用户原文再写一遍", "热路径"),
        ("E Agent Units", "context cards", "同一批材料再做成卡片", "CharacterAgentHost"),
        ("E Agent Units", "help observations", "Worker 回传", "角色 ask_help 后"),
        ("E Agent Units", "add_user", "真正的 user 消息", "热路径有原文"),
    ]
    print(f"{'来源':<18} {'槽位':<36} {'角色看到什么':<28} {'何时出现'}")
    print(SUB)
    for src, slot, what, when in rows:
        print(f"{src:<18} {slot:<36} {what:<28} {when}")
    print(
        "\n角色路径故意不要："
        "bundle.system.output_format（[think]/[action]/[state] 协议）、"
        "behavior_guide、script_hint、silence_log 正文。"
    )
    print(
        "注意：同一批材料会进 SYSTEM extra 和 Agent 卡片，用户原文还会再走 add_user。"
        "ComposeManager 的记忆不会自动进提示词，必须编剧 schedule.inject_*。"
    )


def _full_bundle(*, mode: str, extras: bool) -> SpeakPromptBundle:
    social = [INITIATIVE_PROMPT]
    if extras:
        social.append(
            render_enter_greeting_block(
                EnterGreetingTurnSpec(
                    session_id="demo",
                    elapsed_sec=12,
                    angle="「{进房话头角度}」",
                    thought="",
                    dialogue_compressed="「{近期对话脉络}」",
                )
            )
        )
    return SpeakPromptBundle(
        session_id="demo",
        mode=mode,  # type: ignore[arg-type]
        system=SpeakSystemLayer(
            role=build_role(mode),  # type: ignore[arg-type]
            output_format=SpeakOutputFormat().render_prompt(),
        ),
        persona=SpeakPersonaLayer(
            dialogue_compressed="「{对话压缩，角色路径会 scrub}」",
        ),
        scene=SpeakSceneLayer(
            world_scene="「{Storyview 场景：你此刻身处……}」",
            scene_name="demo-scene",
        ),
        guidance=SpeakGuidanceLayer(
            control_arc="「{导演对话引导自然段}」",
            recall_preview=f"{_MEMORY_LEAD}\n- 「{{长期记忆浮现 1}}」\n- 「{{长期记忆浮现 2}}」",
            share_preview=(
                "你心里有想与用户分享的事情；是否分享、何时分享由你自行决定"
                "（可用 state:share 或指向索引查阅详情）。 "
                "分享摘要：「{分享摘要}」。"
            ),
            social_blocks=social,
            context_distill=f"{_DISTILL_LEAD}\n- 「{{已压缩脉络 1}}」\n- 「{{已压缩脉络 2}}」",
            working_memory=(
                f"{_WM_LEAD}\n（generation=3）\n"
                "用户：「{近轮用户}」\n我：「{近轮角色}」"
            ),
        ),
        user_text="「{对方刚发来的原文}」",
        meta={
            "recent_brew_lines": "「{brew 队列里已说过的句子}」",
        },
    )


def _empty_bundle(*, mode: str) -> SpeakPromptBundle:
    return SpeakPromptBundle(
        session_id="demo",
        mode=mode,  # type: ignore[arg-type]
        system=SpeakSystemLayer(
            role=build_role(mode),  # type: ignore[arg-type]
            output_format=SpeakOutputFormat().render_prompt(),
        ),
        user_text="「{对方刚发来的原文}」",
    )


def _wire_persona(bundle: SpeakPromptBundle) -> None:
    bundle.persona.self_narrative = "「{人格自叙 / persona_distill.slices.general}」"
    bundle.persona.instant_mood = "「{presence 此刻心情}」"
    bundle.persona.relational.interactor_portrait = (
        "与你交谈的是「{对方名字}」，特质偏「{特质}」；"
        "你们的关系是「{关系}」；近期你对「{对方名字}」的印象是「{印象}」。"
    )


def _full_view() -> RoleContextView:
    return RoleContextView(
        session_id="demo",
        history_distilled=("「{轨迹压缩 1}」", "「{轨迹压缩 2}」"),
        working_turns=(("「{未压缩用户}」", "「{未压缩角色}」"),),
        memory_texts=("「{检索命中，但不自动注入}」",),
        memory_ids=("mem-1",),
        meta={"memory_not_auto_injected": True},
    )


def _full_materials() -> DynamicLayerMaterials:
    return DynamicLayerMaterials(
        session_id="demo",
        memory_ids=("mem-1", "mem-2"),
        memory_texts=("「{本轮记忆卡片 1}」", "「{本轮记忆卡片 2}」"),
        share_texts=("「{本轮分享卡片}」",),
        director_memory_ids=("dmem-1",),
        director_memory_texts=("「{编剧 pass_info 背景}」",),
    )


def _full_schedule() -> DynamicLayerSchedule:
    return DynamicLayerSchedule(
        inject_memory=True,
        memory_unit_ids=("mem-1", "mem-2"),
        inject_share=True,
        share_indices=(0,),
        pass_info=True,
        reason="dump_full",
        source="screenwriter",
    )


def _full_narrative(*, user_text: str) -> NarrativeSnapshot:
    return NarrativeSnapshot(
        plot_outline_text="「{本场故事线 / plot_arc.render_for_inject}」",
        plot_flow_text="「{此刻情景 / plot_flow.render_for_inject}」",
        director_detail="「{手头动作}」",
        director_inner="「{内心状态}」",
        director_transition="「{过渡方式}」",
        director_stance="「{姿态}」",
        presence_mood="「{心情}」",
        presence_brief="「{临场简述}」",
        presence_speak_desire=62,
        presence_fate_tendency="偏开口",
        presence_render="心情：「{心情}」\n开口欲：62/100（偏开口）\n简述：「{临场简述}」",
        user_identity="「{对方身份}」",
        user_activity="正在与你文字往来",
        interaction_channel=(
            f"{REMOTE_TEXT_CHANNEL}\n本拍是对方刚发来的文字，不是静默场面。"
        ),
        interaction_record_text=(
            "你们之间已经发生的往来如下。据此自然延续，"
            "不要装作没听过或没说过。\n"
            "对方上次说话是 3.0 秒前；你上次开口是 28.0 秒前。\n"
            "对方刚说、还等你接的是：「{对方刚发来的原文}」\n"
            "你最近一句是：「{你上一句}」\n"
            "已经发生的对白如下：\n- 用户：「{对白}」 / 你：「{对白}」"
        ),
    )


def _assemble(
    *,
    mode: str,
    empty: bool,
    extras: bool,
) -> tuple[str, list[tuple[str, str]], str]:
    user_text = "「{对方刚发来的原文}」"
    if empty:
        bundle = _empty_bundle(mode=mode)
        view = RoleContextView(session_id="demo")
        materials = DynamicLayerMaterials(session_id="demo")
        schedule = DynamicLayerSchedule(reason="no_director_schedule")
        narrative = NarrativeSnapshot(
            interaction_channel=REMOTE_TEXT_CHANNEL,
        )
        help_obs: tuple[str, ...] = ()
    else:
        bundle = _full_bundle(mode=mode, extras=extras)
        _wire_persona(bundle)
        view = _full_view()
        materials = _full_materials()
        schedule = _full_schedule()
        narrative = _full_narrative(user_text=user_text)
        help_obs = ("「{Worker 回传观察}」",)

    interrupt = None
    parsed = None
    round_idx = 0
    if extras and not empty:
        interrupt = InterruptContext(
            new_user_text="「{打断后的最新用户原文}」",
            previous_user_text="「{被打断的上一轮用户原文}」",
            partial_agent_output="「{尚未推完的片段}」",
            suspended_compose_count=1,
            suspended_compose_summary="「{挂起队列快照}」",
        )

        class _Parsed:
            session_state = "append"

        parsed = _Parsed()
        round_idx = 1

    base = build_turn_system(
        bundle,
        interrupt_context=interrupt,
        round_idx=round_idx,
        partial_output="「{已输出片段}」" if extras and not empty else "",
        parsed=parsed,
        for_character=True,
    )
    prompt = build_role_prompt(
        view,
        user_text=user_text if not empty else user_text,
        materials=materials,
        schedule=schedule,
        help_observations=help_obs,
        presence_mood=narrative.presence_mood,
        presence_brief=narrative.presence_brief,
        presence_speak_desire=narrative.presence_speak_desire,
        presence_fate_tendency=narrative.presence_fate_tendency,
        user_identity=narrative.user_identity,
        user_activity=narrative.user_activity,
        interaction_channel=narrative.interaction_channel,
        plot_outline_text=narrative.plot_outline_text,
        plot_flow_text=narrative.plot_flow_text,
        scene_event=narrative.scene_event,
        director_detail=narrative.director_detail,
        director_inner=narrative.director_inner,
        director_transition=narrative.director_transition,
        director_stance=narrative.director_stance,
        interaction_record_text=narrative.interaction_record_text,
    )
    system = base
    if prompt.system_extra.strip():
        system = f"{system}\n\n{prompt.system_extra}".strip() if system else prompt.system_extra
    cards = context_cards_from_narrative(
        narrative,
        dialogue_frame=prompt.layers.dialogue_frame if prompt.layers is not None else "",
        memory_texts=schedule.selected_memory_texts(materials),
        share_texts=schedule.selected_share_texts(materials),
        user_text=user_text,
    )
    return system, cards, user_text


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump character composer prompt")
    parser.add_argument("--empty", action="store_true", help="只留静态壳，不填动态槽")
    parser.add_argument("--mode", choices=("inbound", "proactive"), default="inbound")
    parser.add_argument(
        "--extras",
        action="store_true",
        help="附上 interrupt / append / enter_greeting 等非常驻块",
    )
    parser.add_argument("--no-static", action="store_true", help="不打印静态原文清单")
    parser.add_argument("--no-catalog", action="store_true", help="不打印槽位目录")
    args = parser.parse_args()

    if not args.no_catalog:
        _print_catalog()
    if not args.no_static:
        _print_static_templates()

    system, cards, user_text = _assemble(
        mode=args.mode,
        empty=args.empty,
        extras=args.extras,
    )
    label = "空壳" if args.empty else "打满槽位"
    _banner(f"3. 角色 SYSTEM（{args.mode} / {label}）")
    print(system)
    _banner("4. CharacterAgentHost 上下文卡片（与 SYSTEM 有重叠）")
    if not cards:
        print("（无卡片）")
    for title, body in cards:
        _block(f"[角色卡片·{title}]", body)
    _banner("5. user 消息（add_user / RolePrompt.user_text）")
    print(user_text)
    _banner("6. 最终送给 LLM 的形状")
    print("llm.generate(")
    print("    human = AgentService.timeline.render()   # Units + UserUnit")
    print("    system = 上面第 3 节 SYSTEM")
    print(")")
    print("热路径有用户原文时 human 至少包含 user 消息；")
    print("预约路径 user_text 为空，human 可能回落到「（系统：按台本推进本拍演出。）」。")


if __name__ == "__main__":
    main()
