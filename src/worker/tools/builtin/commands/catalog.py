from __future__ import annotations

from worker.tools.builtin.commands.bash import GROUPS as BASH_GROUPS
from worker.tools.builtin.commands.powershell import GROUPS as POWERSHELL_GROUPS
from worker.tools.builtin.commands.schema import CommandEntry, CommandGroup
from worker.tools.builtin.commands.winnt import GROUPS as WINNT_GROUPS

ALL_GROUPS: tuple[CommandGroup, ...] = POWERSHELL_GROUPS + BASH_GROUPS + WINNT_GROUPS


def all_entries() -> list[CommandEntry]:
    return [entry for group in ALL_GROUPS for entry in group.entries]


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return 0x4E00 <= code <= 0x9FFF


def _query_tokens(query: str) -> list[str]:
    text = query.strip().lower()
    if not text:
        return []

    tokens: list[str] = []
    for part in text.split():
        if part:
            tokens.append(part)

    cjk = "".join(ch for ch in query if _is_cjk(ch))
    if len(cjk) >= 2:
        for size in (2, 3):
            for idx in range(len(cjk) - size + 1):
                gram = cjk[idx : idx + size]
                if gram not in tokens:
                    tokens.append(gram)

    return tokens


def _entry_corpus(entry: CommandEntry) -> str:
    parts = [
        entry.id,
        entry.family,
        entry.group,
        entry.name,
        entry.synopsis,
        entry.template,
        entry.example,
        entry.run_tool,
        " ".join(entry.tags),
    ]
    return " ".join(parts).lower()


def search_commands(
    query: str,
    *,
    family: str = "",
    group: str = "",
    top_k: int = 5,
) -> list[CommandEntry]:
    tokens = _query_tokens(query)
    if not tokens:
        return []

    scored: list[tuple[int, CommandEntry]] = []
    for entry in all_entries():
        if family and entry.family != family:
            continue
        if group and entry.group != group:
            continue
        corpus = _entry_corpus(entry)
        score = sum(1 for token in tokens if token in corpus)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda item: (-item[0], item[1].id))
    return [entry for _, entry in scored[: max(1, int(top_k))]]
