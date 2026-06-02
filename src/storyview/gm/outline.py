from __future__ import annotations

import re

from storyview.store.mysql import StoryStoreBundle


_ACTIVE_VERBS = re.compile(r"(我决定|我想|我打算|我要|尝试|走向|打开|询问)")


class OutlineTracker:
    def __init__(self, stores: StoryStoreBundle) -> None:
        self._stores = stores

    def check_deviation(self, world_id: str, intent: str) -> tuple[bool, str]:
        text = intent.strip()
        if not text or not _ACTIVE_VERBS.search(text):
            return False, ""
        arc = self._stores.outline.active_arc(world_id)
        if arc is None:
            return False, ""
        beat = self._stores.outline.next_optional_beat(arc["id"])
        if beat is None:
            return False, ""
        summary = str(beat.get("summary") or "").strip()
        if not summary:
            return False, ""
        overlap = self._token_overlap(text, summary)
        if overlap >= 0.35:
            return False, ""
        return True, f"主动意图「{text[:40]}」偏离大纲 beat「{summary[:40]}」"

    def _token_overlap(self, a: str, b: str) -> float:
        ta = self._tokens(a)
        tb = self._tokens(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / max(len(ta), len(tb))

    def _tokens(self, text: str) -> set[str]:
        parts = {t.strip() for t in re.split(r"\W+", text) if t.strip() and len(t.strip()) >= 2}
        chars = [c for c in text if not c.isspace()]
        if len(chars) >= 2:
            parts.update("".join(chars[i : i + 2]) for i in range(len(chars) - 1))
        return parts
