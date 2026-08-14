"""Pinned Hugging Face IFEval download and deterministic 80-case sampling."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx

DATASET_REPO = "google/IFEval"
DATASET_REVISION = "193ae952ec892316cf21fb5d8cbb704e811fe873"
DATASET_FILENAME = "ifeval_input_data.jsonl"
DATASET_URL = (
    f"https://huggingface.co/datasets/{DATASET_REPO}/resolve/"
    f"{DATASET_REVISION}/{DATASET_FILENAME}"
)
SAMPLE_SIZE = 80
SAMPLING_ALGORITHM = "primary_instruction_family_round_robin_v1"

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATA_DIR = _REPO_ROOT / "data" / "workbench" / "ifeval"
DEFAULT_CASES_PATH = DEFAULT_DATA_DIR / "ifeval_80.jsonl"
DEFAULT_MANIFEST_PATH = DEFAULT_DATA_DIR / "manifest.json"


@dataclass(frozen=True)
class IFEvalCase:
    key: int
    prompt: str
    instruction_id_list: tuple[str, ...]
    kwargs: tuple[dict[str, Any], ...]

    @property
    def primary_family(self) -> str:
        return self.instruction_id_list[0].split(":", 1)[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "prompt": self.prompt,
            "instruction_id_list": list(self.instruction_id_list),
            "kwargs": [dict(item) for item in self.kwargs],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "IFEvalCase":
        required = {"key", "prompt", "instruction_id_list", "kwargs"}
        missing = required.difference(raw)
        if missing:
            raise ValueError(f"IFEval case missing fields: {sorted(missing)}")
        instruction_ids = raw["instruction_id_list"]
        kwargs = raw["kwargs"]
        if not isinstance(instruction_ids, list) or not instruction_ids:
            raise ValueError("instruction_id_list must be a non-empty list")
        if not isinstance(kwargs, list) or len(kwargs) != len(instruction_ids):
            raise ValueError("kwargs must align with instruction_id_list")
        prompt = str(raw["prompt"]).strip()
        if not prompt:
            raise ValueError("prompt must not be empty")
        return cls(
            key=int(raw["key"]),
            prompt=prompt,
            instruction_id_list=tuple(str(x) for x in instruction_ids),
            kwargs=tuple(dict(x or {}) for x in kwargs),
        )


def parse_jsonl(text: str) -> list[IFEvalCase]:
    cases: list[IFEvalCase] = []
    seen_keys: set[int] = set()
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"line {line_number}: root must be object")
        case = IFEvalCase.from_dict(payload)
        if case.key in seen_keys:
            raise ValueError(f"line {line_number}: duplicate key {case.key}")
        seen_keys.add(case.key)
        cases.append(case)
    if not cases:
        raise ValueError("IFEval source is empty")
    return cases


def _bucket_by_primary_family(
    cases: Iterable[IFEvalCase],
) -> dict[str, list[IFEvalCase]]:
    buckets: dict[str, list[IFEvalCase]] = {}
    for case in sorted(cases, key=lambda item: item.key):
        buckets.setdefault(case.primary_family, []).append(case)
    return buckets


def stratified_sample(
    cases: Iterable[IFEvalCase],
    *,
    sample_size: int = SAMPLE_SIZE,
) -> list[IFEvalCase]:
    """Round-robin primary instruction families with stable key ordering."""
    source = list(cases)
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    if sample_size > len(source):
        raise ValueError(
            f"sample_size={sample_size} exceeds source size={len(source)}"
        )

    buckets = _bucket_by_primary_family(source)
    selected: list[IFEvalCase] = []
    cursor = 0
    families = sorted(buckets)
    while len(selected) < sample_size:
        progressed = False
        for family in families:
            bucket = buckets[family]
            if cursor < len(bucket):
                selected.append(bucket[cursor])
                progressed = True
                if len(selected) == sample_size:
                    break
        if not progressed:
            raise RuntimeError("unable to fill deterministic IFEval sample")
        cursor += 1
    return selected


def serialize_jsonl(cases: Iterable[IFEvalCase]) -> str:
    lines = [
        json.dumps(case.to_dict(), ensure_ascii=False, sort_keys=True)
        for case in cases
    ]
    return "\n".join(lines) + "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def download_source(*, timeout_sec: float = 120.0) -> str:
    response = httpx.get(DATASET_URL, follow_redirects=True, timeout=timeout_sec)
    response.raise_for_status()
    return response.text


def download_and_sample(
    *,
    cases_path: Path = DEFAULT_CASES_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    sample_size: int = SAMPLE_SIZE,
) -> dict[str, Any]:
    source_text = download_source()
    source_cases = parse_jsonl(source_text)
    sampled = stratified_sample(source_cases, sample_size=sample_size)
    sampled_text = serialize_jsonl(sampled)

    cases_path.parent.mkdir(parents=True, exist_ok=True)
    cases_path.write_text(sampled_text, encoding="utf-8")
    family_counts: dict[str, int] = {}
    for case in sampled:
        family_counts[case.primary_family] = (
            family_counts.get(case.primary_family, 0) + 1
        )
    manifest = {
        "dataset_repo": DATASET_REPO,
        "dataset_revision": DATASET_REVISION,
        "dataset_url": DATASET_URL,
        "license": "apache-2.0",
        "source_filename": DATASET_FILENAME,
        "source_count": len(source_cases),
        "sample_count": len(sampled),
        "sampling_algorithm": SAMPLING_ALGORITHM,
        "sample_sha256": sha256_text(sampled_text),
        "primary_family_counts": dict(sorted(family_counts.items())),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[IFEvalCase]:
    return parse_jsonl(path.read_text(encoding="utf-8"))
