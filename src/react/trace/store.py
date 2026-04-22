from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config.react.trace_config import TraceConfig
from react.memory.memory import Step


def _trunc(text: str, limit: int) -> str:
    return text[:limit] if limit > 0 and len(text) > limit else text


class TraceStore:
    def __init__(self, cfg: TraceConfig) -> None:
        self._cfg = cfg
        self._dir = Path(cfg.trace_dir)

    def write(self, question: str, answer: str, steps: list[Step]) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        slug = question[:40].replace(" ", "_").replace("/", "-")
        filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{slug}.json"

        record = {
            "id": str(uuid.uuid4()),
            "timestamp": now.isoformat(),
            "question": question,
            "answer": answer,
            "steps": [
                {
                    "index": i,
                    "thought": _trunc(s.thought, self._cfg.max_thought_chars),
                    "action": s.action,
                    "action_input": s.action_input,
                    "observation": _trunc(s.observation, self._cfg.max_observation_chars),
                }
                for i, s in enumerate(steps)
            ],
        }

        path = self._dir / filename
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
