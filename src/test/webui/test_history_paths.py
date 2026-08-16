from __future__ import annotations

import json

from webui.history_files import resolve_history_path, write_history_path


def test_resolve_history_path_maps_live_id_to_sanitized_file(tmp_path):
    session_id = "live:b6812c30-3d38-4f78-b898-e7e332821c4a"
    path = tmp_path / "live_b6812c30-3d38-4f78-b898-e7e332821c4a.json"
    path.write_text(
        json.dumps({"id": session_id, "session_id": session_id, "title": "主动"}),
        encoding="utf-8",
    )
    found = resolve_history_path(str(tmp_path), session_id)
    assert found == str(path)


def test_write_history_path_reuses_sanitized_file(tmp_path):
    session_id = "live:abc"
    existing = tmp_path / "live_abc.json"
    existing.write_text(json.dumps({"id": session_id}), encoding="utf-8")
    assert write_history_path(str(tmp_path), session_id) == str(existing)
