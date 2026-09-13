"""Embedding 全局配置端点测试 + SoulMemoryInfraConfig 覆盖协议行为。"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_WEBUI_DIR = Path(__file__).resolve().parents[2] / "webui"
if str(_WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(_WEBUI_DIR))

from config import paths  # noqa: E402
from config.soul.memory.infra_config import SoulMemoryInfraConfig  # noqa: E402
import routers.infra.embedding as embedding_router  # noqa: E402


def _patch_model_yaml(monkeypatch, tmp_path: Path) -> Path:
    target = tmp_path / "model.yaml"
    monkeypatch.setattr(
        type(paths), "embedding_model_yaml", property(lambda self: target)
    )
    return target


# ── GET /api/embedding/config ────────────────────────────────────────────────

def test_get_embedding_config_missing_file_returns_defaults(monkeypatch, tmp_path):
    target = _patch_model_yaml(monkeypatch, tmp_path)
    data = embedding_router.get_embedding_config()
    assert data["exists"] is False
    assert data["config"]["model_name_or_path"] == "BAAI/bge-small-zh-v1.5"
    assert data["requires_restart"] is True


def test_get_embedding_config_reads_yaml(monkeypatch, tmp_path):
    target = _patch_model_yaml(monkeypatch, tmp_path)
    target.write_text(
        yaml.dump({"model_name_or_path": "./models/embedding_model", "device": "cpu"}),
        encoding="utf-8",
    )
    data = embedding_router.get_embedding_config()
    assert data["exists"] is True
    assert data["config"]["model_name_or_path"] == "./models/embedding_model"
    assert data["config"]["device"] == "cpu"


# ── POST /api/embedding/config/save ──────────────────────────────────────────

def test_embedding_save_roundtrip(monkeypatch, tmp_path):
    target = _patch_model_yaml(monkeypatch, tmp_path)
    resp = embedding_router.save_embedding_config({
        "config": {
            "model_name_or_path": "./models/embedding_model",
            "device": "cuda",
            "query_prefix": "q: ",
        }
    })
    assert resp["status"] == "ok"
    assert resp["requires_restart"] is True

    on_disk = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert on_disk["model_name_or_path"] == "./models/embedding_model"
    assert on_disk["device"] == "cuda"
    assert on_disk["query_prefix"] == "q: "

    data = embedding_router.get_embedding_config()
    assert data["exists"] is True
    assert data["config"]["device"] == "cuda"


def test_embedding_save_rejects_empty_model(monkeypatch, tmp_path):
    _patch_model_yaml(monkeypatch, tmp_path)
    resp = embedding_router.save_embedding_config({"config": {"model_name_or_path": ""}})
    assert resp.status_code == 400


def test_embedding_save_preserves_deployment_fields(monkeypatch, tmp_path):
    target = _patch_model_yaml(monkeypatch, tmp_path)
    target.write_text(
        yaml.dump({"host": "127.0.0.1", "port": 8001, "workers": 2}),
        encoding="utf-8",
    )
    embedding_router.save_embedding_config({
        "config": {"model_name_or_path": "new-model"}
    })
    on_disk = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert on_disk["host"] == "127.0.0.1"
    assert on_disk["port"] == 8001
    assert on_disk["workers"] == 2


# ── SoulMemoryInfraConfig 覆盖协议（model.yaml 是唯一 embedding 权威源）───────

def test_infra_load_default_overridden_by_model_yaml(monkeypatch, tmp_path):
    model_yaml = _patch_model_yaml(monkeypatch, tmp_path)
    model_yaml.write_text(
        yaml.dump({
            "model_name_or_path": "./models/embedding_model",
            "device": "cpu",
            "query_prefix": "query: ",
        }),
        encoding="utf-8",
    )
    cfg = SoulMemoryInfraConfig.load_default()
    assert cfg.model_name_or_path.endswith("models" + __import__("os").sep + "embedding_model") or \
        cfg.model_name_or_path == "./models/embedding_model"
    assert cfg.device == "cpu"


def test_infra_values_kept_when_model_yaml_missing(monkeypatch, tmp_path):
    _patch_model_yaml(monkeypatch, tmp_path)  # 指向不存在的文件
    cfg = SoulMemoryInfraConfig(
        model_name_or_path="infra-local-model",
        device="cuda",
    )
    resolved = SoulMemoryInfraConfig._apply_embedding_override(cfg)
    assert resolved.model_name_or_path == "infra-local-model"
    assert resolved.device == "cuda"
