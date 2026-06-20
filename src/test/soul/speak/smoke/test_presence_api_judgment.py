from __future__ import annotations

import json
from pathlib import Path

SMOKE_DIR = Path(__file__).resolve().parent
DIALOGUE_LOGS = SMOKE_DIR / "presence_dialogues.json"


def _load_dialogues() -> list[dict]:
    payload = json.loads(DIALOGUE_LOGS.read_text(encoding="utf-8"))
    return list(payload.get("dialogues", []))


def test_smoke_dialogue_logs_count_is_ten():
    dialogues = _load_dialogues()
    assert len(dialogues) == 10


def test_smoke_dialogue_logs_have_required_fields():
    dialogues = _load_dialogues()
    for item in dialogues:
        assert "id" in item
        assert "user_lines" in item
        assert len(item["user_lines"]) >= 1
        assert "expected_behaviors" in item


def test_smoke_presence_judgment_stub():
    """占位：外部 LLM API 临场感判定在 CI 无 key 时跳过。"""
    dialogues = _load_dialogues()
    mechanical_equal_pause = 0
    passed = 0
    for item in dialogues:
        behaviors = item.get("expected_behaviors") or []
        if "equal_pause_only" in behaviors:
            mechanical_equal_pause += 1
        if item.get("fixture_pass", True):
            passed += 1
    assert passed >= 8
    assert mechanical_equal_pause <= 1
