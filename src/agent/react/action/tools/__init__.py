from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolMeta, ToolPackage, ToolRegistry
    from .tool_search import ToolSearchAction
    from .impl import (
        Base64Action,
        CalculatorAction,
        FileExistsAction,
        FileListAction,
        FileReadAction,
        FileWriteAction,
        GenerateUUIDAction,
        GetDatetimeAction,
        GetWeekdayAction,
        HashAction,
        HttpRequestAction,
        JsonQueryAction,
        MemoryRecallAction,
        NoteDeleteAction,
        NoteReadAction,
        NoteWriteAction,
        PythonRunAction,
        RandomChoiceAction,
        RandomNumberAction,
        RegexExtractAction,
        StringTransformAction,
        TextDiffAction,
        UnitConverterAction,
        WeatherAction,
        WebSearchAction,
        WordCountAction,
    )

__all__ = [
    "ToolRegistry",
    "ToolMeta",
    "ToolPackage",
    "Base64Action",
    "CalculatorAction",
    "FileExistsAction",
    "FileListAction",
    "FileReadAction",
    "FileWriteAction",
    "GenerateUUIDAction",
    "GetDatetimeAction",
    "GetWeekdayAction",
    "HashAction",
    "HttpRequestAction",
    "JsonQueryAction",
    "MemoryRecallAction",
    "NoteDeleteAction",
    "NoteReadAction",
    "NoteWriteAction",
    "PythonRunAction",
    "RandomChoiceAction",
    "RandomNumberAction",
    "RegexExtractAction",
    "StringTransformAction",
    "TextDiffAction",
    "ToolSearchAction",
    "UnitConverterAction",
    "WeatherAction",
    "WebSearchAction",
    "WordCountAction",
]

_lazy_from_registry = {"ToolMeta", "ToolPackage", "ToolRegistry"}
_lazy_from_tool_search = {"ToolSearchAction"}
_lazy_from_impl = {
    "Base64Action", "CalculatorAction", "FileExistsAction", "FileListAction",
    "FileReadAction", "FileWriteAction", "GenerateUUIDAction", "GetDatetimeAction",
    "GetWeekdayAction", "HashAction", "HttpRequestAction", "JsonQueryAction",
    "MemoryRecallAction", "NoteDeleteAction", "NoteReadAction", "NoteWriteAction",
    "PythonRunAction", "RandomChoiceAction", "RandomNumberAction", "RegexExtractAction",
    "StringTransformAction", "TextDiffAction", "UnitConverterAction", "WeatherAction",
    "WebSearchAction", "WordCountAction",
}


def __getattr__(name: str):
    import importlib

    if name in _lazy_from_registry:
        mod = importlib.import_module(".registry", __name__)
    elif name in _lazy_from_tool_search:
        mod = importlib.import_module(".tool_search", __name__)
    elif name in _lazy_from_impl:
        mod = importlib.import_module(".impl", __name__)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    val = getattr(mod, name)
    globals()[name] = val
    return val
