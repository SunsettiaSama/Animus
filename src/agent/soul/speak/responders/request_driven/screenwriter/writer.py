from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from ..directors.agent.fate import fate_band_label
from ..directors.agent.units import (
    InteractionPlanUnit,
    PlotFlowUnit,
    PresenceUnit,
    SceneEventUnit,
    UserStageUnit,
)
from ..directors.base import DirectorLLMCaller, DirectorOutput, extract_json_object
from ..directors.presence_card import apply_presence_card_output
from ..orchestrator.state.core.interaction_plan import (
    DEFAULT_UNIT_SPAN_POLLS,
    INTERACTION_ROUNDS_BEFORE_WAKE,
    MIN_TOTAL_UNITS_BEFORE_ALIGN,
    PlotArc,
    build_grounded_heuristic_arc,
    reset_narrative_wake_counters,
    should_wake_narrative,
)
from ..orchestrator.state.core.narrative_card import NarrativeStageCard
from ..orchestrator.state.core.plot_flow import PlotFlow
from ..orchestrator.state.core.presence_card import CharacterPresenceCard
from .interaction_mode import (
    InteractionMode,
    interaction_annotation_block,
    no_utterance_user_activity_placeholder,
    resolve_interaction_mode,
    silence_user_activity_placeholder,
)
from .agent import ScreenwriterAgent, ScreenwriterAgentResult
from .materials import (
    USER_PRESENCE_RULE,
    WritingMaterials,
    build_writing_materials,
)
from .scene_seed import DEFAULT_SCENE_SEED_K, build_init_scene_seeds, is_usable_scene_seed

logger = logging.getLogger(__name__)


def normalize_user_opening(text: str) -> str:
    """用户可见开场旁白：一到两句；占用 outline 投递渠道。"""
    body = " ".join(str(text or "").split()).strip()
    if len(body) < 8:
        return ""
    parts = [
        p.strip()
        for p in body.replace("！", "。").replace("？", "。").split("。")
        if p.strip()
    ]
    if len(parts) > 2:
        body = "。".join(parts[:2]) + "。"
    if len(body) > 120:
        return body[:119] + "…"
    return body


class Screenwriter:
    """叙事编剧：写场面与议程，不写角色台词。

    职责备注
    --------
    1) 给角色看
       - plot_arc.summary：完整故事线（起因→经过→转折→收束），客观、冷静、真实
       - units：可执行步骤（intent 用动宾短句），按故事线拆出，供角色侧注入
    2) 内部场记（调度用，不推给用户通读）
       - plot_flow：chronicle / focus_now / next_push / beats
       - 记忆、分享等书写材料统一抽象为 WritingMaterials，由编剧展开后写入剧情流
    3) 给用户看（唯一占用 outline 投递渠道）
       - opening：开场旁白，写用户看见她或他在做什么
       - 只投递这一份用户旁白，不把角色大纲或场记推到同一渠道
       - 开场分三次交稿：先写大纲，再并行写开场旁白和初始剧情 unit
    4) 附带侧卡
       - presence_card（mood/brief）、narrative_card（user_activity 等）

    书写材料（外部注入的统一入口）
    ------------------------
    命运骰、角色面板、场景与世界观请求、记忆池、分享队列、抽词器（约十词），
    以及高优先级的「与用户交互记录（含时间元数据）」——编剧可自由展开为 unit。

    触发节奏
    --------
    - init_presence：先写大纲，再并行写开场旁白与初始剧情 unit
    - sync_on_user_ingress：可选慢路径（热路径默认跳过）；交互记录由角色侧 export 同步
    - tick_on_poll / maybe_align_after_exchange：到门槛时触发（往来满 3 轮或 unit 超 5）；
      唤醒后清空往来计数。导演另检剧情 unit 是否有变动，无变动则不唤醒导演
    - confirm_interaction_unit_complete：只消费当前 unit，不负责唤醒
    - refresh_presence：按需续写内部场记

    实现：大纲与 unit 由 ScreenwriterAgent 多步查阅材料后交稿；
    场记微推（无补仓）仍可用单次调用。记忆与分享的调度写在剧情流上。
    """

    name = "screenwriter"

    # 文风：正向场记指引（写什么、怎么写）
    _CRAFT = (
        "用户在屏幕外看戏，角色在场面里做事。各自写各自的事。\n"
        + USER_PRESENCE_RULE
        + "材料里若有 1 小时内即将到点的手账地标，优先把那一刻写进故事线，"
        "让它当场上实时发生，而不是背景板。\n"
        "开场分三次交稿。第一次写大纲。第二次按大纲写开场旁白。第三次按大纲写初始剧情 unit。"
        "第一次先完成；第二次和第三次并行，都挂在同一份大纲下。\n"
        "三份稿子的写法不同：\n"
        "第一，plot_arc.summary 给角色看。写一条完整故事线（起因→经过→转折或发现→收束可能）。"
        "客观、冷静、真实。一段连贯叙述，含始末与中间节点，能撑住大约十个执行步骤。"
        "不要缩成待办列表，不要写成「你看见……」这类旁白，不要写角色台词。\n"
        "unit 的 estimate_sec 写这一步现实耗时的秒数（发条短消息 5–15，一眼 3–8，"
        "整理/检查 30–60，读/比对/翻找 60–120）；导演按它排现实时间轴、预约开口。\n"
        "第二，opening 给用户看。写眼前能看到的东西，比如「你看见她……」。"
        "「你」表示观看位置；角色的动作写她或他。旁白是开场镜头，不是整场故事线。\n"
        "第三，plot_arc.units.intent 给角色执行。用动宾短句，顺序覆盖故事线各段。\n"
        "plot_flow 写镜头里的物件、光线、她或他的动作。\n"
        "场记与旁白优先入镜：蓟花、台灯、压纸、泥径、绳头、手上的活计。"
        "用现在时、短句。结构说明写在 JSON 字段名里，reason 尽量短。\n"
        "交互记录优先参考，其余材料按需展开为步骤。"
        "场记用客观笔墨写物件、光线、位置、角色动作。\n"
        "有用户往来时，plot_flow.interaction_process 写两件事："
        "第一，交互怎么发生的——对方从屏幕外发来什么、落在角色正在做什么的当口、隔了多久；"
        "第二，这对角色后续故事线有什么影响——注意点、手头活计、下一步往哪偏。"
        "不要写角色说了什么，也不要转述角色台词。\n"
        "材料不多时，故事线仍然写清始末；场记写角色安静在场、手上有未完成的事，从小处往前挪一步。\n"
        "种子词也取这些能入镜的物件和位置。\n"
    )

    _SYSTEM_INIT = (
        "你是叙事编剧，负责起一场戏。\n"
        + _CRAFT
        + "开场分三次交稿，各写各的：\n"
        "第一次，先写 plot_arc.summary 完整故事线；\n"
        "第二次，按大纲写 opening 开场旁白；\n"
        "第三次，按大纲写大约十个初始剧情 unit，覆盖故事线各段。\n"
        "第一次先完成；第二次和第三次并行，都挂在同一份大纲下。\n"
        "plot_flow 由大纲和前几个 unit 派生，不当作第四次交稿。\n"
        "材料从最近经历、场面锚定、种子词里取物件和事实；种子词可以任选若干。\n"
        "side 里的 mood 和 brief 用短标签；没有明确说法时，user_activity 保持中性在场。\n"
        "输出 JSON："
        '{"action":"advance",'
        '"plot_arc":{"summary":"…","evidence":"…",'
        '"units":[{"intent":"…","evidence":"…","span_polls":2,"estimate_sec":40}]},'
        '"plot_flow":{"chronicle":"…","interaction_process":"…","focus_now":"…","next_push":"…","beat":"…","beat_kind":"open",'
        '"inject_memory":true,"memory_unit_ids":["…"],'
        '"inject_share":true,"share_indices":[0]},'
        '"opening":"…",'
        '"side":{"mood":"…","brief":"…","user_identity":"…","user_activity":"…",'
        '"scene_delta":"","structural":false},"reason":"…"}'
    )

    _SYSTEM_REFRESH = (
        "你是叙事编剧，角色刚开过口：续写场记。\n"
        + _CRAFT
        + "action=keep：场面仍然够用。action=advance：chronicle 承接上文，"
        "focus_now、next_push、beat 各写一句具体动作或场面变化。\n"
        "对方有说法时，写清这句话如何落到场面、把角色注意点带向何处；不写角色台词。\n"
        "输出 JSON："
        '{"action":"keep|advance",'
        '"plot_flow":{"chronicle":"…","interaction_process":"…","focus_now":"…","next_push":"…","beat":"…","beat_kind":"interact|push|hold"},'
        '"side":{"mood":"…","brief":"…","user_identity":"…","user_activity":"…",'
        '"scene_delta":"","structural":false},"reason":"…"}'
    )

    _SYSTEM_PLOT_CONTINUE = (
        "你是叙事编剧，按当前角色步骤往下推一小格场记。\n"
        + _CRAFT
        + "先看当前步骤的 intent，尽量往前推一小步。\n"
        "chronicle 承接上一份；静默时尽量写物件、光线、角色手上的空档。\n"
        "focus_now 和 next_push 尽量对齐当前步骤；beat 写这一拍的一句场记。\n"
        "通常选 advance；现场几乎不动时再选 keep。\n"
        "输出 JSON："
        '{"action":"keep|advance",'
        '"plot_flow":{"chronicle":"…","interaction_process":"…","focus_now":"…","next_push":"…","beat":"…","beat_kind":"interact|push|hold"},'
        '"side":{"mood":"…","brief":"…","user_identity":"…","user_activity":"…",'
        '"scene_delta":"","structural":false},"reason":"…"}'
    )

    _SYSTEM_ALIGN = (
        "你是叙事编剧。用户和角色已经往来几轮，后续剧情 unit 可能偏了，需要对齐。\n"
        + _CRAFT
        + "优先看【交互记录｜高优先级】，再从书写材料里取物件、记忆、分享、抽词展开。\n"
        "任务：\n"
        "1) plot_arc.summary 保持原样或微调成完整故事线（客观、冷静、真实），不要缩成清单；\n"
        "2) 当前正在执行的步骤会保留，不要重写它；\n"
        "3) 按已发生的用户交互重写后续 unit（动宾短句），覆盖故事线剩下的段落；\n"
        "4) 同步轻推 plot_flow 一场记；interaction_process 写交互如何发生、对角色后续的影响，不写角色台词；"
        "材料调度可以写 inject_memory 或 inject_share。\n"
        "输出 JSON："
        '{"action":"advance",'
        '"plot_arc":{"summary":"…","evidence":"…",'
        '"units":[{"intent":"…","evidence":"…","span_polls":2,"estimate_sec":40}]},'
        '"plot_flow":{"chronicle":"…","interaction_process":"…","focus_now":"…","next_push":"…","beat":"…","beat_kind":"push",'
        '"inject_memory":false,"memory_unit_ids":[],'
        '"inject_share":false,"share_indices":[]},'
        '"side":{"mood":"…","brief":"…","user_identity":"…","user_activity":"…",'
        '"scene_delta":"","structural":false},"reason":"…"}'
    )

    _SYSTEM_USER_SYNC = (
        "你是叙事编剧。对方刚说了一句话，角色即将接话：判断场记要不要改。\n"
        + _CRAFT
        + "action=keep：现有步骤和场面仍然成立。\n"
        "action=advance：改 focus_now、chronicle、beat、interaction_process，"
        "写清对方这句话如何发生、把角色手头事和注意点带向何处；不写角色台词。\n"
        "输出 JSON："
        '{"action":"keep|advance",'
        '"plot_flow":{"chronicle":"…","interaction_process":"…","focus_now":"…","next_push":"…","beat":"…","beat_kind":"interact|push|hold"},'
        '"side":{"mood":"…","brief":"…","user_identity":"…","user_activity":"…",'
        '"scene_delta":"","structural":false},"reason":"…"}'
    )

    def __init__(
        self,
        *,
        llm: DirectorLLMCaller | None = None,
        story_port: Any | None = None,
        world_id_fn: Callable[[], str] | None = None,
        scene_brief_fn: Callable[[str], str] | None = None,
        resolve_scene_id_fn: Callable[[str], str] | None = None,
        embedder: Any | None = None,
        scene_seed_k: int = DEFAULT_SCENE_SEED_K,
        agent: ScreenwriterAgent | None = None,
        target_units: int = 10,
        on_opening_ready: Callable[[str, str], None] | None = None,
    ) -> None:
        self._llm = llm
        self._story_port = story_port
        self._world_id_fn = world_id_fn
        self._scene_brief_fn = scene_brief_fn
        self._resolve_scene_id_fn = resolve_scene_id_fn
        self._embedder = embedder
        self._scene_seed_k = max(1, int(scene_seed_k))
        self._target_units = max(4, int(target_units))
        self._on_opening_ready = on_opening_ready
        # 剧情写透监听（story_pool 持久化）：_apply_write 成功后回调 session_id
        self._story_change_listener = None
        self._agent = agent or ScreenwriterAgent(
            llm=llm,
            target_units=self._target_units,
        )

    def bind_opening_ready(self, on_opening_ready: Callable[[str, str], None] | None) -> None:
        self._on_opening_ready = on_opening_ready

    def set_story_change_listener(self, listener) -> None:
        """注册剧情写透回调 listener(session_id)；异常由监听方自行吞掉。"""
        self._story_change_listener = listener

    def bind_story(
        self,
        story_port: Any | None,
        world_id_fn: Callable[[], str] | None = None,
        *,
        scene_brief_fn: Callable[[str], str] | None = None,
        resolve_scene_id_fn: Callable[[str], str] | None = None,
    ) -> None:
        self._story_port = story_port
        self._world_id_fn = world_id_fn
        if scene_brief_fn is not None:
            self._scene_brief_fn = scene_brief_fn
        if resolve_scene_id_fn is not None:
            self._resolve_scene_id_fn = resolve_scene_id_fn

    def set_embedder(self, embedder: Any | None) -> None:
        self._embedder = embedder

    def init_presence(
        self,
        state,
        *,
        session_id: str,
        user_text: str = "",
        speak_desire: int | None = None,
        turn_index: int = 0,
        materials: dict[str, Any] | None = None,
        background_agent: bool = False,
        upgrade_agent: bool = True,
    ) -> DirectorOutput:
        """会话开场：先写大纲，再并行写开场旁白与初始剧情 unit。

        background_agent=True：先启发快落盘，再后台跑 Agent 覆写（不堵热路径）。
        upgrade_agent=False：纯启发骨架，不安排后台覆写（预热池骨架候选专用）。
        opening 仅此时生成；随后由 SpeakService 投递给用户，不进角色上下文。
        """
        from agent.soul.speak.story_autonomy import story_autonomy_enabled

        if story_autonomy_enabled():
            # R6.3 总阀（本体级）：剧情/大纲/unit/opening 生成归 life/story
            # （storybus beat）。service 调度、导演协调器直调、预热池三条
            # 来源全部经此断供；返回空输出，调用方按"无叙事"路径降级。
            from ..directors.base import DirectorOutput

            return DirectorOutput(director="screenwriter_init",
                                  reason="story_autonomy_retired")
        grounded = self._ground_text(session_id, user_text=user_text)
        mode = resolve_interaction_mode(
            user_text,
            silence_log_ready=bool(getattr(state.silence_log, "ready", False)),
        )
        seeds = build_init_scene_seeds(
            grounded=grounded,
            user_text=user_text,
            materials=materials,
            embedder=self._embedder,
            k=self._scene_seed_k,
        )
        # 外部已注入抽词种子时优先用它（模拟材料 / compose 预置）
        if isinstance(materials, dict):
            preset = [
                str(x).strip()
                for x in (materials.get("scene_seeds") or [])
                if str(x).strip()
            ]
            if preset:
                cleaned = [t for t in preset if is_usable_scene_seed(t)]
                if cleaned:
                    seeds = cleaned[: max(self._scene_seed_k, len(cleaned))]
        desire = self._desire(state, speak_desire)
        tendency = fate_band_label(desire)

        use_agent_sync = (
            self._llm is not None
            and self._llm.available
            and not background_agent
        )
        decided = None
        if use_agent_sync:
            agent_out = self._compose_with_agent(
                state,
                session_id=session_id,
                turn_index=turn_index,
                task="init",
                grounded=grounded,
                user_text=user_text,
                speak_desire=desire,
                fate_tendency=tendency,
                materials=materials,
                scene_seeds=seeds,
                dialogue_history="",
            )
            if agent_out is not None:
                decided = agent_out.payload
        if decided is None:
            evidence = self._evidence_brief(grounded, materials)
            arc = build_grounded_heuristic_arc(
                evidence=evidence,
                seeds=seeds,
                span_polls=DEFAULT_UNIT_SPAN_POLLS,
            )
            active = arc.active_unit()
            object_hint = ""
            for token in seeds:
                t = str(token or "").strip()
                if is_usable_scene_seed(t):
                    object_hint = t
                    break
            if object_hint:
                chronicle = f"灯下，角色停在手头的活计旁，目光掠过{object_hint}。"
                focus = f"整理眼前的{object_hint}"
                beat = f"角色在场，手边是{object_hint}。"
            else:
                chronicle = "灯下安静。角色坐着，手上有未完成的活计。"
                focus = "继续手头未完成的活计"
                beat = "角色在场，尚未开口。"
            # 启发式开场不把生种子词贴进用户旁白；后台 upgrade 再写正式 opening
            opening = ""
            if not background_agent:
                opening = "灯还亮着。你看见她低着头，手上还停着未做完的活计。"
            decided = {
                "action": "advance",
                "plot_arc": arc.snapshot(),
                "plot_flow": {
                    "chronicle": chronicle,
                    "focus_now": (active.intent if active is not None else focus),
                    "next_push": (
                        active.intent if active is not None else "把眼前物件再确认一遍"
                    ),
                    "beat": beat,
                    "beat_kind": "open",
                },
                "opening": opening,
                "side": {
                    "mood": "平静",
                    "brief": "在做手头的活计",
                    "user_identity": "同场的来访者",
                    "user_activity": self._default_user_activity(mode),
                    "scene_delta": "",
                    "structural": False,
                },
                "reason": "heuristic_init",
            }
            if not grounded.strip():
                decided["side"]["brief"] = "在场，手上有活"
        decided = self._sanitize_side_for_mode(decided, mode)
        payload = self._apply_write(
            state,
            decided,
            speak_desire=desire,
            fate_tendency=tendency,
            turn_index=turn_index,
            session_id=session_id,
            allow_keep=False,
            poll_seq=int(state.poll_seq or 0),
            interaction_mode=mode,
            scene_seeds=seeds,
            replace_arc=True,
            materials=materials,
        )
        reset_narrative_wake_counters(state)
        out = DirectorOutput(
            director=self.name,
            payload=payload,
            reason=str(payload.get("reason") or "init"),
            used_fallback=(
                str(payload.get("reason") or "") == "heuristic_init"
                or "fallback" in str(payload.get("reason") or "")
                or str(payload.get("reason") or "").endswith("_fill")
                or "sparse" in str(payload.get("reason") or "")
                or "max_steps" in str(payload.get("reason") or "")
            ),
        )
        if (
            background_agent
            and upgrade_agent
            and self._llm is not None
            and self._llm.available
            and str(payload.get("reason") or "") == "heuristic_init"
        ):
            self._schedule_agent_init_upgrade(
                state,
                session_id=session_id,
                turn_index=turn_index,
                grounded=grounded,
                user_text=user_text,
                speak_desire=desire,
                fate_tendency=tendency,
                materials=materials,
                scene_seeds=seeds,
                mode=mode,
            )
        return out

    def _schedule_agent_init_upgrade(
        self,
        state,
        *,
        session_id: str,
        turn_index: int,
        grounded: str,
        user_text: str,
        speak_desire: int,
        fate_tendency: str,
        materials: dict[str, Any] | None,
        scene_seeds: list[str],
        mode: InteractionMode,
    ) -> None:
        """启发已落盘后，后台 Agent 覆写弧/场记/opening；不阻塞调用方。"""
        if bool(state.director_cache.get("screenwriter_agent_upgrade_scheduled")):
            return
        state.director_cache["screenwriter_agent_upgrade_scheduled"] = True

        def _run() -> None:
            agent_out = self._compose_with_agent(
                state,
                session_id=session_id,
                turn_index=turn_index,
                task="init",
                grounded=grounded,
                user_text=user_text,
                speak_desire=speak_desire,
                fate_tendency=fate_tendency,
                materials=materials,
                scene_seeds=scene_seeds,
                dialogue_history="",
            )
            state.director_cache.pop("screenwriter_agent_upgrade_scheduled", None)
            if agent_out is None or not isinstance(agent_out.payload, dict):
                return
            decided = self._sanitize_side_for_mode(dict(agent_out.payload), mode)
            payload = self._apply_write(
                state,
                decided,
                speak_desire=speak_desire,
                fate_tendency=fate_tendency,
                turn_index=turn_index,
                session_id=session_id,
                allow_keep=False,
                poll_seq=int(state.poll_seq or 0),
                interaction_mode=mode,
                scene_seeds=scene_seeds,
                replace_arc=True,
                materials=materials,
            )
            reset_narrative_wake_counters(state)
            state.notes.append(
                f"screenwriter:agent_init_upgrade reason={agent_out.reason[:60]}"
            )
            opening = ""
            if isinstance(payload, dict):
                opening = str(payload.get("opening") or "").strip()
            if not opening:
                opening = str(state.director_cache.get("narrative_opening") or "").strip()
            if (
                opening
                and self._on_opening_ready is not None
                and not bool(state.director_cache.get("narrative_opening_delivered"))
            ):
                self._on_opening_ready(session_id, opening)

        threading.Thread(
            target=_run,
            daemon=True,
            name=f"screenwriter-agent-init-{session_id[:12]}",
        ).start()

    def maybe_refresh_after_speak(
        self,
        state,
        *,
        session_id: str,
        turn_index: int,
        user_text: str = "",
        recent_turns: tuple[str, ...] = (),
        speak_desire: int | None = None,
        materials: dict[str, Any] | None = None,
    ) -> DirectorOutput | None:
        """开口本身不唤醒编剧；往来轮次由 note_agent_visible_speak 计数。

        只更新角色可见发言时间戳。
        """
        del session_id, user_text, recent_turns, speak_desire, materials
        if turn_index > 0 and int(state.last_counted_speak_turn) == int(turn_index):
            return None
        if turn_index > 0:
            state.last_counted_speak_turn = int(turn_index)
        state.last_agent_speak_at = time.time()
        return None

    def refresh_presence(
        self,
        state,
        *,
        session_id: str,
        user_text: str = "",
        recent_turns: tuple[str, ...] = (),
        speak_desire: int | None = None,
        turn_index: int = 0,
        speak_count: int | None = None,
        materials: dict[str, Any] | None = None,
    ) -> DirectorOutput:
        """续写内部场记与侧卡；不重写角色议程 opening 旁白。"""
        grounded = self._ground_text(session_id, user_text=user_text)
        mode = resolve_interaction_mode(
            user_text,
            silence_log_ready=bool(getattr(state.silence_log, "ready", False)),
        )
        desire = self._desire(state, speak_desire)
        tendency = fate_band_label(desire)
        previous = state.presence_card if state.presence_card.ready else None
        previous_nar = state.narrative_card if state.narrative_card.ready else None
        decided = None
        if self._llm is not None and self._llm.available:
            decided = self._decide_llm(
                system=self._SYSTEM_REFRESH,
                session_id=session_id,
                turn_index=turn_index,
                grounded=grounded,
                previous_presence=previous,
                previous_narrative=previous_nar,
                user_text=user_text,
                speak_desire=desire,
                fate_tendency=tendency,
                force_rewrite=False,
                recent_turns=recent_turns,
                materials=materials,
                silence_log=tuple(state.silence_log.entries),
                previous_plot=state.plot_flow,
                interaction_mode=mode,
            )
        if decided is None:
            flow = state.plot_flow
            decided = {
                "action": "keep",
                "plot_flow": {
                    "chronicle": flow.chronicle,
                    "focus_now": flow.focus_now,
                    "next_push": flow.next_push,
                    "beat": "",
                    "beat_kind": "hold",
                },
                "side": {
                    "mood": previous.mood if previous is not None else "平静",
                    "brief": previous.brief if previous is not None else "仍在场。",
                    "user_identity": previous_nar.user_identity if previous_nar is not None else "",
                    "user_activity": previous_nar.user_activity if previous_nar is not None else "",
                    "scene_delta": "",
                    "structural": False,
                },
                "reason": "heuristic_keep",
            }
        decided = self._sanitize_side_for_mode(decided, mode)
        payload = self._apply_write(
            state,
            decided,
            speak_desire=desire,
            fate_tendency=tendency,
            turn_index=turn_index,
            session_id=session_id,
            allow_keep=True,
            speak_count=speak_count if speak_count is not None else int(state.agent_speak_count or 0),
            poll_seq=int(state.poll_seq or 0),
            interaction_mode=mode,
            materials=materials,
        )
        return DirectorOutput(
            director=self.name,
            payload=payload,
            reason=str(payload.get("reason") or "refresh"),
            used_fallback="heuristic" in str(payload.get("reason") or ""),
        )

    def tick_on_poll(
        self,
        state,
        *,
        session_id: str,
        turn_index: int = 0,
        materials: dict[str, Any] | None = None,
        speak_desire: int | None = None,
        force: bool = False,
        async_write: bool = True,
        dialogue_history: str = "",
    ) -> DirectorOutput | None:
        """往来满 3 轮或 unit 总数超过 5 时唤醒对齐；否则只缓存。"""
        seq = int(state.poll_seq or 0)
        need_align = bool(force) or self._should_align(state)
        if not need_align:
            self._cache_narrative_units(state)
            state.notes.append(
                f"screenwriter:poll_skip seq={seq} "
                f"exchanges={int(getattr(state, 'interaction_exchange_count', 0) or 0)} "
                f"aligned_at={int(getattr(state, 'screenwriter_aligned_at_exchange', 0) or 0)} "
                f"total={state.plot_arc.total_unit_count() if state.plot_arc.ready else 0} "
                f"rounds={INTERACTION_ROUNDS_BEFORE_WAKE} min_total={MIN_TOTAL_UNITS_BEFORE_ALIGN}"
            )
            return None
        if (
            not force
            and int(state.screenwriter_continued_at_poll or 0) == seq
            and seq > 0
        ):
            self._cache_narrative_units(state)
            state.notes.append(f"screenwriter:poll_already_continued seq={seq}")
            return None

        return self._schedule_align(
            state,
            session_id=session_id,
            turn_index=turn_index,
            materials=materials,
            speak_desire=speak_desire,
            dialogue_history=dialogue_history,
            poll_seq=seq,
            async_write=async_write and not force,
        )

    def tick_on_silence(
        self,
        state,
        *,
        session_id: str,
        turn_index: int = 0,
        materials: dict[str, Any] | None = None,
        speak_desire: int | None = None,
        force: bool = False,
    ) -> DirectorOutput | None:
        """兼容旧名：等价于强制同步续写一拍。"""
        del force
        return self.tick_on_poll(
            state,
            session_id=session_id,
            turn_index=turn_index,
            materials=materials,
            speak_desire=speak_desire,
            force=True,
            async_write=False,
        )

    def sync_on_user_ingress(
        self,
        state,
        *,
        session_id: str,
        user_text: str,
        turn_index: int = 0,
        materials: dict[str, Any] | None = None,
        speak_desire: int | None = None,
    ) -> DirectorOutput:
        """用户入站后、角色开口前：同步判断内部场记是否要改（角色议程仍以现有 units 为准）。"""
        text = str(user_text or "").strip()
        mode: InteractionMode = "user_utterance"
        grounded = self._ground_text(session_id, user_text=text or "user")
        desire = self._desire(state, speak_desire)
        tendency = fate_band_label(desire)
        previous = state.presence_card if state.presence_card.ready else None
        previous_nar = state.narrative_card if state.narrative_card.ready else None
        decided = None
        if self._llm is not None and self._llm.available and text:
            decided = self._decide_llm(
                system=self._SYSTEM_USER_SYNC,
                session_id=session_id,
                turn_index=turn_index,
                grounded=grounded,
                previous_presence=previous,
                previous_narrative=previous_nar,
                user_text=text,
                speak_desire=desire,
                fate_tendency=tendency,
                force_rewrite=False,
                materials=materials,
                silence_log=(),
                previous_plot=state.plot_flow,
                previous_arc=state.plot_arc,
                interaction_mode=mode,
                last_user_utterance=text,
            )
        if decided is None:
            flow = state.plot_flow
            beat = (
                f"对方发来：「{text[:80]}」；角色仍按其当前步骤在场。"
                if text
                else "对方有往来；角色仍按其当前步骤在场。"
            )
            chronicle = flow.chronicle.strip()
            chronicle = f"{chronicle}\n{beat}".strip() if chronicle else beat
            decided = {
                "action": "advance" if text else "keep",
                "plot_flow": {
                    "chronicle": chronicle if text else flow.chronicle,
                    "focus_now": flow.focus_now.strip() or "与对方文字往来中",
                    "next_push": flow.next_push.strip() or "承接对方这句话",
                    "beat": beat if text else "",
                    "beat_kind": "interact",
                },
                "side": {
                    "mood": previous.mood if previous is not None else "平静·在场",
                    "brief": previous.brief if previous is not None else "仍在场。",
                    "user_identity": (
                        previous_nar.user_identity
                        if previous_nar is not None and previous_nar.user_identity.strip()
                        else "对话中的来访者"
                    ),
                    "user_activity": "正在与你文字往来",
                    "scene_delta": "",
                    "structural": False,
                },
                "reason": "heuristic_user_sync",
            }
        decided = self._sanitize_side_for_mode(decided, mode)
        payload = self._apply_write(
            state,
            decided,
            speak_desire=desire,
            fate_tendency=tendency,
            turn_index=turn_index,
            session_id=session_id,
            allow_keep=True,
            poll_seq=int(state.poll_seq or 0),
            interaction_mode=mode,
            materials=materials,
        )
        state.notes.append(
            f"screenwriter:user_sync action={payload.get('action')} "
            f"reason={str(payload.get('reason') or '')[:60]}"
        )
        return DirectorOutput(
            director=self.name,
            payload=payload,
            reason=str(payload.get("reason") or "user_sync"),
            used_fallback="heuristic" in str(payload.get("reason") or ""),
        )

    def confirm_interaction_unit_complete(
        self,
        state,
        *,
        poll_seq: int = 0,
        reason: str = "",
        session_id: str = "",
        materials: dict[str, Any] | None = None,
        dialogue_history: str = "",
        speak_desire: int | None = None,
        turn_index: int = 0,
        unit_id: str = "",
    ) -> Any:
        """导演确认后的唯一落账口：消费当前剧情 unit → 历史。

        角色 delivery 不得调用本方法；仅 DirectorCoordinator._apply_pending_unit_complete。
        unit_id 非空时必须与当前 active 一致，否则视为过期确认并忽略。
        唤醒对齐不在这里：往来满 3 轮或 unit 总数超过 5 才叫醒编剧。
        """
        del materials, dialogue_history, speak_desire, turn_index, session_id
        if not getattr(state, "plot_arc", None) or not state.plot_arc.ready:
            return None
        active = state.plot_arc.active_unit()
        if active is None:
            return None
        want_id = str(unit_id or "").strip()
        active_id = str(getattr(active, "unit_id", "") or "").strip()
        if want_id and active_id and want_id != active_id:
            state.notes.append(
                f"screenwriter:unit_complete_stale want={want_id} active={active_id}"
            )
            return None
        last_done = str(state.director_cache.get("last_completed_plot_unit_id") or "").strip()
        if active_id and last_done == active_id:
            state.notes.append(f"screenwriter:unit_complete_dup id={active_id}")
            return None

        prev = active
        nxt = state.plot_arc.complete_active(
            poll_seq=int(poll_seq or getattr(state, "poll_seq", 0) or 0),
            reason=reason,
        )
        if active_id:
            state.director_cache["last_completed_plot_unit_id"] = active_id
        state.director_cache["plot_arc"] = state.plot_arc.snapshot()
        # 角色侧交付证据已消费
        state.director_cache.pop("plot_unit_delivery_evidence", None)
        live = state.plot_arc.live_unit_count()
        history_n = len(state.plot_arc.unit_history)
        state.notes.append(
            "screenwriter:interaction_unit_complete "
            f"from={(prev.intent if prev else '')[:40]} "
            f"to={(nxt.intent if nxt else '∅')[:40]} "
            f"live={live} "
            f"history={history_n} "
            f"reason={str(reason or '')[:60]}"
        )
        rhythm = getattr(state, "character_rhythm_schedule", None)
        if rhythm is not None and hasattr(rhythm, "sync_scripts_from_plot_arc"):
            rhythm.sync_scripts_from_plot_arc(state.plot_arc)
            state.character_rhythm_schedule = rhythm
            state.director_cache["character_rhythm_schedule"] = rhythm.snapshot()
        self._cache_narrative_units(state)
        return nxt

    def _should_align(self, state) -> bool:
        return should_wake_narrative(state)

    def maybe_align_after_exchange(
        self,
        state,
        *,
        session_id: str,
        turn_index: int = 0,
        materials: dict[str, Any] | None = None,
        dialogue_history: str = "",
        speak_desire: int | None = None,
        async_write: bool = True,
    ) -> DirectorOutput | None:
        """用户↔角色一轮往来落账后：满 3 轮或 unit 总数超过 5 则对齐。"""
        if not self._should_align(state):
            return None
        return self._schedule_align(
            state,
            session_id=session_id,
            turn_index=turn_index,
            materials=materials,
            speak_desire=speak_desire,
            dialogue_history=dialogue_history,
            poll_seq=int(getattr(state, "poll_seq", 0) or 0),
            async_write=async_write,
        )

    def _schedule_align(
        self,
        state,
        *,
        session_id: str,
        turn_index: int,
        materials: dict[str, Any] | None,
        dialogue_history: str,
        speak_desire: int | None,
        poll_seq: int,
        async_write: bool,
    ) -> DirectorOutput | None:
        if not session_id:
            state.notes.append("screenwriter:align_skipped_no_session")
            return None
        seq = int(poll_seq or 0)
        if int(getattr(state, "screenwriter_continued_at_poll", 0) or 0) == seq and seq > 0:
            state.notes.append(f"screenwriter:align_already_scheduled seq={seq}")
            return None
        state.screenwriter_continued_at_poll = seq
        live = state.plot_arc.live_unit_count() if state.plot_arc.ready else 0
        total = state.plot_arc.total_unit_count() if state.plot_arc.ready else 0
        exchanges = int(getattr(state, "interaction_exchange_count", 0) or 0)
        reset_narrative_wake_counters(state)
        logger.info(
            "[screenwriter] align schedule session=%s poll_seq=%s async=%s "
            "exchanges=%s live=%s total=%s",
            session_id,
            seq,
            async_write,
            exchanges,
            live,
            total,
        )
        kwargs = {
            "state": state,
            "session_id": session_id,
            "turn_index": turn_index,
            "materials": materials,
            "speak_desire": speak_desire
            if speak_desire is not None
            else getattr(state, "fate_speak_desire", None),
            "dialogue_history": dialogue_history,
            "poll_seq": seq,
            "align_units": True,
        }
        if async_write and self._llm is not None and self._llm.available:
            threading.Thread(
                target=self._continue_plot_safe,
                kwargs=kwargs,
                daemon=True,
                name=f"screenwriter-align-{session_id[:8]}",
            ).start()
            state.notes.append(
                f"screenwriter:align_async seq={seq} exchanges={exchanges} total={total}"
            )
            self._cache_narrative_units(state)
            return None
        state.notes.append(
            f"screenwriter:align_on_exchange exchanges={exchanges} total={total}"
        )
        return self._continue_interaction_plot(**kwargs)

    def _continue_plot_safe(self, **kwargs) -> None:
        self._continue_interaction_plot(**kwargs)

    def _continue_interaction_plot(
        self,
        state,
        *,
        session_id: str,
        turn_index: int = 0,
        materials: dict[str, Any] | None = None,
        speak_desire: int | None = None,
        dialogue_history: str = "",
        poll_seq: int = 0,
        align_units: bool = False,
    ) -> DirectorOutput:
        last_user = str(state.last_real_user_text or "").strip()
        fuel_query = last_user or "silence"
        mode: InteractionMode = (
            "user_silent" if state.silence_log.ready else "no_utterance"
        )
        grounded = self._ground_text(session_id, user_text=fuel_query)
        desire = self._desire(state, speak_desire)
        tendency = fate_band_label(desire)
        previous = state.presence_card if state.presence_card.ready else None
        previous_nar = state.narrative_card if state.narrative_card.ready else None
        need_align = bool(align_units) or not state.plot_arc.ready
        decided = None
        if self._llm is not None and self._llm.available and need_align:
            agent_out = self._compose_with_agent(
                state,
                session_id=session_id,
                turn_index=turn_index,
                task="align",
                grounded=grounded,
                user_text=fuel_query if mode == "user_utterance" else "",
                speak_desire=desire,
                fate_tendency=tendency,
                materials=materials,
                dialogue_history=dialogue_history,
                previous_presence=previous,
            )
            if agent_out is not None:
                decided = agent_out.payload
        elif self._llm is not None and self._llm.available:
            decided = self._decide_llm(
                system=self._SYSTEM_PLOT_CONTINUE,
                session_id=session_id,
                turn_index=turn_index,
                grounded=grounded,
                previous_presence=previous,
                previous_narrative=previous_nar,
                user_text=fuel_query if mode == "user_utterance" else "",
                speak_desire=desire,
                fate_tendency=tendency,
                force_rewrite=not bool(state.plot_flow.ready),
                materials=materials,
                silence_log=tuple(state.silence_log.entries),
                dialogue_history=dialogue_history,
                poll_seq=poll_seq,
                previous_plot=state.plot_flow,
                previous_arc=state.plot_arc,
                interaction_mode=mode,
                last_user_utterance=last_user,
                require_plot_arc=False,
            )
        if decided is None:
            if need_align and not state.plot_arc.ready:
                decided = None  # fall through to heuristic init-like via apply
            if decided is None:
                decided = self._heuristic_plot_continue(
                    state,
                    previous=previous,
                    previous_nar=previous_nar,
                    poll_seq=poll_seq,
                    interaction_mode=mode,
                )
            if need_align:
                decided = self._heuristic_align_units(state, decided, materials=materials)
        decided = self._sanitize_side_for_mode(decided, mode)
        payload = self._apply_write(
            state,
            decided,
            speak_desire=desire,
            fate_tendency=tendency,
            turn_index=turn_index,
            session_id=session_id,
            allow_keep=not need_align,
            poll_seq=poll_seq,
            interaction_mode=mode,
            materials=materials,
            realign_arc=need_align and state.plot_arc.ready,
            replace_arc=need_align and not state.plot_arc.ready,
        )
        logger.info(
            "[screenwriter] plot_continue done session=%s poll_seq=%s action=%s "
            "reason=%s mode=%s align=%s live=%s",
            session_id,
            poll_seq,
            payload.get("action"),
            str(payload.get("reason") or "")[:80],
            mode,
            need_align,
            state.plot_arc.live_unit_count() if state.plot_arc.ready else 0,
        )
        return DirectorOutput(
            director=self.name,
            payload=payload,
            reason=str(payload.get("reason") or "plot_continue"),
            used_fallback="heuristic" in str(payload.get("reason") or ""),
        )

    def _heuristic_align_units(
        self,
        state,
        decided: dict[str, Any],
        *,
        materials: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """无 LLM 时按用户交互把后续步骤接到这句话上。"""
        out = dict(decided or {})
        out["action"] = "advance"
        seeds = []
        if isinstance(materials, dict):
            seeds = [
                str(x).strip()
                for x in (materials.get("scene_seeds") or materials.get("dynamic_memory_texts") or [])
                if str(x).strip()
            ]
        hint = ""
        for token in seeds:
            if 2 <= len(token) <= 12 and not token.endswith("角色"):
                hint = token
                break
        if hint:
            units = [
                {"intent": f"整理眼前的{hint}", "evidence": hint, "span_polls": 2},
                {"intent": f"把{hint}再确认一遍", "evidence": hint, "span_polls": 2},
                {"intent": f"记下{hint}眼下的状态", "evidence": hint, "span_polls": 1},
            ]
            summary = f"角色继续围绕{hint}做手头整理"
        else:
            units = [
                {"intent": "停在原处，继续手头活计", "evidence": "", "span_polls": 2},
                {"intent": "留意眼前物件与光线", "evidence": "", "span_polls": 2},
                {"intent": "把眼前物件再确认一遍", "evidence": "", "span_polls": 1},
            ]
            summary = "角色在场，手上有未完成的活计"
        out["plot_arc"] = {
            "summary": summary,
            "evidence": hint or str((materials or {}).get("scene_grounded") or "")[:200],
            "units": units,
        }
        out["reason"] = "heuristic_align_units"
        return out

    def _heuristic_plot_continue(
        self,
        state,
        *,
        previous: CharacterPresenceCard | None,
        previous_nar: NarrativeStageCard | None,
        poll_seq: int,
        interaction_mode: InteractionMode = "user_silent",
    ) -> dict[str, Any]:
        n = len(state.silence_log.entries)
        flow = state.plot_flow
        if flow.focus_now.strip():
            beat = f"沉默延续。角色仍{flow.focus_now.strip().rstrip('。')}，没有抬头。"
        else:
            beat = "沉默延续。角色停在原处，手指没有离开手头物件。"
        if n >= 3:
            beat = beat.rstrip("。") + "，偶有细小的整理动作。"
        chronicle = flow.chronicle.strip()
        chronicle = f"{chronicle}\n{beat}".strip() if chronicle else beat
        return {
            "action": "advance",
            "plot_flow": {
                "chronicle": chronicle,
                "focus_now": flow.focus_now.strip() or "停在手头活计旁",
                "next_push": flow.next_push.strip() or "把眼前物件再确认一遍",
                "beat": beat,
                "beat_kind": "push",
            },
            "side": {
                "mood": previous.mood if previous is not None else "平静",
                "brief": previous.brief if previous is not None else "仍在做手头的事",
                "user_identity": (
                    previous_nar.user_identity
                    if previous_nar is not None and previous_nar.user_identity.strip()
                    else "同场的来访者"
                ),
                "user_activity": self._default_user_activity(interaction_mode),
                "scene_delta": "",
                "structural": False,
            },
            "reason": "heuristic_plot_continue",
        }

    def plot_flow_unit_from_state(self, state) -> PlotFlowUnit | None:
        return PlotFlowUnit.from_flow(state.plot_flow, plot_arc=state.plot_arc)

    def interaction_unit_from_state(self, state) -> InteractionPlanUnit | None:
        arc = state.plot_arc
        if not arc.ready:
            return None
        active = arc.active_unit()
        if active is None or not active.intent.strip():
            return None
        return InteractionPlanUnit(
            intent=active.intent,
            evidence=active.evidence or arc.evidence,
            span_polls=active.span_polls,
            status=active.status,
            arc_summary=arc.summary,
        )

    def presence_unit_from_state(self, state) -> PresenceUnit | None:
        card = state.presence_card
        if not card.ready:
            return None
        return PresenceUnit(
            mood=card.mood,
            brief=card.brief,
            speak_desire=card.speak_desire,
            fate_tendency=card.fate_tendency,
        )

    def user_stage_unit_from_state(self, state) -> UserStageUnit | None:
        card = state.narrative_card
        if not card.ready:
            return None
        if not (card.user_identity.strip() or card.user_activity.strip() or card.interaction_mode.strip()):
            return None
        return UserStageUnit(
            user_identity=card.user_identity,
            user_activity=card.user_activity,
            interaction_mode=card.interaction_mode,
        )

    def scene_event_unit_from_state(self, state) -> SceneEventUnit | None:
        # 剧情流就绪时由 PlotFlowUnit 主注入，不再重复塞 scene_event
        if state.plot_flow.ready:
            return None
        card = state.narrative_card
        if not card.scene_event.strip():
            return None
        return SceneEventUnit(scene_event=card.scene_event)

    def soft_merge_fate(self, state, *, speak_desire: int | None = None) -> None:
        """不调编剧 LLM：只把命运骰开口欲软并入已有卡。"""
        card = state.presence_card
        if not card.ready:
            return
        desire = self._desire(state, speak_desire)
        card.speak_desire = desire
        card.fate_tendency = fate_band_label(desire)
        state.director_cache["presence_unit"] = PresenceUnit(
            mood=card.mood,
            brief=card.brief,
            speak_desire=card.speak_desire,
            fate_tendency=card.fate_tendency,
        ).render()

    def _apply_write(
        self,
        state,
        decided: dict[str, Any],
        *,
        speak_desire: int,
        fate_tendency: str,
        turn_index: int,
        session_id: str,
        allow_keep: bool,
        speak_count: int | None = None,
        poll_seq: int | None = None,
        interaction_mode: InteractionMode | None = None,
        scene_seeds: list[str] | None = None,
        replace_arc: bool = False,
        append_arc: bool = False,
        realign_arc: bool = False,
        materials: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action = str(decided.get("action") or "advance").strip().lower()
        if action == "rewrite":
            action = "advance"
        if not allow_keep:
            action = "advance"
        seq = int(poll_seq) if poll_seq is not None else int(state.poll_seq or 0)
        mode = interaction_mode or resolve_interaction_mode(
            "",
            silence_log_ready=bool(getattr(state.silence_log, "ready", False)),
        )

        plot_payload = decided.get("plot_flow")
        if not isinstance(plot_payload, dict):
            plot_payload = {}
        # 编剧把记忆/分享调度并入剧情流（优先 LLM 字段，否则按库存启发）
        schedule = self._select_material_schedule(
            materials,
            mode=mode,
            plot_payload=plot_payload,
        )
        plot_payload = {**plot_payload, **schedule}
        if not str(plot_payload.get("interaction_process") or "").strip():
            clay = (
                materials
                if isinstance(materials, WritingMaterials)
                else build_writing_materials(compose_meta=materials or {})
            )
            process = clay.render_interaction_process()
            if process:
                plot_payload["interaction_process"] = process
        side = decided.get("side")
        if not isinstance(side, dict):
            side = {
                "mood": decided.get("mood"),
                "brief": decided.get("brief"),
                "user_identity": decided.get("user_identity"),
                "user_activity": decided.get("user_activity"),
                "scene_delta": decided.get("scene_delta"),
                "structural": decided.get("structural"),
            }
            if not plot_payload and str(decided.get("scene_event") or "").strip():
                plot_payload = {
                    "chronicle": str(decided.get("scene_event") or "").strip(),
                    "focus_now": "",
                    "next_push": "",
                    "beat": str(decided.get("scene_event") or "").strip()[:120],
                    "beat_kind": "interact",
                }

        arc_payload = decided.get("plot_arc")
        if replace_arc and isinstance(arc_payload, dict):
            state.plot_arc = state.plot_arc.replace_from_payload(
                arc_payload,
                default_span=DEFAULT_UNIT_SPAN_POLLS,
            )
        elif realign_arc and isinstance(arc_payload, dict):
            state.plot_arc.realign_pending_from_payload(
                arc_payload,
                default_span=DEFAULT_UNIT_SPAN_POLLS,
                poll_seq=seq,
            )
        elif append_arc and isinstance(arc_payload, dict):
            state.plot_arc.append_units_from_payload(
                arc_payload,
                default_span=DEFAULT_UNIT_SPAN_POLLS,
                poll_seq=seq,
            )
        elif replace_arc and not state.plot_arc.ready:
            evidence = str((arc_payload or {}).get("evidence") if isinstance(arc_payload, dict) else "")
            state.plot_arc = build_grounded_heuristic_arc(
                evidence=evidence or self._evidence_brief("", materials),
                seeds=scene_seeds,
            )

        if action == "keep" and state.plot_flow.ready:
            state.plot_flow.set_material_schedule(
                inject_memory=bool(schedule.get("inject_memory")),
                memory_unit_ids=list(schedule.get("memory_unit_ids") or []),
                inject_share=bool(schedule.get("inject_share")),
                share_indices=list(schedule.get("share_indices") or []),
                pass_info=bool(schedule.get("pass_info")),
                reason=str(schedule.get("material_reason") or ""),
            )
            state.presence_card.speak_desire = speak_desire
            state.presence_card.fate_tendency = fate_tendency
            if mode and not state.narrative_card.interaction_mode.strip():
                state.narrative_card.interaction_mode = mode
            payload = {
                "action": "keep",
                "plot_flow": state.plot_flow.snapshot(),
                "plot_arc": state.plot_arc.snapshot(),
                "mood": state.presence_card.mood,
                "brief": state.presence_card.brief,
                "user_identity": state.narrative_card.user_identity,
                "user_activity": state.narrative_card.user_activity,
                "interaction_mode": state.narrative_card.interaction_mode or mode,
                "speak_desire": speak_desire,
                "fate_tendency": fate_tendency,
                "reason": str(decided.get("reason") or "keep"),
                "scene_uplift": "skipped",
            }
        else:
            # 角色步骤对齐戏眼：有 active unit 时优先用角色 intent
            active = state.plot_arc.active_unit() if state.plot_arc.ready else None
            if active is not None:
                if not str(plot_payload.get("focus_now") or "").strip():
                    plot_payload["focus_now"] = active.intent
                if not str(plot_payload.get("next_push") or "").strip():
                    plot_payload["next_push"] = active.intent
            state.plot_flow = state.plot_flow.advance_from_payload(
                plot_payload,
                poll_seq=seq,
                turn_index=turn_index,
            )
            mood = str(side.get("mood") or "").strip() or (
                state.presence_card.mood if state.presence_card.ready else "平静"
            )
            brief = str(side.get("brief") or "").strip() or (
                state.presence_card.brief if state.presence_card.ready else "留意着当下。"
            )
            apply_presence_card_output(
                state,
                DirectorOutput(
                    director=self.name,
                    payload={
                        "mood": mood,
                        "brief": brief,
                        "speak_desire": speak_desire,
                        "fate_tendency": fate_tendency,
                        "reason": str(decided.get("reason") or "advance"),
                    },
                    reason="advance",
                ),
                turn_index=turn_index,
            )
            self._write_side_narrative(
                state,
                side,
                turn_index=turn_index,
                interaction_mode=mode,
            )
            if state.plot_flow.chronicle.strip():
                state.narrative_card.scene_event = state.plot_flow.chronicle.strip()
            uplift = self._maybe_uplift_scene(
                session_id,
                scene_delta=str(side.get("scene_delta") or ""),
                structural=bool(side.get("structural")),
            )
            payload = {
                "action": "advance",
                "plot_flow": state.plot_flow.snapshot(),
                "plot_arc": state.plot_arc.snapshot(),
                "mood": state.presence_card.mood,
                "brief": state.presence_card.brief,
                "user_identity": state.narrative_card.user_identity,
                "user_activity": state.narrative_card.user_activity,
                "interaction_mode": state.narrative_card.interaction_mode or mode,
                "speak_desire": speak_desire,
                "fate_tendency": fate_tendency,
                "reason": str(decided.get("reason") or "advance"),
                "scene_uplift": uplift,
            }

        if scene_seeds:
            payload["scene_seeds"] = list(scene_seeds)
            state.director_cache["scene_seeds"] = list(scene_seeds)
        opening = normalize_user_opening(str(decided.get("opening") or ""))
        if replace_arc:
            reason = str(decided.get("reason") or "")
            if not opening and reason != "heuristic_init":
                opening = self._synthesize_outline_opening(state)
                opening = normalize_user_opening(opening)
            if opening:
                payload["opening"] = opening
                already = bool(state.director_cache.get("narrative_opening_delivered"))
                # 用户旁白已占用 outline 渠道：只保留已投递正文，禁止清 flag / 再推一遍
                if already:
                    cached = str(state.director_cache.get("narrative_opening") or "").strip()
                    if not cached:
                        state.director_cache["narrative_opening"] = opening
                else:
                    state.director_cache["narrative_opening"] = opening
        count = int(speak_count) if speak_count is not None else 0
        if count > 0:
            # 兼容旧字段；编剧唤醒指标是往来轮次 + unit 总数
            state.presence_written_at_speak = count
        elif getattr(state, "plot_arc", None) is not None and state.plot_arc.ready:
            state.presence_written_at_speak = len(state.plot_arc.unit_history)
        self._cache_narrative_units(state)
        state.director_cache["screenwriter"] = dict(payload)
        state.director_cache["plot_flow"] = state.plot_flow.snapshot()
        state.director_cache["plot_arc"] = state.plot_arc.snapshot()
        state.notes.append(f"screenwriter:{payload.get('action')}:{payload.get('reason')}")
        if mode:
            state.notes.append(f"screenwriter:interaction_mode={mode}")
        listener = self._story_change_listener
        if listener is not None and str(session_id or "").strip():
            try:
                listener(str(session_id))
            except Exception:
                pass  # 写透失败不回滚剧情写入
        return payload

    def _select_material_schedule(
        self,
        materials: dict[str, Any] | None,
        *,
        mode: InteractionMode,
        plot_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """从库存挑选记忆/分享，写入剧情流调度字段。"""
        mat = materials if isinstance(materials, dict) else {}
        mem_ids = [str(x).strip() for x in (mat.get("dynamic_memory_ids") or []) if str(x).strip()]
        mem_texts = [str(x).strip() for x in (mat.get("dynamic_memory_texts") or []) if str(x).strip()]
        share_texts = [str(x).strip() for x in (mat.get("dynamic_share_texts") or []) if str(x).strip()]
        dir_texts = [
            str(x).strip()
            for x in (mat.get("compose_manager_director_memory_texts") or [])
            if str(x).strip()
        ]

        # LLM 已给字段时尽量尊重；缺省时用启发补齐
        has_llm_mem = "inject_memory" in plot_payload or "memory_unit_ids" in plot_payload
        has_llm_share = "inject_share" in plot_payload or "share_indices" in plot_payload
        inject_memory = bool(plot_payload.get("inject_memory")) if has_llm_mem else False
        mem_ids_out = plot_payload.get("memory_unit_ids") if has_llm_mem else None
        if not isinstance(mem_ids_out, list):
            mem_ids_out = []
        inject_share = bool(plot_payload.get("inject_share")) if has_llm_share else False
        share_idx = plot_payload.get("share_indices") if has_llm_share else None
        if not isinstance(share_idx, list):
            share_idx = []
        pass_info = bool(plot_payload.get("pass_info")) if "pass_info" in plot_payload else False

        prefer_share = mode in ("user_silent", "no_utterance")
        if not has_llm_share and share_texts and prefer_share:
            inject_share = True
            share_idx = [0]
        if not has_llm_mem and mem_texts:
            inject_memory = True
            mem_ids_out = list(mem_ids[:2]) if mem_ids else []
        if "pass_info" not in plot_payload and dir_texts and prefer_share:
            pass_info = True

        # 有库存却全空时，开场/静默仍尽量带一条，避免角色空手上场
        if share_texts and not inject_share and prefer_share:
            inject_share = True
            share_idx = [0]
        if mem_texts and not inject_memory and prefer_share:
            inject_memory = True
            if not mem_ids_out and mem_ids:
                mem_ids_out = list(mem_ids[:1])

        allowed = set(mem_ids)
        mem_ids_out = [str(x) for x in mem_ids_out if str(x).strip() and (not allowed or str(x) in allowed)]
        share_idx = [
            int(x)
            for x in share_idx
            if str(x).lstrip("-").isdigit() and 0 <= int(x) < len(share_texts)
        ]
        return {
            "inject_memory": bool(inject_memory and (mem_ids_out or mem_texts)),
            "memory_unit_ids": mem_ids_out,
            "inject_share": bool(inject_share and share_texts),
            "share_indices": share_idx,
            "pass_info": bool(pass_info and dir_texts),
            "material_reason": "screenwriter_material_schedule",
        }

    def _normalize_opening(self, text: str) -> str:
        """给用户看的开场旁白（outline 渠道）。"""
        return normalize_user_opening(text)

    def _synthesize_outline_opening(self, state) -> str:
        """无 LLM opening 时，用场面拼一到两句给用户看的旁白。"""
        focus = ""
        if state.plot_flow.ready:
            focus = state.plot_flow.focus_now.strip()
        if not focus and state.plot_arc.ready:
            active = state.plot_arc.active_unit()
            if active is not None:
                focus = active.intent.strip()
        brief = str(getattr(state.presence_card, "brief", "") or "").strip()
        if focus:
            action = focus.rstrip("。")
            if action.startswith("角色"):
                action = action[2:].lstrip("正")
            return f"灯还亮着。你看见她正{action}。"
        if brief:
            return f"灯还亮着。你看见她{brief.rstrip('。')}。"
        return "灯还亮着。你看见她低着头，手上还停着未做完的活计。"

    def _write_side_narrative(
        self,
        state,
        side: dict[str, Any],
        *,
        turn_index: int,
        interaction_mode: InteractionMode | None = None,
    ) -> None:
        identity = str(side.get("user_identity") or "").strip()
        activity = str(side.get("user_activity") or "").strip()
        if not identity and state.narrative_card.user_identity.strip():
            identity = state.narrative_card.user_identity.strip()
        if not activity and state.narrative_card.user_activity.strip():
            activity = state.narrative_card.user_activity.strip()
        mode = interaction_mode or ""
        if mode in ("user_silent", "no_utterance"):
            activity = self._default_user_activity(mode)
        event = state.plot_flow.chronicle.strip() or state.narrative_card.scene_event.strip()
        state.narrative_card = NarrativeStageCard(
            user_identity=identity,
            user_activity=activity,
            scene_event=event,
            interaction_mode=str(mode or state.narrative_card.interaction_mode or "").strip(),
            turn_index=turn_index,
            written_at=time.time(),
        )

    def _default_user_activity(self, mode: InteractionMode) -> str:
        if mode == "user_silent":
            return silence_user_activity_placeholder()
        if mode == "no_utterance":
            return no_utterance_user_activity_placeholder()
        return "处于对话现场"

    def _sanitize_side_for_mode(
        self,
        decided: dict[str, Any],
        mode: InteractionMode,
    ) -> dict[str, Any]:
        side = decided.get("side")
        if not isinstance(side, dict):
            side = {}
            decided["side"] = side
        if mode in ("user_silent", "no_utterance"):
            side["user_activity"] = self._default_user_activity(mode)
        return decided

    def _cache_narrative_units(self, state) -> None:
        flow_unit = self.plot_flow_unit_from_state(state)
        if flow_unit is not None:
            state.director_cache["plot_flow_unit"] = flow_unit.render()
            state.director_cache["plot_flow"] = state.plot_flow.snapshot()
        if state.plot_arc.ready:
            state.director_cache["plot_arc"] = state.plot_arc.snapshot()
        iu = self.interaction_unit_from_state(state)
        if iu is not None:
            state.director_cache["interaction_unit"] = iu.render()
        unit = self.presence_unit_from_state(state)
        if unit is not None:
            state.director_cache["presence_unit"] = unit.render()
            state.director_cache["presence_card_state"] = state.presence_card.snapshot()
        stage = self.user_stage_unit_from_state(state)
        if stage is not None:
            state.director_cache["user_stage"] = stage.render()
        event = self.scene_event_unit_from_state(state)
        if event is not None:
            state.director_cache["scene_event"] = event.render()
        if state.narrative_card.ready:
            state.director_cache["narrative_card_state"] = state.narrative_card.snapshot()
        if state.silence_log.ready:
            state.director_cache["silence_log"] = state.silence_log.render()

    def _evidence_brief(
        self,
        grounded: str,
        materials: dict[str, Any] | None,
    ) -> str:
        parts: list[str] = []
        body = grounded.strip()
        if body:
            parts.append(body[:600])
        if materials:
            for key in ("dynamic_memory_texts", "memory_texts"):
                mems = materials.get(key) or []
                if isinstance(mems, (list, tuple)):
                    clipped = [str(x).strip() for x in mems if str(x).strip()][:4]
                    if clipped:
                        parts.append("最近经历=\n" + "\n".join(f"- {t[:160]}" for t in clipped))
                        break
            persona = str(materials.get("persona_brief") or materials.get("persona") or "").strip()
            if persona:
                parts.append(f"人格摘要=\n{persona[:300]}")
        return "\n".join(parts).strip()

    def _maybe_uplift_scene(
        self,
        session_id: str,
        *,
        scene_delta: str,
        structural: bool,
    ) -> str:
        delta = scene_delta.strip()
        if not delta:
            return "none"
        if self._story_port is None or self._world_id_fn is None:
            return "skipped_no_story"
        world_id = self._world_id_fn().strip()
        if not world_id:
            return "skipped_no_world"
        scene_id = ""
        if self._resolve_scene_id_fn is not None:
            scene_id = self._resolve_scene_id_fn(session_id).strip()
        if not scene_id:
            locate = self._story_port.locate_scene(world_id, delta)
            scene = getattr(locate, "scene", None)
            scene_id = str(getattr(scene, "scene_id", None) or getattr(scene, "id", "") or "").strip()
        if not scene_id:
            return "skipped_no_scene_id"
        if structural and hasattr(self._story_port, "ask_gm_at_scene"):
            from storyview.types import GMAnswer

            question = self._story_port.ask_gm_at_scene(world_id, scene_id, delta)
            self._story_port.answer_gm(
                question,
                GMAnswer(question_id=str(getattr(question, "question_id", "")), text=delta, intent="screenwriter"),
                with_dice=False,
            )
            return "ask_gm"
        name = ""
        locate = self._story_port.locate_scene(world_id, "", current_scene_id=scene_id)
        scene = getattr(locate, "scene", None)
        if scene is not None:
            name = str(getattr(scene, "name", "") or "").strip() or scene_id
            base = str(getattr(scene, "narrative", "") or getattr(locate, "inject_text", "") or "").strip()
        else:
            name = scene_id
            base = ""
        narrative = f"{base}\n{delta}".strip() if base else delta
        self._story_port.upsert_scene(
            world_id,
            name=name,
            narrative=narrative,
            scene_id=scene_id,
        )
        return "upsert_scene"

    def _ground_text(self, session_id: str, *, user_text: str = "") -> str:
        parts: list[str] = []
        if self._scene_brief_fn is not None:
            brief = self._scene_brief_fn(session_id).strip()
            if brief:
                parts.append(brief)
        if self._story_port is not None and self._world_id_fn is not None:
            world_id = self._world_id_fn().strip()
            if world_id and hasattr(self._story_port, "render_background"):
                bg = str(
                    self._story_port.render_background(
                        world_id,
                        query=user_text.strip(),
                        purpose="screenwriter_presence",
                    )
                    or ""
                ).strip()
                if bg:
                    parts.append(bg[:1200])
            if world_id:
                inject = str(self._story_port.scene_inject_text(world_id, user_text.strip()) or "").strip()
                if inject:
                    parts.append(inject[:600])
        return "\n".join(parts)

    def _desire(self, state, speak_desire: int | None) -> int:
        if speak_desire is not None:
            return max(0, min(100, int(speak_desire)))
        if state.fate_speak_desire is not None:
            return max(0, min(100, int(state.fate_speak_desire)))
        return 55

    def _materials_block(self, materials: dict[str, Any] | None) -> str:
        if not materials:
            return ""
        lines: list[str] = []
        portrait = str(materials.get("interactor_portrait") or "").strip()
        if portrait:
            lines.append(f"对话者画像=\n{portrait[:800]}")
        mems = materials.get("dynamic_memory_texts") or materials.get("memory_texts") or []
        if isinstance(mems, (list, tuple)) and mems:
            clipped = [str(x).strip() for x in mems if str(x).strip()][:6]
            if clipped:
                lines.append("记忆材料=\n" + "\n".join(f"- {t[:200]}" for t in clipped))
        persona = str(materials.get("persona_brief") or materials.get("persona") or "").strip()
        if persona:
            lines.append(f"人格摘要=\n{persona[:600]}")
        return "\n".join(lines)

    def _compose_with_agent(
        self,
        state,
        *,
        session_id: str,
        turn_index: int,
        task: str,
        grounded: str,
        user_text: str,
        speak_desire: int,
        fate_tendency: str,
        materials: dict[str, Any] | None,
        scene_seeds: list[str] | None = None,
        dialogue_history: str = "",
        previous_presence: CharacterPresenceCard | None = None,
    ) -> ScreenwriterAgentResult | None:
        """多步查阅书写材料后交稿；步骤痕迹写入 director_cache。"""
        if self._agent is None:
            return None
        clay = build_writing_materials(
            compose_meta=materials if isinstance(materials, dict) else {},
            fate_speak_desire=speak_desire,
            fate_tendency=fate_tendency,
            presence_mood=(
                previous_presence.mood
                if previous_presence is not None and previous_presence.ready
                else str((materials or {}).get("presence_mood") or "")
            ),
            presence_brief=(
                previous_presence.brief
                if previous_presence is not None and previous_presence.ready
                else str((materials or {}).get("presence_brief") or "")
            ),
            grounded=grounded,
            dialogue_history=dialogue_history
            or str((materials or {}).get("dialogue_history") or ""),
            recent_turns=tuple((materials or {}).get("recent_turns") or ()),
            silence_log=tuple(getattr(state.silence_log, "entries", ()) or ()),
            last_user_text=str(
                getattr(state, "last_real_user_text", "") or user_text or ""
            ),
            last_user_speak_at=float(getattr(state, "last_user_speak_at", 0.0) or 0.0),
            last_agent_speak_at=float(getattr(state, "last_agent_speak_at", 0.0) or 0.0),
            scene_seeds=scene_seeds or (materials or {}).get("scene_seeds"),
        )
        if clay.scene_grounded.strip() == "" and grounded.strip():
            clay.scene_grounded = grounded.strip()
        prev_arc = ""
        if getattr(state, "plot_arc", None) is not None and state.plot_arc.ready:
            prev_arc = state.plot_arc.render_for_screenwriter()
        prev_flow = ""
        if getattr(state, "plot_flow", None) is not None and state.plot_flow.ready:
            prev_flow = state.plot_flow.render_for_screenwriter()
        result = self._agent.compose(
            clay,
            session_id=session_id,
            turn_index=turn_index,
            task=task,
            previous_arc_text=prev_arc,
            previous_flow_text=prev_flow,
            on_opening_ready=self._on_opening_ready if task == "init" else None,
        )
        state.director_cache["screenwriter_agent"] = result.snapshot()
        state.notes.append(
            "screenwriter:agent "
            f"task={task} steps={len(result.steps)} "
            f"lookups={','.join(result.lookups) or '∅'} "
            f"reason={result.reason[:60]} "
            f"fallback={int(result.used_fallback)}"
        )
        logger.info(
            "[screenwriter] agent done session=%s task=%s steps=%s lookups=%s reason=%s",
            session_id,
            task,
            len(result.steps),
            list(result.lookups),
            result.reason[:80],
        )
        return result

    def _decide_llm(
        self,
        *,
        system: str,
        session_id: str,
        turn_index: int,
        grounded: str,
        previous_presence: CharacterPresenceCard | None,
        previous_narrative: NarrativeStageCard | None,
        user_text: str,
        speak_desire: int,
        fate_tendency: str,
        force_rewrite: bool,
        recent_turns: tuple[str, ...] = (),
        materials: dict[str, Any] | None = None,
        silence_log: tuple[str, ...] = (),
        dialogue_history: str = "",
        poll_seq: int = 0,
        previous_plot: PlotFlow | None = None,
        previous_arc: PlotArc | None = None,
        interaction_mode: InteractionMode | None = None,
        scene_seeds: list[str] | None = None,
        last_user_utterance: str = "",
        require_plot_arc: bool = False,
    ) -> dict[str, Any] | None:
        assert self._llm is not None
        mode = interaction_mode or resolve_interaction_mode(
            user_text,
            silence_log_ready=bool(silence_log),
        )
        prev_line = previous_presence.one_line() if previous_presence is not None else "（尚无）"
        nar_line = previous_narrative.one_line() if previous_narrative is not None else "（尚无）"
        clay = build_writing_materials(
            compose_meta=materials if isinstance(materials, dict) else {},
            fate_speak_desire=speak_desire,
            fate_tendency=fate_tendency,
            presence_mood=(
                previous_presence.mood if previous_presence is not None else ""
            ),
            presence_brief=(
                previous_presence.brief if previous_presence is not None else ""
            ),
            grounded=grounded,
            dialogue_history=dialogue_history,
            recent_turns=recent_turns,
            silence_log=silence_log,
            last_user_text=last_user_utterance or user_text,
            scene_seeds=scene_seeds,
        )
        lines = [
            f"turn={turn_index}",
            f"poll_seq={poll_seq}",
            interaction_annotation_block(mode),
            clay.render_interaction_priority(),
            clay.render_clay_blocks(),
            f"上一张临场卡={prev_line}",
            f"上一张叙事舞台={nar_line}",
            f"user_text={user_text[:280]}",
            "指引：从书写材料展开为 unit / 场记；交互记录优先；"
            "plot_arc 与 units 写角色要做的事；plot_flow 写角色所在场面；"
            "opening 写用户看见什么；side 作附带。",
        ]
        char_notes = []
        raw_fb = None
        if materials:
            raw_fb = materials.get("character_feedback_to_screenwriter")
            if not isinstance(raw_fb, list):
                raw_fb = materials.get("screenwriter_character_notes")
        if isinstance(raw_fb, list):
            for x in raw_fb:
                if isinstance(x, dict):
                    text = str(x.get("text") or "").strip()
                else:
                    text = str(x or "").strip()
                if text:
                    char_notes.append(text)
        if char_notes:
            lines.append(
                "角色反馈（可据以调整步骤）=\n"
                + "\n".join(f"- {n[:160]}" for n in char_notes[-6:])
            )
        if last_user_utterance.strip() and mode != "user_utterance":
            lines.append(
                "最近一次用户说法（可作场面背景）=\n"
                + last_user_utterance.strip()[:280]
            )
        if previous_arc is not None and previous_arc.ready:
            lines.append(previous_arc.render_for_screenwriter())
        if previous_plot is not None:
            lines.append(previous_plot.render_for_screenwriter())
        if force_rewrite:
            if require_plot_arc:
                lines.append(
                    "请 action=advance；写全/追加 plot_arc.units（角色议程补仓）与 plot_flow；"
                    "开场拍才写 opening（给用户看的开场白，写用户看见她或他）。"
                )
            else:
                lines.append(
                    "请 action=advance，并写全 plot_flow 与 side；"
                    "正文尽可能用场记口吻直接写场面。"
                )
        raw = self._llm.generate_json(
            system=system,
            user="\n".join(lines),
            session_id=session_id,
            director=self.name,
            turn_index=turn_index,
        )
        data = extract_json_object(raw)
        if not data:
            return None
        action = str(data.get("action") or ("advance" if force_rewrite else "keep")).strip().lower()
        if action == "rewrite":
            action = "advance"
        if action not in ("keep", "advance"):
            action = "advance" if force_rewrite else "keep"
        plot_flow = data.get("plot_flow")
        if not isinstance(plot_flow, dict):
            plot_flow = {}
        side = data.get("side")
        if not isinstance(side, dict):
            side = {
                "mood": data.get("mood"),
                "brief": data.get("brief"),
                "user_identity": data.get("user_identity"),
                "user_activity": data.get("user_activity"),
                "scene_delta": data.get("scene_delta"),
                "structural": data.get("structural"),
            }
            if str(data.get("scene_event") or "").strip() and not plot_flow:
                plot_flow = {
                    "chronicle": str(data.get("scene_event") or "").strip(),
                    "beat": str(data.get("scene_event") or "").strip()[:120],
                    "beat_kind": "interact",
                }
        mood = str(side.get("mood") or "").strip()
        brief = str(side.get("brief") or "").strip()
        if action == "advance" and not plot_flow.get("chronicle") and not plot_flow.get("beat") and not mood and not brief:
            return None
        out: dict[str, Any] = {
            "action": action,
            "plot_flow": {
                "chronicle": str(plot_flow.get("chronicle") or "").strip()
                or (previous_narrative.scene_event if previous_narrative is not None else ""),
                "interaction_process": str(plot_flow.get("interaction_process") or "").strip(),
                "focus_now": str(plot_flow.get("focus_now") or "").strip(),
                "next_push": str(plot_flow.get("next_push") or "").strip(),
                "beat": str(plot_flow.get("beat") or "").strip(),
                "beat_kind": str(plot_flow.get("beat_kind") or "interact").strip().lower(),
            },
            "side": {
                "mood": mood or (previous_presence.mood if previous_presence is not None else "平静"),
                "brief": brief
                or (previous_presence.brief if previous_presence is not None else "留意着当下。"),
                "user_identity": str(side.get("user_identity") or "").strip()
                or (previous_narrative.user_identity if previous_narrative is not None else ""),
                "user_activity": str(side.get("user_activity") or "").strip()
                or (previous_narrative.user_activity if previous_narrative is not None else ""),
                "scene_delta": str(side.get("scene_delta") or "").strip(),
                "structural": bool(side.get("structural")),
            },
            "reason": str(data.get("reason") or "screenwriter_llm"),
        }
        opening = str(data.get("opening") or "").strip()
        if opening:
            out["opening"] = opening
        arc_raw = data.get("plot_arc")
        if isinstance(arc_raw, dict):
            out["plot_arc"] = {
                "summary": str(arc_raw.get("summary") or "").strip(),
                "evidence": str(arc_raw.get("evidence") or grounded[:400]).strip(),
                "units": arc_raw.get("units") or [],
            }
        return out
