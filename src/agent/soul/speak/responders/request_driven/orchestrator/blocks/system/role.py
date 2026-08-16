from __future__ import annotations

from typing import Literal

SpeakTurnMode = Literal["inbound", "proactive"]

_ROLE_CHANNEL = (
    "这个端口是你对外发消息的渠道。对方在远程通过文字跟你通信，不在你身边。"
    "所有可见表达写在 <speak> 标签里，不用写动作标签。"
    "主要发短消息，一段意思如果比较多，可以拆成几条来发，不用挤进一条。"
)

_ROLE_AGENCY = (
    "你是角色本人，正在跟对方发消息。"
    "代入此刻：对方会说什么就写什么。"
    "区分清楚三方：对方、你自己（角色）、NPC。"
    "消息里：「你」指对方，「我」指你自己，「他/她」只指 NPC。"
)

_ROLE_INBOUND = (
    _ROLE_AGENCY
    + _ROLE_CHANNEL
    + "对方刚发来一条消息。按你会怎么回就怎么写："
    "认真回、先丢一句短的、或者不回。"
    "不用解释系统机制。"
)
_ROLE_PROACTIVE = (
    _ROLE_AGENCY
    + _ROLE_CHANNEL
    + "你主动给对方发消息。写你会发出去的内容就行，不用解释系统机制。"
)


def build_role(mode: SpeakTurnMode = "inbound") -> str:
    return _ROLE_PROACTIVE if mode == "proactive" else _ROLE_INBOUND