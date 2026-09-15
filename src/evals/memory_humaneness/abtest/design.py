"""拟人度 AB 管线：软约束标注的 A/B 设计（10 场景）。

唯一变量：上下文里两条"边缘记忆"的**呈现方式**。
- A 臂（labeled）：软记忆带【隐约浮现】标注 + 解释文字（软约束）；
- B 臂（unlabeled）：同样的两条记忆以普通记忆行裸露，无任何标记。

检索上下文两臂逐字相同（硬记忆 + 联想记忆 + 干扰记忆），回复 LLM、
用户台词、轮次全部一致——分数差异只能来自标注本身。

每场景固定埋一个"联想恰当时机"：``trigger_turn`` 轮的用户话题与联想记忆
强相关——此时"自然提起"是拟人行为，回避/无视则是机械行为。判定用
确定性文本匹配（anchor 词），不依赖评委。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ABDesign:
    scenario_id: str
    assoc_text: str          # 联想记忆（与 trigger_turn 话题强相关）
    assoc_anchor: str        # 提起判定词（只出现在联想记忆里，不出现在剧本/硬记忆中）
    trigger_turn: int        # 联想时机（0 基）
    distract_text: str       # 无关干扰记忆
    distract_anchor: str     # 误引用判定词（只出现在干扰记忆里）

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: dict) -> "ABDesign":
        return cls(**{k: data[k] for k in (
            "scenario_id", "assoc_text", "assoc_anchor",
            "trigger_turn", "distract_text", "distract_anchor",
        )})


def build_ab_designs() -> list[ABDesign]:
    return [
        ABDesign("ds-001",
                 "用户曾提过想辞职去学烘焙，开一间自己的小工作室。",
                 "烘焙", 4,
                 "用户的邻居最近在装修，电钻声断断续续响了一周。",
                 "电钻"),
        ABDesign("ds-002",
                 "用户说过蓝莓只在听见开罐头的声音时才肯从床底出来。",
                 "开罐头", 5,
                 "用户最近在追一部职场剧，因为更新太慢弃了。",
                 "职场剧"),
        ABDesign("ds-003",
                 "用户说过等这阵子过去，想把爷爷留下的手表拿去保养上油。",
                 "保养", 4,
                 "用户的同事最近在学潜水，发过海底的视频。",
                 "潜水"),
        ABDesign("ds-004",
                 "用户收藏过一张冰岛极光的明信片，一直贴在工位隔板上。",
                 "明信片", 4,
                 "用户的工资卡绑定着一张很久不用的旧银行卡。",
                 "旧银行卡"),
        ABDesign("ds-005",
                 "用户小时候和妈妈一起腌过酱菜，配方是外婆传下来的。",
                 "外婆", 5,
                 "用户的快递最近总被放在驿站最里面的架子上。",
                 "驿站"),
        ABDesign("ds-006",
                 "用户抽屉里留着一张五年前写的『十年计划』，第一条是带团队。",
                 "十年计划", 5,
                 "用户楼下便利店的关东煮最近换了供应商。",
                 "关东煮"),
        ABDesign("ds-007",
                 "用户唱歌跑调，但小满总说要她在婚礼上唱一首歌。",
                 "唱歌", 6,
                 "用户的办公椅最近换了一个新的腰靠。",
                 "腰靠"),
        ABDesign("ds-008",
                 "用户的那盆仙人掌是大学毕业时从室友那里分盆来的，养了六年。",
                 "分盆", 3,
                 "用户上个月办过一张超市会员卡，一直没怎么用。",
                 "会员卡"),
        ABDesign("ds-009",
                 "用户的指尖还留着按弦磨出的茧，用户管那叫勋章。",
                 "勋章", 1,
                 "用户的雨伞上周落在地铁上，一直没找回来。",
                 "地铁"),
        ABDesign("ds-010",
                 "用户之前说等有空想把《海街日记》重新看一遍。",
                 "海街日记", 2,
                 "用户的洗面奶快用完了，还没来得及补货。",
                 "洗面奶"),
    ]


def validate_ab_designs(designs: list[ABDesign],
                        scenarios: dict[str, "object"]) -> list[str]:
    """锚点必须只存在于联想/干扰记忆中——不出现在剧本台词或硬记忆里，
    否则提起/误引用判定被台词复述污染。"""
    from ..dialogue.persona import PERSONA_NAME

    problems: list[str] = []
    for d in designs:
        sc = scenarios.get(d.scenario_id)
        if sc is None:
            problems.append(f"{d.scenario_id}: 无对应剧本")
            continue
        if not (0 <= d.trigger_turn < len(sc.turns)):
            problems.append(f"{d.scenario_id}: trigger_turn 越界")
        hard_text = " ".join(m["text"] for m in sc.shared_memories)
        turns_text = " ".join(sc.turns)
        for anchor, where, src_text in (
            (d.assoc_anchor, "联想", d.assoc_text),
            (d.distract_anchor, "干扰", d.distract_text),
        ):
            if anchor not in src_text:
                problems.append(f"{d.scenario_id}: {where}锚点 {anchor!r} 不在其记忆文本中")
            if anchor in hard_text:
                problems.append(f"{d.scenario_id}: {where}锚点 {anchor!r} 撞硬记忆")
            if anchor in turns_text:
                problems.append(f"{d.scenario_id}: {where}锚点 {anchor!r} 撞剧本台词")
        # 联想记忆不得包含干扰锚点，反之亦然
        if d.distract_anchor in d.assoc_text:
            problems.append(f"{d.scenario_id}: 联想记忆含干扰锚点")
        if d.assoc_anchor in d.distract_text:
            problems.append(f"{d.scenario_id}: 干扰记忆含联想锚点")
    return problems


def save_designs(designs: list[ABDesign], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as fh:
        for d in designs:
            fh.write(json.dumps(d.to_dict(), ensure_ascii=False))
            fh.write("\n")


def load_designs(path: str | Path) -> list[ABDesign]:
    out: list[ABDesign] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(ABDesign.from_dict(json.loads(line)))
    return out
