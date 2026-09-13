"""从 HuggingFace 数据集抓取示例并转换为 benchmark 用例（可选工具）。

主数据集是仓库内人工编写的 ``data/cases.jsonl``；本脚本提供
"直接从网络上 fetch 示例" 的通道，默认源为
``facebook/empathetic_dialogues``（共情对话），经 datasets-server
REST API 拉取行并转换为记忆相关用例（情境 → 预载记忆，下一句 → 用户当前输入）。

用法（cwd 任意，需联网）::

    PYTHONPATH=src python -m evals.memory_humaneness.fetch_hf \
        --limit 100 --out src/evals/memory_humaneness/data/cases_hf.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

DEFAULT_DATASET = "facebook/empathetic_dialogues"
DEFAULT_CONFIG = "default"
API = "https://datasets-server.huggingface.co/rows"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_WORD_RE = re.compile(r"[A-Za-z]{3,}")


def fetch_rows(dataset: str, config: str, split: str, limit: int) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    page = min(100, max(1, limit))
    while len(rows) < limit:
        url = (
            f"{API}?dataset={dataset}&config={config}&split={split}"
            f"&offset={offset}&length={page}"
        )
        with urllib.request.urlopen(url, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        batch = payload.get("rows") or []
        if not batch:
            break
        rows.extend(item.get("row") or item for item in batch)
        offset += len(batch)
    return rows[:limit]


def keywords_of(text: str, limit: int = 3) -> list[str]:
    cjk = _CJK_RE.findall(text)
    if cjk:
        return [w for w in cjk if len(w) >= 2][:limit]
    return [w.lower() for w in _WORD_RE.findall(text)][:limit]


def row_to_case(idx: int, row: dict, dataset: str) -> dict:
    situation = str(row.get("prompt") or row.get("situation") or "").strip()
    utterance = str(row.get("utterance") or "").strip()
    context = str(row.get("context") or "").strip()
    emotion = str(row.get("emotion") or "neutral").strip()
    if not utterance:
        utterance = context or situation
    memory_text = situation or context
    valence_map = {
        "joyful": "positive", "excited": "positive", "surprised": "positive",
        "content": "positive", "faithful": "positive", "impressed": "positive",
        "sad": "negative", "angry": "negative", "afraid": "negative",
        "disgusted": "negative", "anxious": "negative", "lonely": "negative",
        "terrified": "negative", "devastated": "negative",
        "anticipating": "neutral", "sentimental": "mixed", "nostalgic": "mixed",
        "apprehensive": "neutral", "prepared": "neutral", "caring": "positive",
        "grateful": "positive", "hopeful": "positive", "embarrassed": "mixed",
        "jealous": "negative", "proud": "positive", "annoyed": "negative",
        "confident": "positive", "disappointed": "negative", "furious": "negative",
    }
    return {
        "case_id": f"hf-{idx:03d}",
        "category": "event_recall" if memory_text else "graceful_absence",
        "memories": (
            [{
                "text": f"用户提到过：{memory_text}",
                "focus": keywords_of(memory_text, 1)[0] if memory_text else "",
                "emotion": emotion,
                "valence": valence_map.get(emotion, "neutral"),
                "days_ago": float(3 + (idx * 7) % 27),
                "tags": keywords_of(memory_text, 2),
            }]
            if memory_text else []
        ),
        "history": [],
        "current_user": utterance,
        "must_remember": keywords_of(memory_text, 2),
        "note": f"from HF {dataset}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--split", default="train")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    rows = fetch_rows(args.dataset, args.config, args.split, args.limit)
    cases = [row_to_case(i, row, args.dataset) for i, row in enumerate(rows)]
    out = Path(args.out) if args.out else (
        Path(__file__).resolve().parent / "data" / "cases_hf.jsonl"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for case in cases:
            fh.write(json.dumps(case, ensure_ascii=False))
            fh.write("\n")
    print(f"written {len(cases)} cases -> {out}")


if __name__ == "__main__":
    main()
