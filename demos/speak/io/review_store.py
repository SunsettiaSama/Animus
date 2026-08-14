from __future__ import annotations

import json
from pathlib import Path

from ..stage.review import RhythmReview

_CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache"
_STORE_PATH = _CACHE_DIR / "rhythm_reviews.json"


def _read_all() -> dict[str, dict]:
    if not _STORE_PATH.is_file():
        return {}
    raw = _STORE_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("rhythm_reviews.json: root must be object")
    return payload


def _write_all(data: dict[str, dict]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_review(session_id: str) -> RhythmReview | None:
    data = _read_all()
    item = data.get(session_id.strip())
    if not isinstance(item, dict):
        return None
    review = RhythmReview.from_payload(item)
    if not review.ready:
        return None
    return review


def save_review(session_id: str, review: RhythmReview) -> Path:
    data = _read_all()
    data[session_id.strip()] = review.snapshot()
    _write_all(data)
    return _STORE_PATH
