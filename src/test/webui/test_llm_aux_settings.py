"""次语言模型（aux）设置门面协议测试：AuxLLMRegistry roundtrip + /api/llm/aux 端点。"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_WEBUI_DIR = Path(__file__).resolve().parents[2] / "webui"
if str(_WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(_WEBUI_DIR))

from config.llm_core.aux_config import (  # noqa: E402
    AUX_SLOTS,
    AuxLLMConfig,
    AuxLLMRegistry,
)
import routers.llm as llm_router  # noqa: E402


class _FakeLLMService:
    def __init__(self) -> None:
        self.registered: dict = {}
        self.unregistered: list[str] = []

    def register_aux(self, name, cfg):
        self.registered[name] = cfg

    def unregister_aux(self, name):
        self.unregistered.append(name)

    def aux_status(self):
        return {k: {"model": v.model} for k, v in self.registered.items()}


class _FakeState:
    def __init__(self, llm_service) -> None:
        self.llm_service = llm_service


def _patch_aux_yaml(monkeypatch, tmp_path: Path) -> Path:
    target = tmp_path / "aux_models.yaml"
    from config import paths

    monkeypatch.setattr(
        type(paths), "aux_models_yaml", property(lambda self: target)
    )
    return target


# ── AuxLLMConfig / AuxLLMRegistry ────────────────────────────────────────────

def test_aux_registry_roundtrip_and_unknown_slot_filtering(tmp_path):
    target = tmp_path / "aux_models.yaml"
    registry = AuxLLMRegistry.from_dict({
        "models": {
            "life": {"enabled": True, "model": "small-a", "base_url": "http://x/v1"},
            "persona": {"enabled": False, "model": ""},
            "not_a_slot": {"enabled": True, "model": "ghost"},
        }
    })
    assert "not_a_slot" not in registry.models
    assert registry.slot("life").model == "small-a"
    # 未列出的槽位返回 disabled 默认值（= 回退主模型）
    assert registry.slot("memory").enabled is False

    registry.save_yaml(str(target))
    reloaded = AuxLLMRegistry.from_yaml(str(target))
    assert reloaded.slot("life").model == "small-a"
    assert reloaded.slot("life").enabled is True
    # to_dict 归一化为全部已知槽位
    assert set(reloaded.to_dict()["models"].keys()) == set(AUX_SLOTS)


def test_aux_registry_missing_file_returns_all_disabled(tmp_path):
    registry = AuxLLMRegistry.from_yaml(str(tmp_path / "nope.yaml"))
    assert all(not cfg.enabled for cfg in registry.models.values())
    assert registry.slot("speak").model == ""


def test_aux_validate_rules():
    assert AuxLLMConfig(enabled=False).validate() == []
    assert any("model" in e for e in AuxLLMConfig(enabled=True, model="").validate())
    assert any(
        "backend" in e
        for e in AuxLLMConfig(enabled=True, model="m", backend="transformers").validate()
    )
    assert AuxLLMConfig(enabled=True, model="m", backend="openai").validate() == []


# ── GET /api/llm/aux ─────────────────────────────────────────────────────────

def test_get_aux_models_endpoint(monkeypatch, tmp_path):
    target = tmp_path / "aux_models.yaml"
    registry = AuxLLMRegistry()
    registry.models["life"] = AuxLLMConfig(enabled=True, model="small-a")
    registry.save_yaml(str(target))

    from config import paths

    monkeypatch.setattr(
        type(paths), "aux_models_yaml", property(lambda self: target)
    )
    monkeypatch.setattr(
        llm_router, "get_state", lambda: _FakeState(_FakeLLMService())
    )

    data = llm_router.get_aux_models()
    assert set(data["slots"]) == set(AUX_SLOTS)
    assert data["models"]["life"]["model"] == "small-a"
    assert data["models"]["memory"]["enabled"] is False
    assert data["runtime"] == {}
    assert data["path"] == str(target)


def test_get_aux_models_exposes_runtime_status(monkeypatch, tmp_path):
    target = tmp_path / "aux_models.yaml"
    from config import paths

    monkeypatch.setattr(
        type(paths), "aux_models_yaml", property(lambda self: target)
    )
    svc = _FakeLLMService()
    svc.registered["memory"] = type("C", (), {"model": "m1"})()
    monkeypatch.setattr(llm_router, "get_state", lambda: _FakeState(svc))

    data = llm_router.get_aux_models()
    assert data["runtime"] == {"memory": {"model": "m1"}}


# ── POST /api/llm/aux/save ───────────────────────────────────────────────────

def test_save_aux_models_persists_and_applies(monkeypatch, tmp_path):
    target = _patch_aux_yaml(monkeypatch, tmp_path)
    svc = _FakeLLMService()
    monkeypatch.setattr(llm_router, "get_state", lambda: _FakeState(svc))

    resp = llm_router.save_aux_models({
        "models": {
            "life": {"enabled": True, "model": "small-a", "base_url": "http://x/v1"},
            "memory": {"enabled": False, "model": ""},
        }
    })

    assert resp["status"] == "ok"
    assert resp["applied"]["life"] == "ok"
    assert "fallback" in resp["applied"]["memory"]
    assert svc.registered["life"].model == "small-a"
    assert "memory" in svc.unregistered

    on_disk = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert on_disk["models"]["life"]["model"] == "small-a"
    assert set(on_disk["models"].keys()) == set(AUX_SLOTS)


def test_save_aux_models_per_slot_error_isolation(monkeypatch, tmp_path):
    _patch_aux_yaml(monkeypatch, tmp_path)
    svc = _FakeLLMService()
    monkeypatch.setattr(llm_router, "get_state", lambda: _FakeState(svc))

    resp = llm_router.save_aux_models({
        "models": {
            "life": {"enabled": True, "model": ""},  # 非法：enabled 但无 model
            "persona": {"enabled": True, "model": "small-b"},
        }
    })

    assert resp["applied"]["life"].startswith("skipped")
    assert resp["applied"]["persona"] == "ok"
    assert "life" not in svc.registered
    assert svc.registered["persona"].model == "small-b"


def test_save_aux_models_without_llm_service_still_saves(monkeypatch, tmp_path):
    target = _patch_aux_yaml(monkeypatch, tmp_path)
    monkeypatch.setattr(llm_router, "get_state", lambda: _FakeState(None))

    resp = llm_router.save_aux_models({
        "models": {"life": {"enabled": True, "model": "small-a"}}
    })

    assert resp["status"] == "saved"
    assert target.exists()
