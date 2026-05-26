from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "agent.react.tao",
    "agent.react.loop",
    "agent.adapters.react_stream",
)

CORE_RELATIVE = (
    "service.py",
    "handler.py",
    "ports.py",
    "drive.py",
    "bridge.py",
    "llm/engine.py",
    "compose/composer.py",
    "compose/injected/collect.py",
    "compose/injected/render.py",
    "compose/system/build.py",
    "compose/system/prompt.py",
    "compose/system/output_format.py",
    "compose/share_queue.py",
    "compose/reply_style.py",
    "compose/bundle.py",
    "protocol/tags.py",
    "parse/tags.py",
    "parse/parser.py",
    "parse/model.py",
    "stream/pipeline.py",
    "stream/segmenter.py",
    "stream/events.py",
    "session/registry.py",
    "session/semantic.py",
)


def _speak_root() -> Path:
    return Path(__file__).resolve().parents[3] / "agent" / "soul" / "speak"


def _collect_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_speak_core_modules_do_not_import_tao_or_react_stream():
    root = _speak_root()
    offenders: list[str] = []
    for relative in CORE_RELATIVE:
        path = root / relative
        assert path.exists(), f"missing core speak file: {relative}"
        imports = _collect_imports(path)
        for module in imports:
            for forbidden in FORBIDDEN_PREFIXES:
                if module == forbidden or module.startswith(f"{forbidden}."):
                    offenders.append(f"{relative} -> {module}")
    assert offenders == []


def test_speak_react_package_removed():
    react_dir = _speak_root() / "react"
    assert not react_dir.exists(), "speak/react legacy package should be removed"


def test_speak_output_package_removed():
    output_dir = _speak_root() / "output"
    assert not output_dir.exists(), "speak/output legacy package should be removed; use speak/parse"


def test_compose_does_not_import_parse():
    root = _speak_root()
    compose_files = (
        "compose/composer.py",
        "compose/bundle.py",
        "compose/reply_style.py",
        "compose/system/build.py",
        "compose/system/output_format.py",
        "compose/system/prompt.py",
        "compose/injected/collect.py",
        "compose/injected/render.py",
    )
    offenders: list[str] = []
    for relative in compose_files:
        path = root / relative
        imports = _collect_imports(path)
        for module in imports:
            if module == "agent.soul.speak.parse" or module.startswith("agent.soul.speak.parse."):
                offenders.append(f"{relative} -> {module}")
            if module.endswith(".parse") and "speak" in module:
                offenders.append(f"{relative} -> {module}")
    assert offenders == []


def test_tao_delegate_is_only_tools_entry():
    tools_dir = _speak_root() / "tools"
    tao_delegate = tools_dir / "tao_delegate.py"
    assert tao_delegate.exists()
    imports = _collect_imports(tao_delegate)
    assert any(
        module.startswith("agent.soul.handlers.tao")
        or module.startswith("agent.react")
        for module in imports
    )
