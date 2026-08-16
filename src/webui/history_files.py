from __future__ import annotations

import json
import os


def safe_history_name(conv_id: str) -> str:
    return (
        str(conv_id or "")
        .strip()
        .replace(":", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )


def resolve_history_path(history_dir: str, conv_id: str) -> str:
    key = str(conv_id or "").strip()
    if not key or not history_dir:
        return ""
    candidates = [
        os.path.join(history_dir, f"{key}.json"),
        os.path.join(history_dir, f"{safe_history_name(key)}.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    if not os.path.isdir(history_dir):
        return ""
    for filename in os.listdir(history_dir):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(history_dir, filename)
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if str(data.get("id") or "") == key or str(data.get("session_id") or "") == key:
            return path
    return ""


def write_history_path(history_dir: str, conv_id: str) -> str:
    existing = resolve_history_path(history_dir, conv_id)
    if existing:
        return existing
    return os.path.join(history_dir, f"{safe_history_name(conv_id)}.json")
