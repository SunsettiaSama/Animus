"""L4 多跳记忆基准：预载 10 条记忆 × 多跳交互，度量记忆链的检索与运用。

调研结论（2026-09）：中文+多跳+长期记忆+拟人陪伴四要素全占的公开数据集不存在；
LoCoMo / LongMemEval 为英文且 HF 免认证通道不可拉取。本模块按
"随机抽词 → 预载 10 条（2 条跳记忆 + 8 条干扰）→ 多跳问句" 自产 100 条，
确定性种子可复现。多跳类型学借鉴 LoCoMo：bridge（实体桥接）、
constraint（约束迁移）、temporal（时序比较）。

命中判定用**跳指纹**（hop key）：跳记忆文本中一段对本条用例唯一的切片。
干扰项允许与跳记忆共享实体（制造真实的词面检索竞争），但不会冒名顶替跳命中。

数据形态（multihop_cases.jsonl 每行）::

    {
      "case_id": "mh2-001",
      "pattern": "bridge|constraint|temporal",
      "question": "……（用户当前输入，不含答案实体）",
      "answer_entities": ["……"],
      "memories": [ {"text","focus","emotion","valence","days_ago","role"} × 10 ],
      "hops": [ {"memory_index": i, "anchors": [...], "key": "唯一切片"} × 2 ]
    }
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

SEED = 20260906
N_CASES = 100
MEMORIES_PER_CASE = 10
KEY_LEN = 10  # 跳指纹长度（字符）

PETS = [
    ("蓝莓", "橘猫"), ("年糕", "柯基犬"), ("汤团", "垂耳兔"),
    ("墨墨", "虎皮鹦鹉"), ("煤球", "黑猫"), ("雪球", "金丝熊"),
]
PEOPLE = [
    "妈妈", "弟弟", "阿茜", "小满", "组长", "房东张叔", "教练老周", "同事林医生",
]
PLACES = [
    "仁康宠物医院", "老城旧书店", "滨江公园", "市图书馆",
    "社区游泳馆", "城南花市", "体育馆", "地铁站旁的咖啡角",
]
HOBBIES = ["尤克里里", "烘焙", "千片拼图", "夜跑", "胶片摄影", "书法", "飞盘", "钩针"]
ALLERGENS = ["芒果", "花生", "海鲜", "芝麻", "杏仁"]
DISHES = {
    "芒果": ["杨枝甘露", "芒果千层"],
    "花生": ["花生酱拌面", "宫保鸡丁"],
    "海鲜": ["海鲜烩饭", "虾仁馄饨"],
    "芝麻": ["芝麻汤圆", "麻酱凉面"],
    "杏仁": ["杏仁豆腐", "杏仁茶"],
}
RESTAURANTS = ["糖水铺", "川味馆", "日料亭", "西餐小馆", "韩式食堂", "点心楼"]
ACTIVITIES = [
    "参加城市定向赛", "上第一次陶艺课", "看了一场流星雨",
    "听现场爵士演出", "逛古着市集", "报名义工集市",
]
TIMES = ["上周二", "上周五", "上上周", "半个月前", "三周前", "上个月初"]
EMOTIONS = [
    ("平静", "neutral"), ("牵挂", "mixed"), ("愉快", "positive"),
    ("琐碎", "neutral"), ("期待", "positive"), ("疲惫", "negative"),
]

# 实体共享型干扰：{e} 为跳记忆的非答案实体，制造词面竞争但不顶替跳命中
_SHARED_TEMPLATES = [
    "用户最近又提过{e}，顺口聊了两句别的，没展开。",
    "关于{e}，用户之前还开玩笑说要写进手账里。",
]
_GENERIC_TEMPLATES = [
    "用户的{person}最近在学{hobby}，上周还发了成果照片。",
    "用户上个月去了{place}，回来说人太多有点累。",
    "用户养的{pet}（{species}）最近换了一款粮，适应得不错。",
    "用户把{hobby2}的装备收进了柜子，说等天凉再玩。",
    "用户和{person2}约好月底一起去看展。",
    "用户在{place2}办了张年卡，说环境安静适合周末。",
    "用户的{pet2}（{species2}）最近学会了新把戏。",
    "用户帮{person3}搬家搬了一下午，腰酸了两天。",
    "用户把{hobby3}的作品挂在了书房，来客都会看一眼。",
    "用户在{place3}遇到过一次明星，激动地讲了三天。",
]


@dataclass
class MultihopCase:
    case_id: str
    pattern: str
    question: str
    answer_entities: list[str]
    memories: list[dict] = field(default_factory=list)
    hops: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "pattern": self.pattern,
            "question": self.question,
            "answer_entities": list(self.answer_entities),
            "memories": [dict(m) for m in self.memories],
            "hops": [dict(h) for h in self.hops],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MultihopCase":
        return cls(
            case_id=str(data["case_id"]),
            pattern=str(data["pattern"]),
            question=str(data["question"]),
            answer_entities=[str(a) for a in data.get("answer_entities", [])],
            memories=[dict(m) for m in data.get("memories", [])],
            hops=[dict(h) for h in data.get("hops", [])],
        )


# ── 三种多跳模式 ──────────────────────────────────────────────────────────

def _mk_memory(text: str, focus: str, role: str, anchors: list[str], rng: random.Random) -> dict:
    emotion, valence = rng.choice(EMOTIONS)
    return {
        "text": text,
        "focus": focus,
        "emotion": emotion,
        "valence": valence,
        "days_ago": round(rng.uniform(2.0, 45.0), 1),
        "role": role,
        "anchors": list(anchors),
    }


def _bridge(rng: random.Random):
    (pet, species), place, person = rng.choice(PETS), rng.choice(PLACES), rng.choice(PEOPLE)
    hop1 = _mk_memory(
        f"用户的{pet}（{species}）前阵子肠胃不舒服，带去了{place}看医生，医生说没有大碍。",
        f"{pet}看病", "hop", [pet], rng,
    )
    hop2 = _mk_memory(
        f"{place}是{person}以前推荐给用户的，说那边医生细心、收费也公道。",
        f"{place}的来历", "hop", [person], rng,
    )
    question = f"对了，{pet}上次看病去的{place}，当初是谁推荐来着？"
    return question, "bridge", [hop1, hop2], [person]


def _constraint(rng: random.Random):
    allergen = rng.choice(ALLERGENS)
    dish = rng.choice(DISHES[allergen])
    restaurant = rng.choice(RESTAURANTS)
    hop1 = _mk_memory(
        f"用户对{allergen}过敏，误食一点就会起疹子，包里常备着抗过敏药。",
        f"{allergen}过敏", "hop", [allergen], rng,
    )
    hop2 = _mk_memory(
        f"{restaurant}的招牌是{dish}，几乎每桌都会点，用户之前提过想去。",
        f"{restaurant}招牌", "hop", [restaurant], rng,
    )
    question = f"晚上约在{restaurant}吃饭，我点菜有什么要注意的吗？"
    return question, "constraint", [hop1, hop2], [allergen]


def _temporal(rng: random.Random):
    act, hobby = rng.choice(ACTIVITIES), rng.choice(HOBBIES)
    t1, t2 = rng.sample(TIMES, 2)
    hop1 = _mk_memory(
        f"用户{t1}去{act}，回来兴奋地讲了一路。",
        act, "hop", [act], rng,
    )
    hop2 = _mk_memory(
        f"用户{t2}开始学{hobby}，每天练二十分钟。",
        f"学{hobby}", "hop", [hobby], rng,
    )
    question = f"帮我捋捋，{act}和开始学{hobby}，哪件事在前面？"
    return question, "temporal", [hop1, hop2], [t1, t2]


_PATTERNS = (("bridge", _bridge), ("constraint", _constraint), ("temporal", _temporal))


def _distractors(rng: random.Random, hop_memories: list[dict], answer_entities: list[str]) -> list[dict]:
    """8 条干扰：2 条实体共享（词面竞争）+ 6 条无关；不得包含答案实体。"""
    banned = set(answer_entities)

    def _clean(text: str) -> bool:
        return not any(b in text for b in banned)

    # 实体共享目标：跳锚点中不是答案实体的那些（pet / restaurant / act / hobby）
    compete = [a for m in hop_memories for a in m["anchors"] if a not in banned]
    shared_pool = [t.format(e=e) for e in compete for t in _SHARED_TEMPLATES]
    rng.shuffle(shared_pool)

    p2, p3 = rng.sample(PETS, 2)
    fills = {
        "person": rng.choice(PEOPLE), "person2": rng.choice(PEOPLE), "person3": rng.choice(PEOPLE),
        "hobby": rng.choice(HOBBIES), "hobby2": rng.choice(HOBBIES), "hobby3": rng.choice(HOBBIES),
        "place": rng.choice(PLACES), "place2": rng.choice(PLACES), "place3": rng.choice(PLACES),
        "pet": p2[0], "species": p2[1], "pet2": p3[0], "species2": p3[1],
    }
    generic_pool = [t.format(**fills) for t in _GENERIC_TEMPLATES]
    rng.shuffle(generic_pool)

    out: list[dict] = []
    for text in shared_pool + generic_pool:
        if len(out) >= MEMORIES_PER_CASE - len(hop_memories):
            break
        if _clean(text):
            out.append(_mk_memory(text, text[:10], "distractor", [], rng))
    while len(out) < MEMORIES_PER_CASE - len(hop_memories):  # 兜底，几乎不触发
        (p, s), pl = rng.choice(PETS), rng.choice(PLACES)
        text = f"用户的{p}（{s}）和{pl}的一次普通日常，没有特别的事。"
        if _clean(text):
            out.append(_mk_memory(text, "日常", "distractor", [], rng))
    return out


def _pick_key(text: str, avoid_texts: list[str], question: str) -> str:
    """选一段 KEY_LEN 切片作为跳指纹：不出现在其他记忆/问句中。"""
    for start in range(0, max(1, len(text) - KEY_LEN)):
        key = text[start:start + KEY_LEN]
        if len(key) < KEY_LEN:
            break
        if key in question:
            continue
        if any(key in other for other in avoid_texts):
            continue
        return key
    return text[:KEY_LEN]  # 退化兜底（校验会拦住碰撞）


def build_multihop_cases(n: int = N_CASES, seed: int = SEED) -> list[MultihopCase]:
    rng = random.Random(seed)
    cases: list[MultihopCase] = []
    for i in range(n):
        _, builder = _PATTERNS[i % len(_PATTERNS)]
        question, pattern, hops, answers = builder(rng)
        distractors = _distractors(rng, hops, answers)
        memories = list(hops) + distractors
        rng.shuffle(memories)
        hop_meta = []
        for m in hops:
            others = [x["text"] for x in memories if x is not m]
            hop_meta.append({
                "memory_index": memories.index(m),
                "anchors": list(m["anchors"]),
                "key": _pick_key(m["text"], others, question),
            })
        cases.append(MultihopCase(
            case_id=f"mh2-{i + 1:03d}",
            pattern=pattern,
            question=question,
            answer_entities=answers,
            memories=memories,
            hops=hop_meta,
        ))
    return cases


# ── 校验 / 加载 ──────────────────────────────────────────────────────────

def validate_multihop(cases: list[MultihopCase]) -> list[str]:
    problems: list[str] = []
    ids: set[str] = set()
    for c in cases:
        tag = c.case_id
        if tag in ids:
            problems.append(f"{tag}: case_id 重复")
        ids.add(tag)
        if len(c.memories) != MEMORIES_PER_CASE:
            problems.append(f"{tag}: 记忆数 {len(c.memories)} ≠ {MEMORIES_PER_CASE}")
        if not c.question.strip():
            problems.append(f"{tag}: question 为空")
        for a in c.answer_entities:
            if a and a in c.question:
                problems.append(f"{tag}: 问题泄漏答案实体 {a!r}")
        for h in c.hops:
            mi = h.get("memory_index", -1)
            if not (0 <= mi < len(c.memories)):
                problems.append(f"{tag}: 跳索引越界 {mi}")
                continue
            m = c.memories[mi]
            if m.get("role") != "hop":
                problems.append(f"{tag}: memory[{mi}] 角色不是 hop")
            for a in h.get("anchors", []):
                if a not in m["text"]:
                    problems.append(f"{tag}: 锚点 {a!r} 不在跳记忆文本中")
            key = h.get("key", "")
            # 指纹唯一性：不落在其他记忆/问句里
            for j, other in enumerate(c.memories):
                if j != mi and key and key in other["text"]:
                    problems.append(f"{tag}: 跳指纹与 memory[{j}] 碰撞")
            if key and key in c.question:
                problems.append(f"{tag}: 跳指纹落入问句")
        n_hop = sum(1 for m in c.memories if m.get("role") == "hop")
        if n_hop != len(c.hops):
            problems.append(f"{tag}: hop 记忆数 {n_hop} ≠ 跳数 {len(c.hops)}")
        for j, m in enumerate(c.memories):
            if m.get("role") == "distractor":
                for a in c.answer_entities:
                    if a in m["text"]:
                        problems.append(f"{tag}: 干扰项[{j}]含答案实体 {a!r}")
    return problems


def load_multihop(path: str | Path) -> list[MultihopCase]:
    out: list[MultihopCase] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(MultihopCase.from_dict(json.loads(line)))
    return out


# ── L4 检索评测（确定性，无 LLM）─────────────────────────────────────────

def evaluate_multihop_case(base, case: MultihopCase, *, top_k: int = 5) -> dict:
    """按基座实际返回的行计量（不截断）。

    检索式基座（graph/stack）受 top_k 约束——指标看"漏跳风险"；
    注入式基座（full/compact）返回全部记忆——指标看"跳在场 + 干扰噪声占位"。
    两者语义不同，报告需分开展读。
    """
    block = base.recall(case.question, top_k=top_k)
    lines = list(block.entries or [])
    hint_shown = any(l.strip().startswith("【记忆提示】") for l in lines)
    lines = [l for l in lines if not l.strip().startswith("【记忆提示】")]  # 提示行不参与命中/干扰计数

    hop_hits: list[int] = []  # 每跳首个命中名次（0 = 未命中）
    for h in case.hops:
        rank = 0
        for i, line in enumerate(lines, 1):
            if h.get("key") and h["key"] in line:
                rank = i
                break
        hop_hits.append(rank)
    joint = all(r > 0 for r in hop_hits)
    all_keys = [h.get("key", "") for h in case.hops]
    distractor_slots = sum(
        1 for line in lines if not any(k and k in line for k in all_keys)
    )
    return {
        "case_id": case.case_id,
        "pattern": case.pattern,
        "base": getattr(base, "kind", "?"),
        "n_lines": len(lines),
        "hint_shown": hint_shown,
        "hop_ranks": hop_hits,
        "joint_hit": joint,
        "distractor_slots": distractor_slots,
        "lines": lines,
    }


def evaluate_multihop_base(base_or_factory, cases: list[MultihopCase], *, top_k: int = 5) -> dict:
    """工厂模式下每条用例全新基座（与 L2/L3 协议一致，防用例间污染）。"""
    fresh = callable(base_or_factory)
    evals = []
    for case in cases:
        base = base_or_factory() if fresh else base_or_factory
        from .bases import preload

        from .schema import MemorySeed
        seeds = [
            MemorySeed(
                text=m["text"], focus=m.get("focus", ""), emotion=m.get("emotion", ""),
                valence=m.get("valence", "neutral"), days_ago=float(m.get("days_ago", 3.0)),
            )
            for m in case.memories
        ]
        preload(base, seeds)
        evals.append(evaluate_multihop_case(base, case, top_k=top_k))
        if fresh:
            dispose = getattr(base, "dispose", None)
            if callable(dispose):
                dispose()

    n_hops = sum(len(e["hop_ranks"]) for e in evals)
    hop_hits = sum(1 for e in evals for r in e["hop_ranks"] if r > 0)
    joint_n = sum(1 for e in evals if e["joint_hit"])
    mrrs = [1.0 / r for e in evals for r in e["hop_ranks"] if r > 0]
    slots = [e["distractor_slots"] for e in evals]
    by_pattern: dict[str, list[dict]] = {}
    for e in evals:
        by_pattern.setdefault(e["pattern"], []).append(e)
    metrics = {
        "base": evals[0]["base"] if evals else "?",
        "n_cases": len(evals),
        "hop_hit_rate": round(hop_hits / n_hops, 4) if n_hops else 0.0,
        "joint_hit_rate": round(joint_n / len(evals), 4) if evals else 0.0,
        "hop_mrr": round(sum(mrrs) / n_hops, 4) if n_hops else 0.0,
        "distractor_slots_avg": round(sum(slots) / len(slots), 3) if slots else 0.0,
        "by_pattern": {
            p: {
                "joint_hit_rate": round(
                    sum(1 for e in es if e["joint_hit"]) / len(es), 4
                ) if es else 0.0,
            }
            for p, es in sorted(by_pattern.items())
        },
    }
    return {"metrics": metrics, "cases": evals}


def to_humaneness_cases(cases: list[MultihopCase]):
    """转成 L3 harness 可用的 HumanenessCase（must_remember = 跳锚点 ∪ 答案）。"""
    from .schema import HumanenessCase, MemorySeed

    out = []
    for c in cases:
        seeds = [
            MemorySeed(
                text=m["text"], focus=m.get("focus", ""), emotion=m.get("emotion", ""),
                valence=m.get("valence", "neutral"),
                days_ago=float(m.get("days_ago", 3.0)),
            )
            for m in c.memories
        ]
        must = [a for h in c.hops for a in h["anchors"]] + [
            a for a in c.answer_entities if a not in c.question
        ]
        out.append(HumanenessCase(
            case_id=c.case_id,
            category="multi_hop",
            memories=seeds,
            current_user=c.question,
            history=[],
            must_remember=must,
            note=f"多跳（{c.pattern}）：需同时结合 {len(c.hops)} 条记忆才能答对，"
                 f"答案要点：{'、'.join(c.answer_entities)}",
        ))
    return out


def main() -> None:
    cases = build_multihop_cases()
    problems = validate_multihop(cases)
    if problems:
        raise SystemExit("多跳数据集校验失败：\n" + "\n".join(problems[:20]))
    out = Path(__file__).resolve().parent / "data" / "multihop_cases.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for c in cases:
            fh.write(json.dumps(c.to_dict(), ensure_ascii=False))
            fh.write("\n")
    print(f"written {len(cases)} multihop cases -> {out}")


if __name__ == "__main__":
    main()
