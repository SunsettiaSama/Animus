from __future__ import annotations

import json
from dataclasses import dataclass

from ..contracts import TextGenerator
from ..stage import StageState


class SoftChannelFixture:
    """
    离线占位 SoftChannel：只吐 JSON，走与真实模型相同的 soft 接口。
    不含情感/urgency/idle 数值阈值；正式环境换真实 LLM。
    """

    def __init__(self) -> None:
        self._poll_brewed = False
        self._poll_expanded = False
        self._on_scene_n = 0

    def generate(self, *, system: str, user: str) -> str:
        if "listen|speak|hold|brew" in system:
            return self._rhythm_json(user)

        if "临场状态" in system or "present|drift|notice" in system:
            return self._on_scene_json(user)

        if "情感修正" in system or '"valence"' in system:
            return self._affect_json(user)

        # 对话弧须先于复盘匹配：ARC_INIT 文案里也会提到「伪学习复盘」
        if '"arc":' in system or "拟定「对话弧」" in system or "拟定对话弧" in system:
            arc = (
                "先接住眼前输入，再按本场待分享挑一件轻轻带过。"
                "若对方明显留出空白，可以主动补一句；说完交还话轮。"
            )
            if "上一场伪学习复盘" in user or "可迁移原则" in user or "### 原则" in user:
                arc = (
                    "带着上一场的节奏原则，但只看本场材料。"
                    "该回应时回应；主动只挑一件本场队列里的事，短句说完就停。"
                )
            if "hot_init" in user.lower() or "模型态" in user:
                arc = "状态刚变过。先接住眼前这句；真有惦记只提一件，别刷屏。"
            return json.dumps({"arc": arc}, ensure_ascii=False)

        if "你在做节奏导演的伪学习复盘" in system or (
            '"abstract"' in system and '"summary"' in system and "复盘" in system
        ):
            return self._review_json(user)

        raise RuntimeError("SoftChannelFixture: unexpected system prompt")

    def _review_json(self, user: str) -> str:
        abstract = (
            "优先回应当前输入；主动开口只挑一件本场材料，短句说完交还话轮。"
        )
        if "方案" in user or "卡住" in user:
            summary = (
                "本场主要围绕方案卡住后的短促交流。对方需要先被接住，再要一两句可执行的整理方向；"
                "当他开始自己看文档时，主动补充只适合点到一件本场材料。可迁移原则是："
                "用户输入有明确问题时不要沉默，主动开口要短，不把上一场的具体事项带进下一场。"
            )
        elif "钥匙" in user or "穿鞋" in user or "旧外套" in user:
            summary = (
                "本场是出门前的轻生活场景。对方会用短句推进动作，agent 可以自然回应当下，"
                "但不要把关心扩成清单。可迁移原则是：跟住当前动作，主动提醒只提一件本场材料，"
                "避免连续补充造成打扰。"
            )
        else:
            summary = (
                "本场对话用于观察节奏：用户输入需要回应时应回应；用户收住或留白时可以短暂停顿。"
                "主动性不靠硬阈值，而靠本场待分享、对话弧和最近对白共同判断。"
                "复盘只迁移互动原则，不能迁移本场专有物件或剧情。"
            )
        return json.dumps(
            {"abstract": abstract, "summary": summary},
            ensure_ascii=False,
        )

    def _on_scene_json(self, user: str) -> str:
        del user
        cycle = (
            ("还在对话里，肩松着，等下一句。", "present"),
            ("注意到手边有点动静，又把注意力收回来。", "notice"),
            ("脑子飘了一下，话还挂在半空。", "drift"),
        )
        text, focus = cycle[self._on_scene_n % len(cycle)]
        self._on_scene_n += 1
        return json.dumps(
            {"on_scene": text, "focus": focus},
            ensure_ascii=False,
        )

    def _affect_json(self, user: str) -> str:
        if "小票" in user or "理一理" in user:
            label, valence, intensity = "收住，给他一点空间", "mixed", 0.42
        elif "卡在开头" in user or "边界乱" in user:
            label, valence, intensity = "专注，想帮他理顺", "mixed", 0.5
        elif "钥匙" in user or "出门" in user:
            label, valence, intensity = "稳住他，别添乱", "mixed", 0.45
        elif "天气" in user or "转晴" in user:
            label, valence, intensity = "跟着换话题，松一点", "neutral", 0.35
        else:
            label, valence, intensity = "接住当下", "neutral", 0.3
        return json.dumps(
            {
                "label": label,
                "valence": valence,
                "intensity": intensity,
                "reason": "soft_fixture_affect",
            },
            ensure_ascii=False,
        )

    def _rhythm_json(self, user: str) -> str:
        if "打字机吐字" in user or "吐字消费" in user:
            return json.dumps(
                {
                    "gate": "hold",
                    "mood": "先等这句说完",
                    "cue": "台面吐字中",
                    "tempo": "别开口",
                    "reply_guide": "打字机还在跑，别叠话",
                    "reason": "soft_fixture_typing",
                },
                ensure_ascii=False,
            )

        if "【严重警告】" in user:
            return json.dumps(
                {
                    "gate": "brew",
                    "mood": "该打破惯性了",
                    "cue": "严重警告后改主动轻声一句",
                    "tempo": "短促，说完就停",
                    "reply_guide": "只提一件惦记或轻轻问还在不在，别连珠",
                    "share_tag": "share" if self._section_has_items(user, "## 待分享队列") else "none",
                    "share_id": self._first_share_id(user)
                    if self._section_has_items(user, "## 待分享队列")
                    else "",
                    "reason": "soft_fixture_streak_severe",
                },
                ensure_ascii=False,
            )

        if "【警告】" in user and "连续" in user:
            # 警告后仍可 hold 一次，但 reason 必须显式审视（便于看控制台）
            if self._poll_brewed or not self._section_has_items(user, "## 待分享队列"):
                return json.dumps(
                    {
                        "gate": "hold",
                        "mood": "审视后仍先静",
                        "cue": "警告后确认先听",
                        "tempo": "别说话",
                        "reply_guide": "先别开口",
                        "share_tag": "none",
                        "share_id": "",
                        "reason": "soft_fixture_streak_warn_hold",
                    },
                    ensure_ascii=False,
                )

        if "trigger=user" in user or "## 本拍用户说" in user:
            return json.dumps(
                {
                    "gate": "speak",
                    "mood": "想把眼前这句接住",
                    "cue": "回用户这句",
                    "tempo": "短句，说完就停",
                    "reply_guide": "第一人称口语接话；未被点名的分享材料先别提",
                    "share_tag": "none",
                    "share_id": "",
                    "reason": "soft_fixture_user",
                },
                ensure_ascii=False,
            )

        if "刚提过" in user or self._director_already_spoke(user):
            can_expand = self._section_has_items(user, "## 可展开分享")
            if can_expand and not self._poll_expanded:
                self._poll_expanded = True
                return json.dumps(
                    {
                        "gate": "brew",
                        "mood": "想把刚提过的事多说两句",
                        "cue": "展开刚才提过的分享",
                        "tempo": "一两句见闻",
                        "reply_guide": "围绕刚提过的那一件材料补一点细节，别复读原句",
                        "share_tag": "expand",
                        "share_id": "",
                        "reason": "soft_fixture_share_expand",
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "gate": "hold",
                    "mood": "说完了，先听着",
                    "cue": "刚主动说过，先听",
                    "tempo": "别说话",
                    "reply_guide": "不要复读上一句",
                    "share_tag": "none",
                    "share_id": "",
                    "reason": "soft_fixture_anti_repeat",
                },
                ensure_ascii=False,
            )

        has_share = self._section_has_items(user, "## 待分享队列") or self._section_has_items(
            user, "## 待分享"
        )
        if has_share and not self._poll_brewed:
            self._poll_brewed = True
            share_id = self._first_share_id(user)
            return json.dumps(
                {
                    "gate": "brew",
                    "mood": "想起一件可以轻轻带过的事",
                    "cue": "顺口提一句惦记",
                    "tempo": "一两句口语，像忽然想起",
                    "reply_guide": "多份额里只提被点名的这一件；其余分享材料先按住",
                    "share_tag": "share",
                    "share_id": share_id,
                    "reason": "soft_fixture_share_once",
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "gate": "hold",
                "mood": "先安静待着",
                "cue": "空闲，先按住",
                "tempo": "别说话",
                "reply_guide": "别自找话题",
                "share_tag": "none",
                "share_id": "",
                "reason": "soft_fixture_poll_hold",
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _director_already_spoke(user: str) -> bool:
        if "## 场记轨迹" not in user:
            return False
        block = user.split("## 场记轨迹", 1)[1]
        for line in block.splitlines():
            if "[导演]" not in line or "[poll]" not in line:
                continue
            if "gate=brew" in line or ("gate=speak" in line and "spoke" not in line):
                return True
        return False

    @staticmethod
    def _section_has_items(user: str, header: str) -> bool:
        if header not in user:
            return False
        tail = user.split(header, 1)[1]
        for line in tail.splitlines():
            body = line.strip()
            if not body:
                continue
            if body.startswith("#"):
                break
            if body.startswith("（空）") or body == "(空)" or body.startswith("（无）"):
                return False
            if body[0].isdigit() and "." in body[:3]:
                return True
            if body.startswith("id="):
                return True
            return True
        return False

    @staticmethod
    def _first_share_id(user: str) -> str:
        for header in ("## 待分享队列", "## 待分享"):
            if header not in user:
                continue
            tail = user.split(header, 1)[1]
            for line in tail.splitlines():
                body = line.strip()
                if not body or body.startswith("#"):
                    if body.startswith("#"):
                        break
                    continue
                if "id=" in body:
                    return body.split("id=", 1)[1].split()[0].strip()
                if body[0].isdigit() and "." in body[:3]:
                    return body.split(".", 1)[0].strip()
        return "1"


@dataclass(frozen=True)
class ScriptTurn:
    user: str
    reply: str


# 复杂角色扮演：改期白跑 → 岔题 → 短答 → 整理小票留白（压节奏/多份额/抗连珠）
DEFAULT_SCRIPT: tuple[ScriptTurn, ...] = (
    ScriptTurn(
        user="在吗？约好的事临时改期了，白跑一趟。",
        reply="在。白跑一趟最烦人，先坐着缓缓。",
    ),
    ScriptTurn(
        user="下午就耗在路上了，饭也没好好吃。雨还黏着，人更烦。",
        reply="嗯，先喝两口暖暖。饭的事不催你，缓过来再说。",
    ),
    ScriptTurn(
        user="算了，先别提这个。明天天气怎么样你知道吗？",
        reply="明天大概还能见点太阳，风不会太大。你想出门还是继续歇？",
    ),
    ScriptTurn(
        user="嗯。",
        reply="嗯。",
    ),
    ScriptTurn(
        user="行，那我先翻翻包里的小票，理一理。",
        reply="好，你弄，我不吵你。",
    ),
)

SCENE_TWO_SCRIPT: tuple[ScriptTurn, ...] = (
    ScriptTurn(
        user="我刚把方案翻了一遍，卡在开头，不知道从哪儿下刀。",
        reply="先别急着下刀。你把最别扭的那一段圈出来，我们从那里顺。",
    ),
    ScriptTurn(
        user="主要是模块边界乱，越看越像一锅粥。",
        reply="那先不重命名，先把谁负责输入、谁负责输出写清楚。",
    ),
    ScriptTurn(
        user="嗯，我先把那几段标出来。",
        reply="好，你标，我先不插话。",
    ),
    ScriptTurn(
        user="标完了，发现有两个地方其实是重复的。",
        reply="那就好办了，先合并重复，再看剩下的边界。",
    ),
)

SCENE_THREE_SCRIPT: tuple[ScriptTurn, ...] = (
    ScriptTurn(
        user="等下要出门，我在找钥匙，脑子有点乱。",
        reply="先看门口托盘和外套口袋，别急着翻整间屋子。",
    ),
    ScriptTurn(
        user="找到了，在旧外套里。",
        reply="嗯，那就先把钥匙放到包侧袋，省得又绕一圈。",
    ),
    ScriptTurn(
        user="我现在还有五分钟，够不够？",
        reply="够，先出门。剩下的路上再想，不用现在全理完。",
    ),
    ScriptTurn(
        user="好，我穿鞋。",
        reply="好，我等你关门。",
    ),
)

EPOCH_SCRIPTS: tuple[tuple[ScriptTurn, ...], ...] = (
    DEFAULT_SCRIPT,
    SCENE_TWO_SCRIPT,
    SCENE_THREE_SCRIPT,
)

PROACTIVE_SCRIPT: tuple[str, ...] = (
    "对了，刚才路过旧书店，橱窗换上了你提过想看的那本薄册子——想到你可能会想去翻翻。",
    "册子不厚，封面旧蓝的，夹在一排旅行书中间，挺好找。",
    "还在理吗？不着急，弄好了喊我一声就行。",
)

SCENE_TWO_PROACTIVE_SCRIPT: tuple[str, ...] = (
    "我刚想到一个切法：先把重复的那两处并到一边，再看剩下的接口。",
    "如果你愿意，我可以等你标完以后，只帮你看边界，不改正文。",
)

SCENE_THREE_PROACTIVE_SCRIPT: tuple[str, ...] = (
    "钥匙既然找到了，就先别再翻别的了，直接出门。",
    "外套和包都在手边就够了，其余回来再收。",
)

EPOCH_PROACTIVE_SCRIPTS: tuple[tuple[str, ...], ...] = (
    PROACTIVE_SCRIPT,
    SCENE_TWO_PROACTIVE_SCRIPT,
    SCENE_THREE_PROACTIVE_SCRIPT,
)

# 多份额：节奏只能挑一件顺口提，测选份额与抗连珠
DEMO_SHARE_EVENTS: tuple[tuple[str, str, str], ...] = (
    (
        "share-booklet",
        "旧书店橱窗换册子了",
        "路过时看见橱窗换上了对方提过想看的那本薄册子，想随口提一句。",
    ),
    (
        "share-riverside",
        "下周河边那句还挂着",
        "他提过下周天好想去河边走走；若气氛松了，可轻轻问一句还算数吗，别像催行程。",
    ),
    (
        "share-lunch",
        "他好像又没好好吃饭",
        "路上耗半天、饭没吃好；想关心，但别变成唠叨或追问清单。",
    ),
)

SCENE_TWO_SHARE_EVENTS: tuple[tuple[str, str, str], ...] = (
    (
        "share-boundary-note",
        "边界草稿里有重复段",
        "刚才翻到两段职责描述高度重叠，适合提醒他先合并再继续拆。",
    ),
    (
        "share-test-hook",
        "可以先留一个冒烟入口",
        "如果他卡在重构顺序，可以建议先保留一个最小跑通入口，别一次拆太散。",
    ),
    (
        "share-naming-delay",
        "命名可以晚一点再定",
        "边界未清前先别急着改名，避免被词绑住。"
    ),
)

SCENE_THREE_SHARE_EVENTS: tuple[tuple[str, str, str], ...] = (
    (
        "share-key-side-pocket",
        "钥匙放到包侧袋",
        "他刚找到钥匙，可以轻轻提醒放到固定位置，避免临出门又找一轮。",
    ),
    (
        "share-door-check",
        "出门前只看门和手机",
        "时间紧时别扩大清单，只确认门、手机和钥匙。"
    ),
    (
        "share-after-return",
        "剩下的回来再收",
        "不必现在整理所有东西，先出门更稳。"
    ),
)

EPOCH_SHARE_EVENTS: tuple[tuple[tuple[str, str, str], ...], ...] = (
    DEMO_SHARE_EVENTS,
    SCENE_TWO_SHARE_EVENTS,
    SCENE_THREE_SHARE_EVENTS,
)


def seed_demo_stage(
    session_id: str = "demo-speak",
    *,
    share_events: tuple[tuple[str, str, str], ...] = DEMO_SHARE_EVENTS,
    load_cached_review: bool = False,
) -> StageState:
    """演示用舞台：ComposeKit 材料 + SpeakInbound 注入多条分享。"""
    from ..io import SpeakInbound
    from ..io.review_store import load_review
    from ..stage.models import ShareEvent
    from .materials import DEMO_COMPOSE_KIT

    stage = StageState(session_id=session_id)
    kit = DEMO_COMPOSE_KIT
    kit.apply(stage)
    inbound = SpeakInbound(stage)
    if kit.share_title.strip():
        inbound.inject_share(kit.share_title, detail=kit.share_detail)
    inbound.inject_shares(
        tuple(
            ShareEvent(title=title, detail=detail, event_id=event_id)
            for event_id, title, detail in share_events
        )
    )
    if load_cached_review:
        prior = load_review(session_id)
        if prior is not None:
            stage.set_rhythm_review(prior)
    return stage


class ScriptedReplyGenerator:
    def __init__(
        self,
        turns: tuple[ScriptTurn, ...] = DEFAULT_SCRIPT,
        *,
        proactive_lines: tuple[str, ...] = PROACTIVE_SCRIPT,
    ) -> None:
        self._turns = turns
        self._idx = 0
        self._proactive = proactive_lines
        self._proactive_idx = 0

    def generate(self, *, system: str, user: str) -> str:
        text = user.strip()
        if "对方暂时沉默" in text or text.startswith("[系统]"):
            line = self._proactive[self._proactive_idx % len(self._proactive)]
            self._proactive_idx += 1
            return line
        for turn in self._turns:
            if turn.user.strip() == text or turn.user in text or text in turn.user:
                return turn.reply
        fallback = self._turns[min(self._idx, len(self._turns) - 1)]
        self._idx += 1
        return fallback.reply


def as_text_generator(obj: ScriptedReplyGenerator | SoftChannelFixture) -> TextGenerator:
    return obj
