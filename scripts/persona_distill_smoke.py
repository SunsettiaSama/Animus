#!/usr/bin/env python3
"""?? smoke?????? ?????????? ?????? LLM ??system / user ?????""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from agent.soul.persona.distill import PersonaDistillPack, PersonaDistillWriter
from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.self_concept.concept import SelfConcept
from agent.soul.speak.orchestrator import SpeakPromptBundle
from agent.soul.speak.orchestrator.persona import collect_persona_layer
from agent.soul.speak.orchestrator.scene import SpeakSceneLayer
from agent.soul.speak.orchestrator.guidance import SpeakGuidanceLayer
from agent.soul.speak.orchestrator.system import build_system_layer
from agent.soul.speak.orchestrator.system.output_format import SpeakOutputFormat
from agent.soul.speak.io.outbound.stream import parse_agent_output
from agent.soul.speak.llm.engine import SpeakLLMEngine
from config.llm_core.config import LLMConfig
from config.storage import StorageConfig
from infra.llm import LLM

_FIXTURE = SRC / "test" / "soul" / "persona" / "fixtures" / "rich_built_profile.json"
_LLM_CANDIDATES = [
    ROOT / "config" / "llm_core" / "config.yaml",
    ROOT / "config" / "llm.yaml",
]


def _sep(title: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n  {title}\n{line}", flush=True)


def _load_llm_config() -> LLMConfig:
    for path in _LLM_CANDIDATES:
        if path.is_file():
            cfg = LLMConfig.from_yaml(str(path))
            if cfg.api_key.strip() and cfg.model.strip():
                if cfg.backend not in ("openai", "vllm", "vllm-clone"):
                    cfg.backend = "openai"
                return cfg
    raise SystemExit(
        "????config/llm_core/config.yaml?api_key + model???? REACT_TEST_LLM_* ????"
    )


def _load_source() -> dict:
    storage = StorageConfig()
    persona_dir = Path(storage.resolve_persona_dir(""))
    built = persona_dir / "built_profile.json"
    if built.is_file():
        profile = json.loads(built.read_text(encoding="utf-8"))
        sc_path = persona_dir / "self_concept.json"
        concept = json.loads(sc_path.read_text(encoding="utf-8")) if sc_path.is_file() else {}
        return {"profile": profile, "self_concept": concept, "attention_keywords": []}
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _persona_snap_from_pack(data: dict, pack: PersonaDistillPack) -> dict:
    snap = dict(data)
    snap["persona_distill"] = pack.to_dict()
    return snap


def _empty_presence_snap() -> SimpleNamespace:
    return SimpleNamespace(session_id="smoke", state=None)


def _print_llm_turn(*, turn: int, user_text: str, system: str, reply: str) -> None:
    _sep(f"??{turn} ??· ??? LLM ????)
    print(f"[HumanMessage] ({len(user_text)} chars)\n{user_text}\n", flush=True)
    print(f"[SystemMessage] ({len(system)} chars)\n{system}\n", flush=True)
    print(f"[Assistant ??] ({len(reply)} chars)\n{reply}\n", flush=True)
    parsed = parse_agent_output(reply)
    if parsed.speak.strip():
        print(f"[?? speak]\n{parsed.speak.strip()}\n", flush=True)
    if parsed.thought.strip():
        print(f"[?? thought]\n{parsed.thought.strip()}\n", flush=True)


def _simulate_turns(
    *,
    llm: LLM,
    persona_snap: dict,
    user_turns: list[str],
    dialogue_history: list[tuple[str, str]],
) -> None:
    presence = _empty_presence_snap()
    output_fmt = SpeakOutputFormat(max_fragments=3).render_prompt()
    engine = SpeakLLMEngine(llm)

    for i, user_text in enumerate(user_turns, start=1):
        compressed_lines: list[str] = []
        for u, a in dialogue_history:
            compressed_lines.append(f"???{u}")
            if a.strip():
                compressed_lines.append(f"??{a}")
        dialogue_compressed = "\n".join(compressed_lines)

        session_wm = ""
        if dialogue_compressed.strip():
            session_wm = "????????????\n" + dialogue_compressed.strip()

        bundle = SpeakPromptBundle(
            session_id="smoke",
            mode="inbound",
            system=build_system_layer(
                mode="inbound",
                output_format=output_fmt,
            ),
            persona=collect_persona_layer(
                persona_snap=persona_snap,
                presence_snap=presence,
                dialogue_compressed=dialogue_compressed,
            ),
            scene=SpeakSceneLayer(),
            guidance=SpeakGuidanceLayer(working_memory=session_wm),
            user_text=user_text,
        )
        system = bundle.build_system()

        _sep(f"??{i} ??· ??????)
        print(
            json.dumps(
                {
                    "persona_dialogue_chars": len(bundle.persona_dialogue),
                    "persona_presence_chars": len(bundle.persona.presence),
                    "dialogue_compressed_chars": len(dialogue_compressed),
                    "system_total_chars": len(system),
                    "user_chars": len(user_text),
                },
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )
        if bundle.persona_dialogue.strip():
            print(f"\n--- persona dialogue ??---\n{bundle.persona_dialogue}\n", flush=True)
        if dialogue_compressed.strip():
            print(f"--- ???????? session_working_memory??--\n{dialogue_compressed}\n", flush=True)

        reply = engine.generate(user_text, system=system).text
        _print_llm_turn(turn=i, user_text=user_text, system=system, reply=reply)
        parsed = parse_agent_output(reply)
        dialogue_history.append((user_text, parsed.speak.strip() or reply[:200]))


def main() -> None:
    cfg = _load_llm_config()
    print(f"LLM: backend={cfg.backend} model={cfg.model}", flush=True)

    llm = LLM(cfg)
    data = _load_source()
    profile = PersonaProfile.from_dict(data["profile"])
    concept = SelfConcept.from_dict(data.get("self_concept") or {})
    revision = f"{profile.built_at or 'raw'}|{concept.updated_at or ''}"

    _sep("??????API LLM??)
    pack = PersonaDistillWriter(llm).distill(
        profile,
        concept,
        attention_keywords=list(data.get("attention_keywords") or []),
        source_revision=revision,
    )
    for key in ("general", "dialogue", "story", "reasoning", "memory_anchor"):
        text = pack.slice(key)
        print(f"\n--- {key} ({len(text)} chars) ---\n{text}\n", flush=True)

    persona_snap = _persona_snap_from_pack(data, pack)
    user_turns = [
        "?????????????????,
        "????????????????????????,
        "????????????????,
    ]

    _sep("?????????Speak ?? + ?? LLM ????)
    _simulate_turns(
        llm=llm,
        persona_snap=persona_snap,
        user_turns=user_turns,
        dialogue_history=[],
    )


if __name__ == "__main__":
    main()
