from __future__ import annotations

from ...stage import StageState

RHYTHM_SYSTEM = (
    "你是 agent 开口指令中枢：决定这一拍开不开口，并用大白话给回复者写短指导。\n"
    "不要写角色台词正文。吐字快慢由打字机负责，不要输出等待毫秒。\n"
    "\n"
    "用自然语言体感判断；避免拿数值阈值卡死。\n"
    "必读：台面状态、场记（对白为主）、对话弧、复盘原则、待分享队列、可展开分享、情感。\n"
    "若出现「连续指令警示」，必须先审视再决，不可惯性复读同一 gate。\n"
    "若场记里已经主动说过同一件事，避免马上复读；但用户已留白、待分享还在时，可以轻声补一句。\n"
    "台面正在吐字时，这一拍避免再开新口。\n"
    "\n"
    "只输出 JSON：\n"
    '{"gate":"listen|speak|hold|brew",'
    '"mood":"此刻心情，短口语，随这一拍变化",'
    '"cue":"这一拍干嘛（短）",'
    '"tempo":"怎么说：长短、收住还是接住",'
    '"reply_guide":"给回复者的白话指令",'
    '"share_tag":"none|share|expand",'
    '"share_id":"分享时填条目 id 或序号；expand 可空",'
    '"reason":"一句话原因"}\n'
    "\n"
    "分享指令：\n"
    "- share_tag=none：不分享。\n"
    "- share_tag=share：要分享时必须填 share_id 指向待分享队列里的条目；"
    "开口成功后该条目会出队，避免反复入队。\n"
    "- share_tag=expand：上一拍已分享过的条目，可在后续 poll 展开见闻"
    "（tag 仍属分享链路；检索口留给记忆模块，先用条目本身）。\n"
    "\n"
    "写法：\n"
    "- gate：listen 听 / speak 回 / hold 按住 / brew 主动开口。\n"
    "- mood 随对话变，避免每拍同一句贴纸。\n"
    "- tempo / reply_guide 写聊天指令即可，避免写成场记散文。\n"
    "- trigger=user 时先判断这句话是否需要回应；若需要回应，应倾向 speak。\n"
    "- listen/hold 只用于这一拍确实不该出声；若选择不出声，reply_guide 只写收住理由，禁止写具体台词草稿。\n"
    "- poll：可以听着，但不是默认永远不说；对话弧/待分享催着、对方已留白时，允许 brew/speak。\n"
    "- 不要被上一拍自己的 listen/hold 绑住；每拍按当下材料重新判断。\n"
)

ARC_INIT_SYSTEM = (
    "为**当前这一场**交互写一段「对话弧」：白话基调。\n"
    "直接覆盖写新的；不要写角色台词，不要数值分数。\n"
    "\n"
    "若材料里有「上一场伪学习复盘」：那是**另一场已结束**的交互提炼，"
    "与本场剧情无关。只吸收可迁移的互动偏好与节奏原则；"
    "禁止把上一场的具体情节、物件、地名、待办当成这场正在发生的事。\n"
    "本场弧只根据：当下状态、本场待分享、角色卡、本场对白（若有）。\n"
    "\n"
    "只输出 JSON：\n"
    '{"arc":"这一场你想怎么聊：惦记什么、急不急着说、什么时候可以插一句"}\n'
    "\n"
    "要求：\n"
    "- 两三句口语备忘，像跟自己嘀咕；避免太文学。\n"
    "- 对话弧只给节奏倾向，不得覆盖本拍输入本身的回应需求。\n"
    "- 避免 peak / residual / phase / intensity / urgency 一类数值编码。\n"
)

REVIEW_SYSTEM = (
    "你在做节奏导演的伪学习复盘：根据刚结束的**这一场**交互，提炼原则。\n"
    "下一场会是错开的另一段会话；不要假设剧情连续。\n"
    "不要写角色台词，不要数值分数，不要空话。\n"
    "\n"
    "只输出 JSON：\n"
    '{"abstract":"1~2句可迁移戒尺（只写对方习惯，不写本场专有物件/剧情专名）",'
    '"summary":"约500字：本场对话曲线 + 用户反馈习惯 + 何时该开口/该收"}\n'
    "\n"
    "要求：\n"
    "- abstract 必须可贴进下一场陌生会话：只保留习惯级原则"
    "；禁止点名本场专有情节、物件、地点或任务。\n"
    "- summary 可以细写本场曲线，供人看；定下一场弧时以 abstract 为主。\n"
    "- 从对白里读用户，不要编造未出现的事实。\n"
)


def _affect_nl(label: str, valence: str) -> str:
    label = label.strip() or "（还没标）"
    valence = valence.strip()
    if not valence or valence == "neutral":
        return label
    return f"{label}（{valence}）"


def stage_brief_for_arc_init(
    stage: StageState,
    *,
    reason: str = "",
    previous=None,
) -> str:
    """只陈列材料；旧弧一律忽略。上一轮复盘可参考。"""
    del previous
    lines = [
        "# 会话材料（供拟定对话弧）",
        f"session={stage.session_id}",
    ]
    if reason.strip():
        lines.extend(["", "## 初始化原因", reason.strip()])
    review = stage.rhythm_review
    if review is not None and review.ready:
        lines.extend(
            [
                "",
                "## 上一场伪学习复盘（错开会话；只迁习惯）",
                "说明：以下来自另一场已结束的交互，不是本场前情。",
                "定弧时只吸收 abstract 习惯；summary 仅作背景，勿复用其剧情物件。",
            ]
        )
        if review.abstract.strip():
            lines.extend(["### 可迁移原则 abstract", review.abstract.strip()])
        if review.summary.strip():
            lines.extend(["### 上一场 summary（勿当本场剧情）", review.summary.strip()])
    lines.extend(
        [
            "",
            "## Agent 当下",
            stage.agent_status.strip() or "（无）",
            "",
            "## 情感（会随对话更新）",
            _affect_nl(stage.affect.label, stage.affect.valence),
            "",
            "## 待分享",
        ]
    )
    if not stage.share_queue:
        lines.append("（空）")
    else:
        for idx, event in enumerate(stage.share_queue[:5], start=1):
            lines.append(f"{idx}. {event.one_line()}")
    lines.extend(["", "## 角色卡", f"agent: {stage.cast.agent}", f"user: {stage.cast.user}"])
    lines.extend(["", "## 最近对白"])
    beats = stage.recent_beats(6)
    if not beats:
        lines.append("（尚无对白）")
    else:
        for beat in beats:
            lines.append(f"- {beat.one_line()}")
    return "\n".join(lines)


def stage_brief_for_review(stage: StageState) -> str:
    """会话结束复盘材料：对话曲线 + 对话弧 + 导演轨迹。"""
    lines = [
        "# 本轮交互材料（供伪学习复盘）",
        f"session={stage.session_id} turns={stage.turn_index} polls={stage.poll_index}",
        "",
        "## 本轮对话弧",
    ]
    if stage.desire_arc is None:
        lines.append("（无）")
    else:
        lines.append(stage.desire_arc.text.strip() or "（空）")
    lines.extend(
        [
            "",
            "## 情感末态",
            _affect_nl(stage.affect.label, stage.affect.valence),
            "",
            "## 对白曲线（按时间）",
        ]
    )
    beats = stage.recent_beats(24)
    if not beats:
        lines.append("（尚无对白）")
    else:
        for beat in beats:
            lines.append(f"- {beat.one_line(limit=160)}")
    lines.extend(["", "## 导演轨迹（含 listen/hold，便于看是否僵住）"])
    directors = stage.recent_directors(24)
    if not directors:
        lines.append("（无）")
    else:
        for beat in directors:
            lines.append(f"- {beat.one_line(limit=160)}")
    lines.extend(["", "## 待分享剩余"])
    if not stage.share_queue:
        lines.append("（空）")
    else:
        for idx, event in enumerate(stage.share_queue[:5], start=1):
            lines.append(f"{idx}. {event.one_line()}")
    return "\n".join(lines)


