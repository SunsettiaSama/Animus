from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class TrainDataset:
    """Loads training data from JSONL, Alpaca, or ShareGPT format files.

    Supports optional pre-tokenisation with .arrow caching to avoid
    repeated tokenisation overhead across training runs.
    """

    _ALPACA_KEYS = frozenset({"instruction", "output"})
    _SHAREGPT_KEYS = frozenset({"conversations"})

    def __init__(
        self,
        path: str,
        cache_tokenized: bool = True,
        streaming: bool = False,
    ) -> None:
        self._path = path
        self._cache_tokenized = cache_tokenized
        self._streaming = streaming
        self._records: list[dict] = self.validate_and_filter(self._load_raw(path))

    # ── Loading ───────────────────────────────────────────────────────────────

    @staticmethod
    def _load_raw(path: str) -> list[dict]:
        records: list[dict] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return records

    @staticmethod
    def validate_and_filter(records: list[dict]) -> list[dict]:
        valid: list[dict] = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            if "text" in rec and isinstance(rec["text"], str) and rec["text"].strip():
                valid.append(rec)
                continue
            if "instruction" in rec and "output" in rec:
                valid.append(rec)
                continue
            if (
                "conversations" in rec
                and isinstance(rec["conversations"], list)
                and rec["conversations"]
            ):
                valid.append(rec)
                continue
        return valid

    # ── Formatting ────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_format(record: dict) -> str:
        if "conversations" in record:
            return "sharegpt"
        if "instruction" in record and "output" in record:
            return "alpaca"
        return "text"

    def _format_record(self, record: dict) -> str:
        fmt = self._detect_format(record)
        if fmt == "text":
            return record["text"]
        if fmt == "alpaca":
            instr = record["instruction"].strip()
            inp   = record.get("input", "").strip()
            out   = record["output"].strip()
            if inp:
                return (
                    f"### Instruction:\n{instr}\n\n"
                    f"### Input:\n{inp}\n\n"
                    f"### Response:\n{out}"
                )
            return f"### Instruction:\n{instr}\n\n### Response:\n{out}"
        parts: list[str] = []
        for turn in record["conversations"]:
            role  = turn.get("from", turn.get("role", ""))
            value = turn.get("value", turn.get("content", ""))
            if role in ("human", "user"):
                parts.append(f"Human: {value}")
            elif role in ("gpt", "assistant"):
                parts.append(f"Assistant: {value}")
        return "\n\n".join(parts)

    def formatting_func(self, batch: dict) -> list[str]:
        n = len(next(iter(batch.values())))
        return [self._format_record({k: v[i] for k, v in batch.items()}) for i in range(n)]

    # ── HuggingFace Dataset bridge ────────────────────────────────────────────

    def to_hf_dataset(self, tokenizer=None, cache_dir: str | None = None):
        from datasets import Dataset

        hf = Dataset.from_list(self._records)
        if self._cache_tokenized and tokenizer is not None and not self._streaming:
            return self._tokenize_and_cache(hf, tokenizer, cache_dir)
        return hf

    def _tokenize_and_cache(self, hf, tokenizer, cache_dir: str | None):
        cache_path: str | None = None
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
            stem = Path(self._path).stem
            cache_path = os.path.join(cache_dir, f"tokenized_{stem}")
            if os.path.exists(cache_path):
                from datasets import Dataset
                return Dataset.load_from_disk(cache_path)

        def _tokenize_batch(batch: dict) -> dict:
            texts = [
                self._format_record({k: v[i] for k, v in batch.items()})
                for i in range(len(next(iter(batch.values()))))
            ]
            return tokenizer(texts, truncation=True, padding=False)

        tokenized = hf.map(
            _tokenize_batch,
            batched=True,
            remove_columns=hf.column_names,
        )
        if cache_path:
            tokenized.save_to_disk(cache_path)
        return tokenized

    def __len__(self) -> int:
        return len(self._records)
