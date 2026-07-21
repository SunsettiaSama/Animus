from __future__ import annotations

from ...contracts import TextGenerator
from ...stage import StageState
from ...stage.on_scene import OnSceneFocus, OnSceneState
from ..base import extract_json_object, generate_text

ON_SCENE_SYSTEM = (
    "你在为 agent 刷新「临场状态」：此刻注意力在哪、身体周边有没有动静。\n"
    "给拼接导演读：短衍生，不是角色台词，也不决定开不开口。\n"
    "\n"
    "只输出 JSON：\n"
    '{"on_scene":"一两句口语，写当下临场",'
    '"focus":"present|drift|notice"}\n'
    "\n"
    "focus：\n"
    "- present：注意力还在对话上。\n"
    "- drift：有点走神 / 发呆。\n"
    "- notice：注意到对话外的事（声音、物件、别处动静）。\n"
    "\n"
    "要求：\n"
    "- 一两句即可；写注意力与身体当下。\n"
    "- 避免复述待分享/对话弧里的惦记，避免把分享欲写成临场。\n"
    "- 避免写成长散文。"
)


def on_scene_brief(stage: StageState) -> str:
    lines = [
        "# 材料（供刷新临场状态）",
        f"session={stage.session_id} turn={stage.turn_index} poll={stage.poll_index}",
        "",
        "## Agent 当下",
        stage.agent_status.strip() or "（无）",
        "",
        "## 情感",
        stage.affect.label.strip() or "（未标）",
        "",
        "## 上一拍临场",
        stage.on_scene.one_line() if stage.on_scene.ready else "（尚无）",
        "",
        "## 最近对白（只看氛围，别抄成惦记清单）",
    ]
    beats = stage.recent_beats(4)
    if not beats:
        lines.append("（尚无对白）")
    else:
        for beat in beats:
            lines.append(f"- {beat.one_line()}")
    return "\n".join(lines)


def _parse_focus(raw: object) -> OnSceneFocus:
    token = str(raw or "present").strip().lower()
    if token in ("drift", "absent", "away"):
        return "drift"
    if token in ("notice", "notice_other", "elsewhere"):
        return "notice"
    return "present"


def on_scene_from_payload(payload: dict, *, beat_index: int) -> OnSceneState:
    text = str(payload.get("on_scene") or payload.get("text") or "").strip()
    if not text:
        raise ValueError("on_scene: empty text")
    return OnSceneState(
        text=text,
        focus=_parse_focus(payload.get("focus")),
        beat_index=beat_index,
    )


def should_refresh_on_scene(stage: StageState, *, every_k: int) -> bool:
    """每隔 k 次节奏拍刷新；冷启动无临场时立即刷；在途任务不重复踢。"""
    if every_k <= 0:
        return False
    if stage.on_scene_pending:
        return False
    if not stage.on_scene.ready:
        return True
    return stage.beats_since_on_scene >= every_k


def compute_on_scene(
    llm: TextGenerator,
    brief: str,
    *,
    beat_index: int,
) -> OnSceneState:
    """纯计算：不写 stage，供异步线程调用。"""
    raw = generate_text(llm, system=ON_SCENE_SYSTEM, user=brief)
    return on_scene_from_payload(
        extract_json_object(raw, director="rhythm.on_scene"),
        beat_index=beat_index,
    )


def refresh_on_scene(
    stage: StageState,
    llm: TextGenerator,
    *,
    beat_index: int | None = None,
) -> OnSceneState:
    """同步刷新（测试 / 冷启动兜底）；生产路径优先异步注入。"""
    idx = stage.poll_index if beat_index is None else beat_index
    state = compute_on_scene(llm, on_scene_brief(stage), beat_index=idx)
    stage.set_on_scene(state)
    return state
