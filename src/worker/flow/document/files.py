"""document/files.py — 按后缀加载 / 保存 DAG 计划文档（Markdown / Word）。"""
from __future__ import annotations

from pathlib import Path

from .markdown import DagMarkdownIO
from .model import DagPlanDocument
from .word_docx import DagWordIO

_SUFFIX_MD = frozenset({".md", ".markdown"})
_SUFFIX_DOCX = frozenset({".docx"})


def supported_plan_suffixes() -> tuple[str, ...]:
    return tuple(sorted(_SUFFIX_MD | _SUFFIX_DOCX))


def load_dag_plan_document(path: str | Path, *, strict: bool = True) -> DagPlanDocument:
    p = Path(path).expanduser()
    suf = p.suffix.lower()
    if suf in _SUFFIX_MD:
        return DagMarkdownIO.from_markdown(p.read_text(encoding="utf-8"), strict=strict)
    if suf in _SUFFIX_DOCX:
        return DagWordIO.from_docx_path(p, strict=strict)
    raise ValueError(
        f"unsupported plan document suffix {suf!r}; "
        f"use one of {sorted(_SUFFIX_MD | _SUFFIX_DOCX)}"
    )


def save_dag_plan_document(doc: DagPlanDocument, path: str | Path) -> None:
    p = Path(path).expanduser()
    suf = p.suffix.lower()
    if suf in _SUFFIX_MD:
        p.write_text(DagMarkdownIO.to_markdown(doc), encoding="utf-8")
        return
    if suf in _SUFFIX_DOCX:
        DagWordIO.to_docx_path(doc, p)
        return
    raise ValueError(
        f"unsupported plan document suffix {suf!r}; "
        f"use one of {sorted(_SUFFIX_MD | _SUFFIX_DOCX)}"
    )
