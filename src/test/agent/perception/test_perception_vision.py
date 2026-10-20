from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.perception.protocol import GameEventKind, GamePerceptionEvent
from agent.perception.vision import VisionNarrator, _parse_fields


class _FakeVisionLLM:
    """记录消息并返回预设 JSON 的假多模态模型。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list] = []

    def generate_messages(self, messages):
        self.calls.append(messages)
        return self.reply

    def stream_generate_messages(self, messages):
        yield self.reply


def _event(image_b64: str = "") -> GamePerceptionEvent:
    return GamePerceptionEvent(
        kind=GameEventKind.boss_defeated,
        ts="2026-09-21T00:00:00+00:00",
        detail={"boss_name": "矿洞魔像"},
        image_b64=image_b64,
    )


def test_vision_narrator_uses_model_json_reply():
    llm = _FakeVisionLLM(
        '{"narrative": "魔像的余烬还在发光，洞里安静下来了。", "emotion_label": "震动",'
        ' "salience": 0.9, "valence_delta": 0.5, "arousal_delta": 0.4}'
    )
    narrator = VisionNarrator(llm, model_name="glm-4v-test")
    packet = narrator.translate(_event())
    assert packet.narrative == "魔像的余烬还在发光，洞里安静下来了。"
    assert packet.salience == 0.9
    assert packet.translator == "vision:glm-4v-test"
    assert packet.emotion_label == "震动"


def test_vision_narrator_sends_image_when_present():
    llm = _FakeVisionLLM('{"narrative": "画面里魔像正倒下。"}')
    narrator = VisionNarrator(llm)
    narrator.translate(_event(image_b64="aGVsbG8="))
    messages = llm.calls[-1]
    human = messages[-1]
    content = human.content
    assert isinstance(content, list)
    kinds = [part.get("type") for part in content]
    assert "image_url" in kinds
    image_part = next(p for p in content if p.get("type") == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_vision_narrator_without_image_is_text_only():
    llm = _FakeVisionLLM('{"narrative": "没有画面也能翻译。"}')
    narrator = VisionNarrator(llm)
    narrator.translate(_event())
    content = llm.calls[-1][-1].content
    assert all(part.get("type") == "text" for part in content)


def test_vision_narrator_falls_back_to_rule_on_failure():
    class _Broken:
        def generate_messages(self, messages):
            raise RuntimeError("vision api down")

        def stream_generate_messages(self, messages):
            yield from []

    narrator = VisionNarrator(_Broken())
    packet = narrator.translate(_event())
    assert "矿洞魔像" in packet.narrative  # 规则叙事兜底
    assert "fallback:rule" in packet.translator


def test_vision_narrator_falls_back_on_bad_json():
    llm = _FakeVisionLLM("模型自由发挥了一段没有 JSON 的话")
    narrator = VisionNarrator(llm)
    packet = narrator.translate(_event())
    # 非 JSON 回复整体视作 narrative（不丢弃），标签不影响
    assert packet.narrative == "模型自由发挥了一段没有 JSON 的话"


def test_parse_fields_handles_code_fences():
    fields = _parse_fields('```json\n{"narrative": " fenced ", "salience": 0.5}\n```')
    assert fields["narrative"] == " fenced "
    assert fields["salience"] == 0.5


def test_vision_config_yaml_roundtrip(tmp_path):
    from config.llm_core.vision_config import VisionLLMConfig

    missing = VisionLLMConfig.from_yaml(tmp_path / "none.yaml")
    assert missing.enabled is False and missing.ready is False

    yaml_path = tmp_path / "vision.yaml"
    cfg = VisionLLMConfig(
        enabled=True,
        model="glm-4.5v",
        api_key="sk-x",
        base_url="https://open.bigmodel.cn/api/paas/v4",
    )
    cfg.save_yaml(yaml_path)
    loaded = VisionLLMConfig.from_yaml(yaml_path)
    assert loaded.ready is True
    assert loaded.model == "glm-4.5v"
