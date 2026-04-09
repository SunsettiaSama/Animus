from __future__ import annotations

import csv
from dataclasses import dataclass, field


@dataclass
class Chunk:
    chunk_id: int
    source_row: int
    text: str
    meta: dict = field(default_factory=dict)


def load_csv(csv_path: str, text_column: str, extra_columns: list[str]) -> list[dict]:
    rows: list[dict] = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if text_column not in row:
                raise KeyError(f"column '{text_column}' not found in CSV; available: {list(row.keys())}")
            rows.append(
                {
                    "source_row": i,
                    "text": row[text_column].strip(),
                    "meta": {col: row.get(col, "") for col in extra_columns},
                }
            )
    return rows


def _split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - chunk_overlap
    return chunks


def build_chunks(rows: list[dict], chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    chunk_id = 0
    for row in rows:
        text = row["text"]
        if not text:
            continue
        for piece in _split_text(text, chunk_size, chunk_overlap):
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    source_row=row["source_row"],
                    text=piece,
                    meta=row["meta"],
                )
            )
            chunk_id += 1
    return chunks
