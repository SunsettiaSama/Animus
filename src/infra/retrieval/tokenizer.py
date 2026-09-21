"""检索查询切词：三级降级链（jieba → 字符 n-gram → 原样）。

L1  jieba.posseg（HMM=False，确定性；词性用于低贡献词过滤与实体识别）
L2  fallback：正则切分（中文单字 + 英文词 + 数字），无词性，仍可产出 terms/entities
L3  调用侧兜底：rewrite 结果为空时回退原文 strip（见 rewriter.py）

降级发生时记日志（不静默）；backend() 暴露当前档位供观测与测试。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z][A-Za-z0-9_-]*|\d+(?:\.\d+)?")

_jieba_posseg = None
_jieba_failed = False


def _load_jieba():
    global _jieba_posseg, _jieba_failed
    if _jieba_posseg is not None or _jieba_failed:
        return _jieba_posseg
    try:
        import jieba
        import jieba.posseg

        jieba.setLogLevel(logging.WARNING)
        _jieba_posseg = jieba.posseg
    except Exception as exc:
        _jieba_failed = True
        logger.warning("[retrieval.tokenizer] jieba 不可用（%s），降级字符 n-gram 链路", exc)
    return _jieba_posseg


@dataclass(frozen=True)
class TokenizedTerm:
    word: str
    pos: str  # jieba 词性；fallback 链路为 ""（未知，按保留处理）


def _tokenize_jieba(text: str) -> list[TokenizedTerm]:
    posseg = _load_jieba()
    if posseg is None:
        return []
    return [
        TokenizedTerm(word=pair.word.strip(), pos=str(pair.flag))
        for pair in posseg.lcut(text, HMM=False)
        if pair.word.strip()
    ]


def _tokenize_fallback(text: str) -> list[TokenizedTerm]:
    terms: list[TokenizedTerm] = []
    for chunk in _TOKEN_RE.findall(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) >= 2:
            terms.append(TokenizedTerm(word=chunk, pos=""))
        # 单个 CJK 字单独成词（bigram 语义由下游 BM25/关键词层自行处理）
        elif "\u4e00" <= chunk <= "\u9fff":
            terms.append(TokenizedTerm(word=chunk, pos=""))
    return terms


def backend() -> str:
    """当前切词档位："jieba" | "fallback"。"""
    return "jieba" if _load_jieba() is not None else "fallback"


def tokenize(text: str) -> tuple[list[TokenizedTerm], str]:
    """返回 (terms, backend)。空输入返回 ([], backend())。"""
    raw = str(text or "").strip()
    if not raw:
        return [], backend()
    if _load_jieba() is not None:
        terms = _tokenize_jieba(raw)
        if terms:
            return terms, "jieba"
    return _tokenize_fallback(raw), "fallback"
