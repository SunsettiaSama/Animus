from __future__ import annotations

import re


def enforce_canon(text: str, rules: dict[str, list[str]], *, retry_text: str = "") -> str:
    """若命中 forbidden 关键词则 raise；否则返回原文或 strip 后文本。"""
    forbidden = [str(x).strip() for x in (rules.get("forbidden") or []) if str(x).strip()]
    for token in forbidden:
        if token and token in text:
            if retry_text and token not in retry_text:
                return retry_text.strip()
            raise ValueError(f"叙事违反 canon 禁忌：{token}")
    return text.strip()


def lore_context_block(lore_rows: list[dict], entities: list[dict]) -> str:
    lines: list[str] = []
    for row in lore_rows:
        title = str(row.get("title") or "").strip()
        body = str(row.get("body") or "").strip()
        if title:
            lines.append(f"- [{title}] {body}")
        elif body:
            lines.append(f"- {body}")
    for ent in entities:
        name = str(ent.get("name") or "").strip()
        desc = str(ent.get("description") or "").strip()
        kind = str(ent.get("kind") or "").strip()
        if name:
            lines.append(f"- （{kind}）{name}：{desc}")
    return "\n".join(lines) if lines else "（暂无检索到的设定）"
