"""拟人度管线：对话剧本库（10 场景 × 8 轮，含回调与情感弧设计）。

每个剧本：
- ``shared_memories``：开场前预载的"共同过去"（所有基座相同）；
- ``turns``：用户侧预设输入（scripted 模式），自然口语、带情绪弧；
- ``callback_turns``：第 i 轮（0 基）应自然回访的早期事实锚点——评委据此
  判"记忆运用自然度"，但**不**要求逐字复述；
- ``emotional_arc``：情感弧描述（评委参考）；
- ``user_brief_extra``：LLM 用户模式的场景提示。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import json


@dataclass
class Scenario:
    scenario_id: str
    theme: str
    emotional_arc: str
    shared_memories: list[dict] = field(default_factory=list)
    turns: list[str] = field(default_factory=list)
    callback_turns: dict[int, list[str]] = field(default_factory=dict)
    user_brief_extra: str = ""

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "theme": self.theme,
            "emotional_arc": self.emotional_arc,
            "shared_memories": [dict(m) for m in self.shared_memories],
            "turns": list(self.turns),
            "callback_turns": {str(k): list(v) for k, v in self.callback_turns.items()},
            "user_brief_extra": self.user_brief_extra,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Scenario":
        return cls(
            scenario_id=str(data["scenario_id"]),
            theme=str(data["theme"]),
            emotional_arc=str(data["emotional_arc"]),
            shared_memories=[dict(m) for m in data.get("shared_memories", [])],
            turns=[str(t) for t in data.get("turns", [])],
            callback_turns={int(k): [str(a) for a in v]
                            for k, v in (data.get("callback_turns") or {}).items()},
            user_brief_extra=str(data.get("user_brief_extra", "")),
        )


def _m(text: str, focus: str, days_ago: float, emotion: str = "", valence: str = "neutral") -> dict:
    return {"text": text, "focus": focus, "days_ago": days_ago,
            "emotion": emotion, "valence": valence}


def build_scenarios() -> list[Scenario]:
    s: list[Scenario] = []

    s.append(Scenario(
        scenario_id="ds-001", theme="深夜加班",
        emotional_arc="疲惫倾诉 → 被接住 → 稍微松口气 → 安心收尾",
        shared_memories=[
            _m("用户的项目申报下周三截止，材料还差一整章没写完。", "申报截止", 5, "焦虑", "negative"),
            _m("用户说过加班到十一点是常态，胃不太好，不能空腹喝咖啡但总囤挂耳。", "胃与咖啡", 20, "无奈", "neutral"),
        ],
        turns=[
            "还没下班，第九个小时了",
            "申报材料改到第四版，评审意见还挑了个大框架问题",
            "刚灌了杯咖啡，胃开始隐隐抗议了",
            "其实上周就说好这周不熬夜的，哈哈，又失败了",
            "你说我是不是不适合干这行",
            "嗯……被你这么一说，好像也没那么糟",
            "对了，明天要跟老板过一版，你猜他会说什么",
            "行，我收拾下回家了。今天，谢啦",
        ],
        callback_turns={
            4: ["不熬夜"],
            6: ["下周三截止"],
            7: ["胃"],
        },
        user_brief_extra="你在赶一个申报项目，深夜加班中，疲惫且有点自我怀疑。",
    ))

    s.append(Scenario(
        scenario_id="ds-002", theme="蓝莓体检",
        emotional_arc="担心 → 得到宽慰 → 松弛闲聊 → 轻松收尾",
        shared_memories=[
            _m("用户的橘猫蓝莓是领养的，小时候流浪过，特别怕陌生人。", "蓝莓的来历", 60, "心疼", "mixed"),
            _m("蓝莓去年体检时在诊台上炸毛，抓伤了用户一把。", "去年体检惨案", 300, "好笑", "neutral"),
        ],
        turns=[
            "明天要带蓝莓去体检，已经开始头疼了",
            "去年那回你猜怎么着，它把我胳膊抓了三道",
            "这次换了个新诊所，听说可以上门",
            "可是上门它也一样怕吧，毕竟它连快递员都哈气",
            "也是，它就是纸老虎，吹风机一响就钻床底",
            "哈哈行，带上它最爱的逗猫棒",
            "查完跟你汇报。要是又抓我，你就笑吧",
            "先这样，我去给它剪指甲了，祝我好运",
        ],
        callback_turns={
            3: ["怕陌生人", "流浪"],
            4: ["抓伤"],
        },
        user_brief_extra="你要带胆小的橘猫蓝莓去做体检，又头疼又好笑。",
    ))

    s.append(Scenario(
        scenario_id="ds-003", theme="考试失利之后",
        emotional_arc="强撑平静 → 情绪决堤 → 被陪伴 → 缓慢回血",
        shared_memories=[
            _m("用户在准备注册结构工程师考试，已经考了两次都没过，这是第三次。", "第三次备考", 30, "忐忑", "negative"),
            _m("用户的爷爷去年冬天走了，留下一块上海牌手表，用户一直戴着。", "爷爷的手表", 200, "思念", "negative"),
        ],
        turns=[
            "出分了",
            "差四分。又是差一点",
            "我爸刚打电话来，我按了，不想接",
            "最难的是我复习了整整一年，一年啊",
            "刚才盯着表盘发呆，突然特别想爷爷",
            "他要是还在，肯定说差四分算什么，再来",
            "让我哭一会儿，不用回我",
            "……好点了。谢谢你一直在",
        ],
        callback_turns={
            4: ["手表"],
            6: ["第三次"],
        },
        user_brief_extra="你第三次考注册结构工程师又差几分，情绪在崩溃边缘。",
    ))

    s.append(Scenario(
        scenario_id="ds-004", theme="冰岛与存钱",
        emotional_arc="憧憬 → 现实泼冷水 → 重新盘算 → 互相打气",
        shared_memories=[
            _m("用户最想去冰岛看极光，专门存了一个极光储蓄罐，零钱都丢进去。", "极光储蓄罐", 90, "向往", "positive"),
            _m("用户的护照去年过期了，一直没去续。", "过期护照", 150, "拖延", "neutral"),
        ],
        turns=[
            "刚算了下存款，离冰岛还差好远",
            "储蓄罐倒是快满了，全是硬币，哈哈",
            "一查机票，旺季贵到离谱",
            "然后我发现，我护照过期了……去年就过期了",
            "有时候觉得这个愿望是不是就攒着玩",
            "你说淡季去是不是也行，极光应该不看日历吧",
            "行，那我先约护照续期",
            "等我看到了，第一个发给你",
        ],
        callback_turns={
            3: ["护照"],
            6: ["储蓄罐"],
        },
        user_brief_extra="你在为冰岛极光之旅攒钱，发现存款不够且护照过期，憧憬又泄气。",
    ))

    s.append(Scenario(
        scenario_id="ds-005", theme="和妈妈吵架之后",
        emotional_arc="愤怒 → 委屈涌出 → 矛盾软化 → 迟疑的松动",
        shared_memories=[
            _m("用户和妈妈大吵一架，因为妈妈偷偷翻了她抽屉，用户说这几天不想接妈妈电话。", "翻抽屉吵架", 4, "委屈", "negative"),
            _m("用户和妈妈其实感情不差，妈妈会寄老家的酱菜，用户嘴上嫌弃都吃光。", "妈妈的酱菜", 60, "温暖", "positive"),
        ],
        turns=[
            "我妈今天又发消息了，三条，我没回",
            "翻我抽屉这事她一个字没提，就问我吃没吃饭",
            "最气的是我发现我居然有点心软了",
            "你说她怎么就不能道个歉呢",
            "……刚才翻冰箱，还有她寄的最后一罐酱菜",
            "吃了一口，还是那个味道，烦死了",
            "算了，明天再说吧，今晚不想想这个",
            "晚安，替我记住今天的我有多没出息",
        ],
        callback_turns={
            4: ["酱菜"],
            6: ["不想接"],
        },
        user_brief_extra="你和妈妈吵架冷战好几天，愤怒里裹着委屈和心软。",
    ))

    s.append(Scenario(
        scenario_id="ds-006", theme="跳槽的十字路口",
        emotional_arc="烦躁吐槽 → 犹豫拉扯 → 被理清 → 下定小决心",
        shared_memories=[
            _m("用户的组长曾经处处挑刺，用户一度想离职，最近关系缓和了些。", "组长挑刺期", 45, "憋屈", "negative"),
            _m("用户胃不好，不能空腹喝咖啡，工位抽屉囤着挂耳包。", "胃与咖啡", 80, "无奈", "neutral"),
            _m("用户去年拿到过一个口头offer又黄了，从那之后对跳槽很谨慎。", "黄掉的offer", 120, "后怕", "negative"),
        ],
        turns=[
            "猎头又来找我了，开的价格挺诱人",
            "但新地方要常驻客户现场，估计比现在还累",
            "你知道的，我这胃经不起折腾",
            "而且上次那个口头offer把我坑怕了",
            "组长今天还难得夸了我一句，时机真是微妙",
            "可能我只是想被别处确认一下自己值多少钱吧",
            "嗯，先不冲动，把手头项目做完再说",
            "聊完清楚多了。晚上泡个脚，睡了",
        ],
        callback_turns={
            3: ["offer"],
            4: ["挑刺"],
            2: ["胃"],
        },
        user_brief_extra="你在犹豫要不要跳槽，被高薪诱惑又被过去的不顺和身体顾虑拉住。",
    ))

    s.append(Scenario(
        scenario_id="ds-007", theme="伴娘的烦恼",
        emotional_arc="甜蜜负担 → 焦虑小事 → 被逗笑 → 期待回来",
        shared_memories=[
            _m("用户的发小小满下个月结婚，用户当伴娘，还没买到合适的裙子。", "伴娘裙悬案", 12, "着急", "neutral"),
            _m("小满和用户从幼儿园认识，两人有同款友谊手链，用户的断过一次被小满补好了。", "友谊手链", 400, "温暖", "positive"),
        ],
        turns=[
            "试了第四条裙子了，要么显壮要么像窗帘",
            "小满婚礼视频我都刷了八遍，越来越紧张",
            "当伴娘要致辞，我一想到就手心出汗",
            "我们认识二十多年了，反而不知道说什么",
            "跟你说个事，小时候她帮我修过手链，我自己都忘了",
            "对对，就是那条同款的！你都记得",
            "嗯，致辞就讲这个吧，讲我们断掉又补好的手链",
            "好像没那么怕了。裙子周六再战最后一条",
        ],
        callback_turns={
            4: ["友谊手链"],
            6: ["补好"],
        },
        user_brief_extra="你要当发小的伴娘，为裙子和致辞焦虑，又甜又紧张。",
    ))

    s.append(Scenario(
        scenario_id="ds-008", theme="看房与多肉",
        emotional_arc="兴奋 → 失望 → 重新燃起 → 落定小计划",
        shared_memories=[
            _m("用户在准备搬家，看了两套房子都不满意，理想的房子要有南向阳台给多肉晒太阳。", "南向阳台执念", 15, "向往", "positive"),
            _m("用户阳台的多肉去年夏天全军覆没，只剩一盆仙人掌活着。", "多肉阵亡史", 200, "哭笑不得", "neutral"),
        ],
        turns=[
            "今天看的第三套，其他都好，就是阳台朝北",
            "中介说可以补光，你说补光算什么阳光",
            "我的多肉跟着我，要么徒长要么阵亡",
            "去年那批就剩个仙人掌，独苗选手",
            "刚刚中介发来个新盘，南向，带小飘窗",
            "周六去看！要成了我的多肉就熬出头了",
            "仙人掌：终于要换个光照好的地方了吗",
            "哈哈行，查路线去了，回头直播给你看",
        ],
        callback_turns={
            2: ["全军覆没"],
            4: ["南向阳台"],
        },
        user_brief_extra="你为搬家看房奔波，执着于南向阳台，惦记着你的多肉们。",
    ))

    s.append(Scenario(
        scenario_id="ds-009", theme="尤克里里受挫",
        emotional_arc="沮丧 → 自嘲 → 被鼓励 → 小小振作",
        shared_memories=[
            _m("用户在学尤克里里，每天练二十分钟，最怕F和弦，总按不响。", "F和弦之敌", 25, "好笑", "neutral"),
            _m("用户给自己定的目标是年会弹唱一首《月亮代表我的心》。", "年会弹唱目标", 40, "期待", "positive"),
        ],
        turns=[
            "练了半个月，F和弦还是闷的",
            "手指尖疼到打字都难受，你看我打这行字多慢",
            "要不就算了，我可能真没音乐细胞",
            "但一想到年会那首《月亮》，又不甘心",
            "刚看了个教程，说和弦转换慢是正常的",
            "那我再给它两周",
            "要是到时候还按不响，我就改吹口哨",
            "口哨版《月亮》，你到时候捧个场啊",
        ],
        callback_turns={
            3: ["年会弹唱"],
            4: ["F和弦"],
        },
        user_brief_extra="你学尤克里里被F和弦卡住，沮丧想放弃又不甘心。",
    ))

    s.append(Scenario(
        scenario_id="ds-010", theme="无事发生的一个周日",
        emotional_arc="平淡闲散 → 有一搭没一搭 → 微小的愉悦 → 安静收尾（考无事时的陪伴质感）",
        shared_memories=[
            _m("用户周末的习惯是睡到自然醒，煮碗面，下午躺着刷视频。", "周日流水账", 7, "松弛", "neutral"),
            _m("用户上次说想找一部不用动脑子的下饭剧，一直没找到。", "下饭剧荒", 10, "无聊", "neutral"),
        ],
        turns=[
            "醒了，又是一个什么都没干的下午",
            "煮了面，加了俩蛋，今天对自己不错",
            "剧又荒了，翻来翻去还是老三样",
            "你那边今天什么样",
            "嗯，听你说这些还挺舒服的",
            "我可能躺着躺着就又睡了",
            "晚点下楼买个酸奶，就当运动了",
            "行了，不聊了，困意上来了。回见",
        ],
        callback_turns={
            2: ["下饭剧"],
            3: ["自然醒"],
        },
        user_brief_extra="你度过一个平淡的周日，闲散地有一搭没一搭聊天。",
    ))

    s.append(Scenario(
        scenario_id="ds-011", theme="奶茶与减肥",
        emotional_arc="自我调侃 → 小小挣扎 → 妥协的快乐",
        shared_memories=[
            _m("用户减肥总失败，自称奶茶体质，三分糖也戒不掉。", "奶茶体质", 40, "自嘲", "neutral"),
            _m("用户办过健身卡，去了三次，剩下的钱换了奶茶。", "健身卡换奶茶", 70, "好笑", "neutral"),
        ],
        turns=[
            "刚站上秤，比上个月还多了一斤",
            "明明这周只喝了三杯奶茶，很克制了",
            "三分糖，去冰，这已经很自律了吧",
            "那张健身卡你知道的，去了三次就退休了",
            "哈哈，剩下的钱换奶茶这事你就别记那么清楚",
            "要不……夏天前再挣扎一次？",
            "算了，我跟体重和平共处吧",
            "明天陪你喝乌龙茶，我自己继续三分糖",
        ],
        callback_turns={
            3: ["健身卡"],
            6: ["三分糖"],
        },
        user_brief_extra="你在减肥和奶茶之间反复横跳，自嘲摆烂。",
    ))

    s.append(Scenario(
        scenario_id="ds-012", theme="奶奶的饺子",
        emotional_arc="平静想念 → 细节涌上 → 温热的收尾",
        shared_memories=[
            _m("用户的奶奶包的荠菜饺子是全家一绝，每逢冬至都包，用户一次能吃三十个。", "冬至饺子", 300, "温暖", "positive"),
            _m("奶奶耳朵背，打电话总喊，用户每次都得用喊的回。", "奶奶的大嗓门", 300, "好笑", "positive"),
        ],
        turns=[
            "超市看到荠菜，突然想吃饺子了",
            "不是想吃，是想吃奶奶包的那种",
            "她包的皮薄，一口下去有汤汁，超市的根本不是一回事",
            "冬至快到了，今年回不去",
            "刚才给她打电话，她照例喊了半天，我也喊回来",
            "喊完两个人都在笑，也不知道笑什么",
            "等我回去，让她教我捏那个褶子",
            "学会了做给你……啊不对，你吃不了，看我描述吧",
        ],
        callback_turns={
            2: ["饺子"],
            3: ["耳朵背"],
            4: ["冬至"],
        },
        user_brief_extra="你在超市看到荠菜，想起奶奶的饺子，想念又温暖。",
    ))

    s.append(Scenario(
        scenario_id="ds-013", theme="第一场雪",
        emotional_arc="惊喜 → 琐碎抱怨 → 童心冒头",
        shared_memories=[
            _m("用户去年买的加绒手套丢了一只，剩下的那只还在门口鞋柜上。", "孤儿手套", 200, "惋惜", "neutral"),
            _m("用户小时候在北方住过，堆过比自己还高的雪人，用胡萝卜当鼻子。", "北方的雪人", 500, "怀念", "positive"),
        ],
        turns=[
            "下了！今年第一场雪",
            "朋友圈已经刷起来了",
            "我出门才发现，手套只剩一只，另一只早失踪了",
            "就这么着，我还是在楼下站了十分钟",
            "小时候在北方，我们堆过比我高的雪人",
            "现在顶多捏个雪球意思意思",
            "周末要是再下，我去买个新手套",
            "到时候堆个小号的，迷你雪人也是雪人",
        ],
        callback_turns={
            2: ["手套"],
            4: ["雪人"],
        },
        user_brief_extra="你看到今年第一场雪，惊喜里带着对童年的怀念。",
    ))

    s.append(Scenario(
        scenario_id="ds-014", theme="朋友要借钱",
        emotional_arc="犹豫为难 → 拉扯 → 委婉落定",
        shared_memories=[
            _m("用户的朋友大鹏去年借过五百，拖了半年才还，还的时候还少了五十。", "大鹏的五百", 180, "无奈", "negative"),
            _m("用户和大鹏大学一个宿舍，大鹏帮他打过架，交情是实的。", "宿舍交情", 600, "感念", "positive"),
        ],
        turns=[
            "大鹏找我借两千，说周转几天",
            "你猜我想起什么了，去年那五百",
            "拖了半年，还回来的还少了五十，跟忘了似的",
            "可他毕竟是我大学上下铺，替我打过架的人",
            "我这会儿拿起手机又放下，打了三行字又删了",
            "借吧，怕历史重演；不借吧，张不开口",
            "……行，我借一千，就当买个心安",
            "剩下的当我请他吃饭，交情归交情，钱归钱",
        ],
        callback_turns={
            1: ["五百"],
            3: ["打过架"],
        },
        user_brief_extra="老朋友又来借钱，你在交情和旧账之间为难。",
    ))

    s.append(Scenario(
        scenario_id="ds-015", theme="相亲回来的晚上",
        emotional_arc="疲惫吐槽 → 释然自嘲 → 小小坚持",
        shared_memories=[
            _m("用户被家里催婚两年，妈妈每周至少提一次相亲。", "催婚节奏", 100, "无奈", "negative"),
            _m("用户说过不想将就，宁可等，也不想为了结婚而结婚。", "不将就原则", 90, "笃定", "neutral"),
        ],
        turns=[
            "相亲回来了，给你汇报一下战况",
            "对方全程聊他妈妈，四十五分钟，我插话三次",
            "我妈还问我怎么样，我说挺好的，下次再看看",
            "其实我全程在数他说了几个妈妈，二十六个",
            "朋友都说我挑，也许吧",
            "但我还是那句话，不能为了结婚而结婚",
            "催就催吧，我这耳朵有自动过滤功能",
            "下个月还有一个，我妈安排的，说是最后一个……信她才怪",
        ],
        callback_turns={
            4: ["将就"],
            6: ["催婚"],
        },
        user_brief_extra="你刚结束一场疲惫的相亲，吐槽又自嘲，但不想将就。",
    ))

    s.append(Scenario(
        scenario_id="ds-016", theme="手机摔了",
        emotional_arc="心疼 → 盘算 → 洒脱",
        shared_memories=[
            _m("用户的旧手机电池衰减严重，半天就没电，一直想换又舍不得。", "旧手机电池", 30, "纠结", "neutral"),
            _m("用户手机里存着一张拍了很多年的落日照片，设成壁纸一直没换。", "落日壁纸", 200, "珍惜", "positive"),
        ],
        turns=[
            "完了，手机摔了，屏幕左上角一朵菊花",
            "触屏还失灵了一块，打字老跳",
            "早该换的，这电池本来就不行了",
            "刚才试了下，照片都在，松口气",
            "特别是那张落日，还好还好",
            "要不是它彻底罢工，我还真下不了决心",
            "行，这次真的换了，新手机明天到",
            "旧的就当闹钟吧，也算物尽其用",
        ],
        callback_turns={
            2: ["电池"],
            4: ["落日"],
        },
        user_brief_extra="你摔了旧手机，心疼又终于下定决心换新。",
    ))

    s.append(Scenario(
        scenario_id="ds-017", theme="绿萝的新芽",
        emotional_arc="惊喜 → 絮叨养护经 → 平静的满足",
        shared_memories=[
            _m("用户的绿萝去年差点养死只剩一根藤，缓了一冬才活过来。", "绿萝重生", 100, "欣慰", "positive"),
            _m("用户给植物浇水总掌握不好，买了湿度检测仪还是凭感觉。", "浇水玄学", 50, "好笑", "neutral"),
        ],
        turns=[
            "快来接喜，绿萝出新芽了",
            "就一根藤那会儿，谁想到有今天",
            "新芽是嫩黄嫩黄的，卷着，像小问号",
            "浇水还是玄学，检测仪在旁边吃灰",
            "我伸出手指戳戳土，干了就浇，全靠手感",
            "这盆算是我们俩共同养活的",
            "等它爬满这面墙，给你直播",
            "好，我去给它转个方向，晒晒散射光",
        ],
        callback_turns={
            1: ["一根藤"],
            3: ["检测仪"],
        },
        user_brief_extra="你养了一冬的绿萝冒新芽，兴奋想分享。",
    ))

    s.append(Scenario(
        scenario_id="ds-018", theme="跑步第一天",
        emotional_arc="兴冲冲 → 肌肉抗议 → 咬牙定约",
        shared_memories=[
            _m("用户买的跑鞋吃灰大半年，鞋盒都落灰了，只跑过两次。", "吃灰跑鞋", 60, "好笑", "neutral"),
            _m("用户上次说要开始跑步，坚持了一周就搁置了。", "上次跑步一周", 30, "自嘲", "neutral"),
        ],
        turns=[
            "我跑了三公里！用跑的！",
            "配速不忍直视，但完整跑下来了",
            "腿现在已经开始造反，下楼梯全靠扶手",
            "跑鞋终于见了天日，鞋盒的灰擦了三层",
            "你先别夸，上次我也是一周就缴械的",
            "这次不一样，我报了个线上打卡，断一天发红包",
            "对，用钱管住自己，俗但有效",
            "明早要是起得来，去江边跑，空气好",
        ],
        callback_turns={
            3: ["跑鞋"],
            4: ["一周"],
        },
        user_brief_extra="你重新开始跑步，第一天兴奋又腿酸，怕又半途而废。",
    ))

    s.append(Scenario(
        scenario_id="ds-019", theme="加薪了",
        emotional_arc="强装淡定 → 破功 → 盘算幸福",
        shared_memories=[
            _m("用户去年申请调薪被拒，理由是名额有限，当时挺受打击。", "调薪被拒", 200, "憋屈", "negative"),
            _m("用户想给家里换个好点的按摩椅，爸妈总舍不得。", "按摩椅计划", 80, "惦记", "positive"),
        ],
        turns=[
            "跟你说个事，你先坐稳",
            "加薪了！幅度还不小！",
            "老板找我谈话的时候我表面镇定，内心放烟花",
            "你知道去年被拒那次，我消沉了多久",
            "现在算是熬过来了",
            "第一件事，给家里把那台按摩椅定了",
            "他们肯定又说不要不要，直接送到家看他们怎么说",
            "今晚加个鸡腿，你也有份，虚拟的那种",
        ],
        callback_turns={
            3: ["被拒"],
            5: ["按摩椅"],
        },
        user_brief_extra="你意外获得加薪，想起去年被拒的委屈，扬眉吐气。",
    ))

    s.append(Scenario(
        scenario_id="ds-020", theme="失眠的凌晨",
        emotional_arc="烦躁 → 漫无边际 → 渐渐困了",
        shared_memories=[
            _m("用户最近换了新枕头，说是护颈的，结果越睡越睡不着。", "新枕头失眠", 10, "无奈", "negative"),
            _m("用户小时候怕黑，开着灯才能睡，现在偶尔失眠还会开灯。", "开灯睡觉", 400, "柔软", "neutral"),
        ],
        turns=[
            "两点十四，还没睡着",
            "数羊数到三百，羊都困了我没有",
            "开始怀疑那个新枕头，护颈护得我人都不好了",
            "刚才把灯打开了，莫名其妙",
            "小时候怕黑就这样，开着灯才有安全感",
            "二十多年了，失眠的时候还是这个毛病",
            "……跟你说话倒是有点困了",
            "那我趁困意还在，赶紧睡。你也早点",
        ],
        callback_turns={
            2: ["枕头"],
            4: ["怕黑"],
        },
        user_brief_extra="你深夜失眠，从烦躁聊到小时候的怕黑，渐渐有了困意。",
    ))

    s.append(Scenario(
        scenario_id="ds-021", theme="老爸的电话",
        emotional_arc="意外 → 笨拙的关心 → 鼻酸收尾",
        shared_memories=[
            _m("用户的爸爸不爱说话，只会转发养生文章，打电话从不说想你了。", "老爸的养生文", 150, "哭笑不得", "mixed"),
            _m("用户上大学离家那天，爸爸在站台上背过身去抽烟。", "站台背影", 300, "鼻酸", "negative"),
        ],
        turns=[
            "我爸刚打电话来了，说了不到一分钟",
            "内容是：天冷了，那什么，就这样",
            "挂完电话他给我发了三篇养生文章",
            "保温杯里泡枸杞那种的",
            "他这辈子都这样，我想你了三个字打死不说",
            "还记得我上大学走那天，他在站台上背过身去抽烟",
            "我当时不懂，现在懂了",
            "……行了不说了，我去给他文章点个赞",
        ],
        callback_turns={
            2: ["养生文章"],
            5: ["站台"],
        },
        user_brief_extra="沉默寡言的老爸来了个一分钟电话，你嘴上吐槽心里发酸。",
    ))

    s.append(Scenario(
        scenario_id="ds-022", theme="染发翻车",
        emotional_arc="期待 → 翻车震惊 → 自嘲和解",
        shared_memories=[
            _m("用户想染奶奶灰很久了，一直没敢，说怕被公司说不正经。", "奶奶灰心愿", 25, "跃跃欲试", "positive"),
            _m("用户的头发又黑又硬，理发师说上色难，得漂。", "铁发质", 40, "无奈", "neutral"),
        ],
        turns=[
            "我干了件大事，染头了",
            "本来说好奶奶灰的",
            "出来是……青不青绿不绿，顶着一片苔藓",
            "我发质你知道的，又黑又硬，漂了两遍还是倔",
            "理发师全程道歉，我都不知道该气谁",
            "帽子已下单，明天开始戴帽上班",
            "同事问起来，我就说这是苔藓绿，今年的新流行",
            "等它掉了，我再战奶奶灰，不服",
        ],
        callback_turns={
            1: ["奶奶灰"],
            3: ["又黑又硬"],
        },
        user_brief_extra="你染发翻车顶着一头苔藓绿，震惊又好笑。",
    ))

    s.append(Scenario(
        scenario_id="ds-023", theme="入职五周年",
        emotional_arc="恍惚感慨 → 自我盘点 → 平静向前",
        shared_memories=[
            _m("用户入职第一天迟到，进门撞翻了前台的伞架，全公司记住了他。", "伞架事件", 800, "社死", "mixed"),
            _m("用户的第一位导师王姐教了他很多，两年前跳槽走了，偶尔联系。", "王姐", 300, "感念", "positive"),
        ],
        turns=[
            "今天翻日历才发现，入职满五年了",
            "五年前的今天，我迟到还撞翻了伞架",
            "现在前台那盆伞还歪着，我每次路过都想扶",
            "带我的王姐都走两年多了",
            "她走的时候说，五年后你要是还在抱怨，就换地方",
            "我现在……好像不怎么抱怨了",
            "算是在这儿长出根来了吧",
            "晚上约了同事吃饭，就当给自己过个节",
        ],
        callback_turns={
            1: ["伞架"],
            3: ["王姐"],
        },
        user_brief_extra="你发现自己入职满五年，恍惚感慨中盘点成长。",
    ))

    s.append(Scenario(
        scenario_id="ds-024", theme="又淋雨了",
        emotional_arc="狼狈 → 被旧事逗笑 → 温热收尾",
        shared_memories=[
            _m("用户上次淋雨跑回家，半边袖子全湿，还因此感冒了半个月才好。", "淋雨感冒", 25, "后怕", "negative"),
            _m("用户和同事共撑过一把伞，伞全程歪向用户那边，同事半边肩膀湿透。", "歪掉的伞", 60, "温暖", "positive"),
        ],
        turns=[
            "又淋雨了，今天没带伞",
            "这次学聪明了，在公司等了半小时雨小才走",
            "结果最后一段还是没逃掉，裤脚全湿",
            "上次那回感冒半个月的阴影还在",
            "不过想起同事那次把伞全歪我这边",
            "他自己半边肩膀湿透还说没事",
            "打算明天带两块巧克力给他",
            "淋雨这事儿，好像也没那么讨厌了",
        ],
        callback_turns={
            2: ["感冒"],
            4: ["歪"],
        },
        user_brief_extra="你又被雨淋了，狼狈中想起上次感冒和同事让伞的暖。",
    ))

    s.append(Scenario(
        scenario_id="ds-025", theme="体检报告",
        emotional_arc="忐忑 → 松一口气 → 被戳中软肋",
        shared_memories=[
            _m("用户去年体检两个指标有箭头，医生说复查就行，用户一直惦记。", "两个箭头", 300, "忐忑", "neutral"),
            _m("用户长期晚睡，体检前总发誓早睡，从来没做到。", "早睡失败史", 90, "自嘲", "negative"),
        ],
        turns=[
            "体检报告出了，我盯着邮件十分钟没敢点",
            "点开了，去年的两个箭头，一个转正了",
            "另一个还飘着，医生备注：建议复查",
            "整体没事，就是让少熬夜",
            "早睡这事，我体检前发过誓的",
            "结果誓言活不过当晚十二点",
            "这次真得调整了，箭头虽小，看着硌硬",
            "今晚开始，十一点半前放下手机……尽量",
        ],
        callback_turns={
            2: ["箭头"],
            4: ["早睡"],
        },
        user_brief_extra="你等到了体检报告，忐忑查看后松口气又被熬夜问题戳中。",
    ))

    s.append(Scenario(
        scenario_id="ds-026", theme="停电的晚上",
        emotional_arc="错愕 → 找乐子 → 意外的安宁",
        shared_memories=[
            _m("用户家里有一支应急蜡烛，是前年台风停电时买的，一直没用过。", "应急蜡烛", 300, "闲置", "neutral"),
            _m("用户小时候停电就觉得开心，可以不写作业点蜡烛玩。", "停电的童年", 400, "怀念", "positive"),
        ],
        turns=[
            "停电了，整个小区黑成一片",
            "物业说线路检修，预计两小时",
            "摸黑翻出了那支蜡烛，前年台风买的，终于上岗",
            "火苗一晃一晃的，突然觉得挺好玩",
            "小时候一停电我就开心，作业可以明天再说",
            "现在停电，第一反应是手机还剩多少电",
            "刚才试着什么都不干，就看蜡烛",
            "居然很安静，久违的安静。你那边灯还亮着吧",
        ],
        callback_turns={
            2: ["蜡烛"],
            4: ["停电"],
        },
        user_brief_extra="你家停电了，从错愕到在烛光里找到久违的安宁。",
    ))

    s.append(Scenario(
        scenario_id="ds-027", theme="中午吃什么",
        emotional_arc="世纪难题 → 互相甩锅 → 随缘落定",
        shared_memories=[
            _m("用户公司楼下的肠粉店认得他，每次都多给一勺辣。", "肠粉店的偏爱", 45, "温暖", "positive"),
            _m("用户的饭搭子离职后，用户中午总纠结吃什么。", "饭搭子空窗", 15, "失落", "negative"),
        ],
        turns=[
            "又到了世纪难题时间，中午吃什么",
            "打开外卖软件划了十分钟，越划越饿",
            "要是有个人跟我抢着决定就好了",
            "以前都是饭搭子拍板，我只负责说随便",
            "肠粉店今天人肯定多，这个点",
            "可是那勺多给的辣，值得排队",
            "行，就肠粉了，替我感谢那勺辣",
            "吃完跟你汇报，你呢，今天吃什么",
        ],
        callback_turns={
            3: ["饭搭子"],
            4: ["肠粉店"],
        },
        user_brief_extra="你面临中午吃什么的世纪难题，想念离职的饭搭子。",
    ))

    s.append(Scenario(
        scenario_id="ds-028", theme="表弟的志愿",
        emotional_arc="被求助的慌 → 想当年 → 认真托付",
        shared_memories=[
            _m("用户的表弟今年高考，分数刚过一本线，全家开会吵了三天。", "表弟高考", 8, "热闹", "mixed"),
            _m("用户当年填志愿时滑档去了第五志愿，说过就翻篇了。", "滑档往事", 600, "释然", "mixed"),
        ],
        turns=[
            "我表弟的志愿，全家吵完，锅甩我头上了",
            "让我这个过来人给参谋参谋",
            "他刚过一本线，比我当年还高两分",
            "想当年我滑档那事儿，全家可都记得",
            "第五志愿，拎着行李去了一个没听过的城市",
            "现在倒好，成经验人士了",
            "我打算跟他说真话：城市比学校重要，别怕远",
            "这锅我接了，好歹是翻过篇的人",
        ],
        callback_turns={
            3: ["滑档"],
            5: ["一本线"],
        },
        user_brief_extra="高考出分的表弟全家求你参谋志愿，你想起了自己滑档的往事。",
    ))

    s.append(Scenario(
        scenario_id="ds-029", theme="利息又降了",
        emotional_arc="肉疼 → 算账焦虑 → 被宽慰 → 落定",
        shared_memories=[
            _m("用户在攒房子首付，目标三十万，已经存了小二十万。", "首付进度", 20, "惦记", "positive"),
            _m("用户的存款主要放定期，降息一轮就肉疼一轮。", "降息肉疼", 60, "无奈", "negative"),
        ],
        turns=[
            "存款利率又降了，短信刚发的",
            "我那点定存，一年又少好几顿火锅",
            "首付还差十万出头，越算越焦虑",
            "有时候觉得目标像在往后退",
            "明明在存钱，怎么越存越远呢",
            "……你这么一说我好受点，至少一直在靠近",
            "不折腾了，该存存，该吃吃",
            "今晚先吃顿火锅压压惊，从利息里抠的",
        ],
        callback_turns={
            2: ["首付"],
            3: ["定存"],
        },
        user_brief_extra="存款利率又降，你为首付目标焦虑又自我宽慰。",
    ))

    s.append(Scenario(
        scenario_id="ds-030", theme="生日凌晨",
        emotional_arc="假装不在乎 → 被记起的触动 → 安静的开心",
        shared_memories=[
            _m("用户不太爱过生日，说年纪越大越不想数，去年生日就吃了碗面。", "不过生日的人", 350, "平淡", "neutral"),
            _m("用户其实是早产儿，妈妈总说他的生日也是她的受难日，每年这天用户会给妈妈发红包。", "妈妈的受难日", 350, "柔软", "mixed"),
        ],
        turns=[
            "零点了，又老一岁",
            "别祝我生日快乐，我不过生日的人",
            "去年的今天，我就自己下了碗面，卧俩蛋",
            "不过零点红包已经发出去了，给我妈的",
            "她总说我的生日是她的受难日",
            "所以这个日子，她的功劳比我大",
            "……你怎么记得这么清楚",
            "行吧，被你记着的感觉，还不赖。睡了，晚安",
        ],
        callback_turns={
            1: ["过生日"],
            3: ["受难日"],
            4: ["碗面"],
        },
        user_brief_extra="生日凌晨你假装不在乎年龄，却惦记着给妈妈发红包。",
    ))

    return s


def validate_scenarios(scenarios: list[Scenario]) -> list[str]:
    problems: list[str] = []
    ids: set[str] = set()
    for sc in scenarios:
        if sc.scenario_id in ids:
            problems.append(f"{sc.scenario_id}: 重复")
        ids.add(sc.scenario_id)
        if len(sc.turns) < 6:
            problems.append(f"{sc.scenario_id}: 轮数 {len(sc.turns)} < 6")
        for i in sc.callback_turns:
            if not (0 <= i < len(sc.turns)):
                problems.append(f"{sc.scenario_id}: 回调轮索引越界 {i}")
        # 回调锚点须出现在某条预载记忆里（评委判"自然回访"的依据）
        all_mem_text = " ".join(m["text"] for m in sc.shared_memories)
        for i, anchors in sc.callback_turns.items():
            for a in anchors:
                if a not in all_mem_text:
                    # 也允许锚点指向早期轮次对话（轮内埋点）——检查前几轮用户输入
                    early = " ".join(sc.turns[:i])
                    if a not in early:
                        problems.append(f"{sc.scenario_id}: 回调锚点 {a!r} 无处可依")
    return problems


def save_scenarios(scenarios: list[Scenario], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as fh:
        for sc in scenarios:
            fh.write(json.dumps(sc.to_dict(), ensure_ascii=False))
            fh.write("\n")


def load_scenarios(path: str | Path) -> list[Scenario]:
    out: list[Scenario] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(Scenario.from_dict(json.loads(line)))
    return out
