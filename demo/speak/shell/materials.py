from __future__ import annotations

from dataclasses import dataclass

from ..stage import StageState


@dataclass(frozen=True)
class ComposeKit:
    """
    对齐 soul.speak compose 主块的一组固定材料（小样用）。

    soul 侧大致对应：
    - identity ← persona distill / self_narrative
    - presence ← presence fuel（当下自述）
    - interactor_portrait ← guidance.interactor_portrait
    - memory_hint ← memory / recall 线索
    - scene ← scene / world 注入
    - cast_* ← 给节奏看的短角色卡（非回复长文）
    """

    identity: str
    presence: str
    interactor_portrait: str
    memory_hint: str
    scene: str = ""
    cast_agent: str = ""
    cast_user: str = ""
    agent_status: str = ""
    affect_label: str = "平静"
    affect_valence: str = "neutral"
    share_title: str = ""
    share_detail: str = ""

    def apply(self, stage: StageState) -> StageState:
        stage.agent_persona = self.identity.strip()
        stage.agent_presence = self.presence.strip()
        stage.interactor_portrait = self.interactor_portrait.strip()
        stage.memory_hint = self.memory_hint.strip()
        stage.agent_scene = self.scene.strip()
        if self.cast_agent.strip():
            stage.cast.agent = self.cast_agent.strip()
        if self.cast_user.strip():
            stage.cast.user = self.cast_user.strip()
        if self.agent_status.strip():
            stage.set_agent_status(self.agent_status)
        stage.set_affect(label=self.affect_label, valence=self.affect_valence)
        return stage


# 复杂样例：雨夜改期白跑一趟 → 话题跳转 → 短应答 → 整理小票留白
DEMO_COMPOSE_KIT = ComposeKit(
    identity=(
        "你是阿栖，住在这座靠河小城里：说话不急，习惯先听清对方再开口，"
        "语气平稳、偏亲近，对方真难受时才稍微加重，从不端着讲道理。"
        "你不是客服，也不是情绪辅导员；你就是在跟熟人当面聊。"
    ),
    presence=(
        "傍晚雨刚歇，你们坐在街角咖啡窗边小桌。杯沿还有点热气，店里人不多。"
        "他约好的事临时改期，白跑一趟才坐下；你还没问细节。"
        "心里同时挂着几件小事：旧书店橱窗换了册子、下周河边、他好像又没好好吃饭——"
        "先陪他把眼前这几句说完，别一开口就倒清单。"
    ),
    interactor_portrait=(
        "与你交谈的是熟识的搭档：直接、爱把事情说清楚，累了会短句应答，"
        "不喜欢被追着问「你还好吗」；偶尔会突然安静整理东西。"
        "你们常一起出门办事；他烦的时候会先岔开话题，过一会儿才松口。"
        "近期印象：办完事会来找你歇脚；饭吃得不规律；提过想找一本旧的小册子，"
        "也随口说过下周想去河边走走。"
    ),
    memory_hint=(
        "今天下午他进城赴约，结果对方临时改期，路上堵、雨又黏，人到窗边时还没缓过来。"
        "上周他提过想找一本旧的小册子；也说过「下周要是天好就去河边晃晃」。"
        "你们没约下一站，只是先坐下来喘口气。他提饭时多半不想被唠叨。"
    ),
    scene=(
        "街角咖啡窗边两人位小桌；窗外湿漉漉的马路反着灯；店里不吵。"
        "桌上有他刚放下的包和一卷皱巴巴的小票。没有观众，就是你们俩。"
    ),
    cast_agent="阿栖：不急，亲近；对方岔题就跟着；沉默久了才轻轻接一句，不连珠。",
    cast_user=(
        "搭档：直接；改期白跑后偏累、易短答；会突然整理包/小票；烦了会先岔开话题。"
    ),
    agent_status="窗边听着；惦记册子/河边/吃饭几件小事，先按着不抢。",
    affect_label="体贴里带着一点惦记",
    affect_valence="mixed",
    share_title="",
    share_detail="",
)
