from __future__ import annotations

import json
import os

from ...persona.preference.entry import PreferenceEntry
from ...persona.preference.recent import RecentPreference


class PreferenceStore:
    """将 RecentPreference 的 PreferenceEntry 列表持久化到 preference.json。

    文件路径：<persona_dir>/preference.json
    """

    _FILENAME = "preference.json"

    def __init__(self, persona_dir: str) -> None:
        self._dir = persona_dir
        self._path = os.path.join(persona_dir, self._FILENAME)

    def load(self, window_days: int = 7, max_topics: int = 5) -> RecentPreference:
        if not os.path.exists(self._path):
            return RecentPreference(window_days=window_days, max_topics=max_topics)
        with open(self._path, encoding="utf-8") as f:
            raw = json.load(f)
        entries = [PreferenceEntry.from_dict(d) for d in raw if isinstance(d, dict)]
        rp = RecentPreference(entries=entries, window_days=window_days, max_topics=max_topics)
        rp._prune()
        return rp

    def save(self, recent: RecentPreference) -> None:
        os.makedirs(self._dir, exist_ok=True)
        data = [e.to_dict() for e in recent.entries]
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
