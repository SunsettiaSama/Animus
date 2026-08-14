from __future__ import annotations

import re

_SPEAK_RE = re.compile(r"\[speak\](.*?)\[/speak\]", re.I | re.S)
_ANY_TAG_RE = re.compile(r"\[/?\s*(?:think|speak|action|state|recall)\b[^\]]*\]", re.I)
_PAREN_ACTION_RE = re.compile(r"（[^）]{1,16}）|\([^)]{1,16}\)")

# 无标签裸动作 / 舞台说明（行级）
_BARE_ACTION_HEAD = re.compile(
    r"^(把|将|轻轻|微微|慢慢|伸手|抬手|抬起|放下|推近|推过|递过|"
    r"点点头|点了点头|笑了笑|侧过|望向|看向|瞥了|凑近|靠过去)"
)
_BARE_ACTION_BODY = re.compile(
    r"(把.+?(推|递|挪|放)|轻轻往|往他那边|往她那边|侧过头|望着对方)"
)


def _is_bare_action_line(line: str) -> bool:
    """无 [action] 包裹、也不像对白的舞台句。"""
    s = line.strip()
    if not s:
        return True
    if "「" in s or "」" in s or '"' in s:
        return False
    # 极短应声当对白
    if len(s) <= 4 and any(ch in s for ch in ("嗯", "哦", "啊", "好", "行", "在")):
        return False
    if _BARE_ACTION_HEAD.match(s):
        return True
    if _BARE_ACTION_BODY.search(s) and not any(
        mark in s for mark in ("？", "?", "吗", "呢", "吧", "呀")
    ):
        # 「路上堵着是挺累的」含「是」类对白；纯动作句常无问语气
        if "。" in s or "，" in s:
            # 有逗号/句号但仍像说明：无第一人称开口
            if not s.startswith(("我", "嗯", "哦", "啊", "好", "行", "对", "那", "你")):
                if _BARE_ACTION_BODY.search(s):
                    return True
    return False


def _drop_bare_action_lines(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        if _is_bare_action_line(line):
            continue
        kept.append(line.strip())
    return "\n".join(p for p in kept if p)


def visible_reply(raw: str) -> str:
    """
    角色扮演输出清洗：
    - 有 [speak] 时只保留对白（[action]/think 不进用户可见通道）
    - 无标签时丢掉裸动作行与括号旁白
    """
    body = raw.strip()
    if not body:
        return ""

    speaks = [m.group(1).strip() for m in _SPEAK_RE.finditer(body) if m.group(1).strip()]
    if speaks:
        text = "\n".join(speaks)
    else:
        text = _ANY_TAG_RE.sub("", body).strip()

    text = _PAREN_ACTION_RE.sub("", text)
    text = _drop_bare_action_lines(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
