from __future__ import annotations


def split_text_chunks(
    text: str,
    *,
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """按字符窗口切分文本（带重叠）。"""
    normalized = text.strip()
    if not normalized:
        return []
    if chunk_size <= 0:
        return [normalized]
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 4)
    chunks: list[str] = []
    start = 0
    length = len(normalized)
    while start < length:
        end = min(length, start + chunk_size)
        piece = normalized[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = max(0, end - overlap)
    return chunks
