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
    "ports.py",
    "drive.py",
    "io/actions.py",
    "io/handler.py",
    "io/inbound/ingest.py",
    "io/inbound/bridge.py",
    "io/inbound/unit.py",
    "io/inbound/ports.py",
    "io/outbound/request.py",
    "io/outbound/deliver.py",
    "io/outbound/delivery.py",
    "io/outbound/router.py",
    "io/outbound/unit.py",
    "io/outbound/ports.py",
    "io/outbound/stream/events.py",
    "io/outbound/stream/pipeline.py",
    "io/outbound/stream/channel.py",
    "io/outbound/stream/ports.py",
    "io/outbound/stream/protocol/tags.py",
    "io/outbound/stream/parse/tags.py",
    "io/outbound/stream/parse/parser.py",
    "io/outbound/stream/parse/model.py",
    "io/outbound/stream/flush/segment.py",
    "io/outbound/stream/flush/dispatch.py",
    "io/outbound/stream/flush/token_batch.py",
    "io/outbound/stream/flush/channel.py",
    "llm/engine.py",
    "compose/composer.py",
    "compose/injected/collect.py",
    "compose/injected/persona/collect.py",
    "compose/injected/persona/render.py",
    "io/inbound/compose/collect.py",
    "io/inbound/compose/render.py",
    "compose/system/build.py",
    "compose/system/prompt.py",
    "compose/system/output_format.py",
    "compose/share/state.py",
    "compose/share/prompt.py",
    "compose/share/composer.py",
    "compose/share/reveal.py",
    "compose/runner.py",
    "compose/frame.py",
    "compose/reply_style.py",
    "compose/bundle.py",
    "session/chunk.py",
    "session/service.py",
    "session/turn.py",
    "session/lifecycle/init/bootstrap.py",
    "session/lifecycle/init/starter.py",
    "session/lifecycle/hold/registry.py",
    "session/lifecycle/hold/manager.py",
    "session/lifecycle/hold/semantic.py",
    "session/queue/hub.py",
    "session/queue/compose.py",
    "session/queue/decision.py",
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


def test_io_legacy_top_level_removed():
    root = _speak_root()
    for name in (
        "actions.py",
        "bridge.py",
        "handler.py",
        "outbound.py",
        "outbound_delivery.py",
        "unit.py",
    ):
        assert not (root / name).exists(), f"speak/{name} should live under speak/io/"
    io_root = root / "io"
    for name in (
        "unit.py",
        "bridge.py",
        "inbound.py",
        "outbound.py",
        "delivery.py",
        "ports.py",
    ):
        assert not (io_root / name).exists(), f"speak/io/{name} should live under inbound/ or outbound/"


def test_chunk_package_removed():
    chunk_path = _speak_root() / "chunk.py"
    assert not chunk_path.exists(), "speak/chunk should live under speak/session/chunk"


def test_output_package_removed():
    output_dir = _speak_root() / "output"
    assert not output_dir.exists(), "speak/output legacy package should be removed; use io/outbound/stream/parse"


def test_parse_package_removed():
    parse_dir = _speak_root() / "parse"
    assert not parse_dir.exists(), "speak/parse should live under io/outbound/stream/parse"


def test_protocol_package_removed():
    protocol_dir = _speak_root() / "protocol"
    assert not protocol_dir.exists(), "speak/protocol should live under io/outbound/stream/protocol"


def test_stream_package_removed():
    stream_dir = _speak_root() / "stream"
    assert not stream_dir.exists(), "speak/stream should live under io/outbound/stream"


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
        "compose/injected/persona/collect.py",
        "compose/injected/persona/render.py",
        "io/inbound/compose/collect.py",
        "io/inbound/compose/render.py",
        "compose/share/state.py",
        "compose/share/prompt.py",
        "compose/share/composer.py",
        "compose/share/reveal.py",
    )
    offenders: list[str] = []
    for relative in compose_files:
        path = root / relative
        imports = _collect_imports(path)
        for module in imports:
            if module == "agent.soul.speak.io.outbound.stream.parse" or module.startswith(
                "agent.soul.speak.io.outbound.stream.parse."
            ):
                offenders.append(f"{relative} -> {module}")
            if module.endswith(".outbound.stream.parse") and "speak" in module:
                offenders.append(f"{relative} -> {module}")
    assert offenders == []


def test_tao_delegate_is_only_tools_entry():
    tools_dir = _speak_root() / "tools"
    tao_delegate = tools_dir / "tao_delegate.py"
    assert tao_delegate.exists()
    imports = _collect_imports(tao_delegate)
    assert any(
        module.startswith("agent.adapters.soul_tao")
        or module.startswith("agent.react")
        for module in imports
    )
