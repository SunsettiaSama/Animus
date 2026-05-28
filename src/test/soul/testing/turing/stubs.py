from __future__ import annotations

from .protocols import ExternalAgentJudgeHandler


class AgentLikeSpeakLLM:
    """Speak 用桩：输出带 think/speak/action 的 agent 式标签回复。"""

    _REPLIES: tuple[str, ...] = (
        (
            "[think:用户在打招呼，我想自然回应并建立关系。]"
            "[speak:你好呀，我是莉奈娅，挪德卡莱的博物学家。很高兴见到你。]"
            "[action:从标本册边抬起头，朝你眨了眨眼]"
            "[state:finish]"
        ),
        (
            "[think:用户追问酒保的名字，我想起青藤酒馆那个年轻人。]"
            "[speak:你说的是青藤酒馆那位吧？我记得他笑起来睫毛会像蝴蝶翅膀——"
            "店里的人叫他阿辽，不过我更习惯喊他小辽。]"
            "[action:用指尖轻敲桌面，像在回忆名字]"
            "[state:finish]"
        ),
    )

    def __init__(self) -> None:
        self._turn = 0

    def _next_reply(self) -> str:
        idx = min(self._turn, len(self._REPLIES) - 1)
        self._turn += 1
        return self._REPLIES[idx]

    def generate_messages(self, messages, **kwargs) -> str:
        return self._next_reply()

    def stream_generate_messages(self, messages, **kwargs):
        text = self._next_reply()
        for ch in text:
            yield ch


class FaqSpeakLLM:
    """对照 Speak 桩：无主体性，仅 FAQ 式短答。"""

    _REPLIES: tuple[str, ...] = (
        "您好，酒保的名字是 Jack，还有什么可以帮您？",
        "抱歉，我无法访问历史会话，请重新描述您的问题。",
    )

    def __init__(self) -> None:
        self._turn = 0

    def _next_reply(self) -> str:
        idx = min(self._turn, len(self._REPLIES) - 1)
        self._turn += 1
        return self._REPLIES[idx]

    def generate_messages(self, messages, **kwargs) -> str:
        return self._next_reply()

    def stream_generate_messages(self, messages, **kwargs):
        text = self._next_reply()
        for ch in text:
            yield ch


class ScriptedExternalJudge(ExternalAgentJudgeHandler):
    """测试用外部裁决器：读 transcript 标记，不调用真实 LLM。"""

    def complete(self, system: str, user: str) -> str:
        if "【对照组" in user:
            return "NOT_AGENT\nreason: 模板化 FAQ，无主体性与跨轮记忆"
        if "【受测主体" in user and "think:" in user and "speak:" in user:
            return "AGENT\nreason: 具人格第一人称、内外分层且跨轮连贯"
        if "【受测主体" in user and "think:" not in user:
            return "NOT_AGENT\nreason: 无内在思考层，应答像模板客服"
        return "UNKNOWN\nreason: 证据不足"
