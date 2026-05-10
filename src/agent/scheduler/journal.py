from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class WorkJournal:
    """Daily work journal stored as a conversation history JSON file.

    Entries are written as ``role=assistant`` messages with a ``meta``
    dict so they are compatible with the existing history viewer.

    Conv-id format: ``agent_journal_YYYYMMDD``
    """

    def __init__(self, history_dir: str) -> None:
        self._history_dir = history_dir
        self._lock = threading.Lock()

    def today_conv_id(self) -> str:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"agent_journal_{today}"

    def _path(self, conv_id: str) -> str:
        return os.path.join(self._history_dir, f"{conv_id}.json")

    def _load(self, conv_id: str) -> dict:
        path = self._path(conv_id)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {
            "id": conv_id,
            "title": f"Work Journal {today}",
            "mode": "journal",
            "messages": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _save(self, conv_id: str, data: dict) -> None:
        os.makedirs(self._history_dir, exist_ok=True)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        with open(self._path(conv_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _append(self, conv_id: str, content: str, meta: dict) -> None:
        with self._lock:
            data = self._load(conv_id)
            data["messages"].append({
                "role": "assistant",
                "content": content,
                "ts": datetime.now(timezone.utc).isoformat(),
                "meta": meta,
            })
            self._save(conv_id, data)

    def append_task_result(self, task_id: str, task_name: str, instruction: str, answer: str) -> None:
        conv_id = self.today_conv_id()
        content = f"**[{task_name}]** 完成\n\n{answer}"
        meta = {
            "entry_type": "task_result",
            "task_id": task_id,
            "task_name": task_name,
            "instruction": instruction[:200],
        }
        self._append(conv_id, content, meta)
        logger.debug("[WorkJournal] task result appended  task=%s  conv=%s", task_id[:8], conv_id)

    def append_mid_run_message(self, task_id: str, task_name: str, title: str, message: str) -> None:
        conv_id = self.today_conv_id()
        heading = f"**[{task_name}]** {title}" if title else f"**[{task_name}]**"
        content = f"{heading}\n\n{message}"
        meta = {
            "entry_type": "mid_run_message",
            "task_id": task_id,
            "task_name": task_name,
            "title": title,
        }
        self._append(conv_id, content, meta)

    def read(self, date: str | None = None) -> dict:
        if date is None:
            conv_id = self.today_conv_id()
        else:
            conv_id = f"agent_journal_{date.replace('-', '')}"
        with self._lock:
            return self._load(conv_id)
