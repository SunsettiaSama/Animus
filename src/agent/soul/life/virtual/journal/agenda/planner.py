from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM

from ..contracts import LandmarkAgendaDraftResult
from .cue import build_landmark_agenda_public_cue
from .item import LandmarkAgenda, LandmarkAgendaRevision, LandmarkAgendaStatus
from .prompts import _DECIDE_SYSTEM, _INIT_SYSTEM, _REVISE_SYSTEM
from .tools import AgendaToolBundle
from storyview.types import SceneCard, SceneGroundingTraceEntry

_MAX_ROUNDS = 8
_DUPLICATE_SENTENCE_RATIO = 0.78
_DUPLICATE_COMMON_BLOCK = 14
_DUPLICATE_COMMON_COVERAGE = 0.55


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"planner expected JSON object, got: {text[:200]}")
    payload = json.loads(m.group(0))
    if not isinstance(payload, dict):
        raise ValueError("planner expected JSON object")
    return payload


def _split_sentences(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[。！？!?])\s*", cleaned)
    return [part.strip() for part in parts if part.strip()]


def _join_sentences(sentences: list[str]) -> str:
    return "".join(sentence for sentence in sentences if sentence.strip())


def _sentence_fingerprint(sentence: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:（）()【】\[\]\"'“”‘’]+", "", sentence)


def _is_duplicate_sentence(candidate: str, existing: str) -> bool:
    left = _sentence_fingerprint(candidate)
    right = _sentence_fingerprint(existing)
    if not left or not right:
        return False
    if left == right:
        return True
    shorter = min(len(left), len(right))
    if shorter < 12:
        return False
    matcher = SequenceMatcher(None, left, right)
    ratio = matcher.ratio()
    if ratio >= _DUPLICATE_SENTENCE_RATIO:
        return True
    blocks = matcher.get_matching_blocks()
    longest = max((block.size for block in blocks), default=0)
    common = sum(block.size for block in blocks)
    coverage = common / shorter
    return (
        longest >= _DUPLICATE_COMMON_BLOCK
        and coverage >= _DUPLICATE_COMMON_COVERAGE
    )


def _dedupe_sentences(sentences: list[str]) -> list[str]:
    kept: list[str] = []
    for sentence in sentences:
        text = sentence.strip()
        if not text:
            continue
        if any(_is_duplicate_sentence(text, existing) for existing in kept):
            continue
        kept.append(text)
    return kept


@dataclass
class _DraftState:
    title: str = ""
    summary: str = ""
    sentences: list[str] = field(default_factory=list)
    scene_hint: str = ""
    scene_id: str = ""
    scene_name: str = ""
    scene_cards: list[SceneCard] = field(default_factory=list)
    grounding_trace: list[SceneGroundingTraceEntry] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    journal_refs: list[str] = field(default_factory=list)

    def normalize(self) -> None:
        self.sentences = _dedupe_sentences(self.sentences)

    @classmethod
    def from_payload(cls, payload: dict) -> _DraftState:
        full_context = str(payload.get("full_context", "")).strip()
        state = cls(
            title=str(payload.get("title", "")).strip(),
            summary=str(payload.get("summary", "")).strip(),
            sentences=_split_sentences(full_context),
            scene_hint=str(payload.get("scene_hint", "")).strip(),
            steps=[str(item).strip() for item in payload.get("steps", []) if str(item).strip()],
            success_criteria=[
                str(item).strip()
                for item in payload.get("success_criteria", [])
                if str(item).strip()
            ],
            constraints=[
                str(item).strip() for item in payload.get("constraints", []) if str(item).strip()
            ],
        )
        state.normalize()
        return state

    def to_agenda(
        self,
        *,
        target_date: str,
        revision_trace: list[LandmarkAgendaRevision],
    ) -> LandmarkAgenda:
        self.normalize()
        agenda = LandmarkAgenda.new_draft(
            target_date=target_date,
            title=self.title,
            summary=self.summary,
            full_context=_join_sentences(self.sentences),
        )
        agenda.scene_hint = self.scene_hint
        agenda.scene_id = self.scene_id
        agenda.scene_name = self.scene_name
        agenda.scene_cards = list(self.scene_cards)
        agenda.grounding_trace = list(self.grounding_trace)
        agenda.steps = list(self.steps)
        agenda.success_criteria = list(self.success_criteria)
        agenda.constraints = list(self.constraints)
        agenda.memory_refs = list(self.memory_refs)
        agenda.journal_refs = list(self.journal_refs)
        agenda.revision_trace = list(revision_trace)
        agenda.mark_finalized()
        return agenda

    def is_converged(self) -> bool:
        self.normalize()
        if not self.title.strip() or not self.summary.strip():
            return False
        if len(_join_sentences(self.sentences)) < 80:
            return False
        if not self.scene_id.strip():
            return False
        if not self.scene_hint.strip():
            return False
        if len(self.steps) < 3:
            return False
        if not self.success_criteria:
            return False
        if len(self.scene_cards) < 3:
            return False
        card_titles = [card.title.strip() for card in self.scene_cards if card.title.strip()]
        if not card_titles:
            return False
        step_blob = " ".join(self.steps)
        if not any(title in step_blob for title in card_titles):
            return False
        return True

    def grounding_cue(self) -> str:
        return " ".join(
            part.strip()
            for part in (
                self.title,
                self.summary,
                _join_sentences(self.sentences),
                self.scene_hint,
            )
            if part.strip()
        )

    def apply_grounding(self, result) -> None:
        if result.blocked:
            raise RuntimeError(f"scene grounding blocked: {result.blocked_reason}")
        if len(result.cards) < 3:
            raise RuntimeError(f"scene grounding returned insufficient cards: {result.scene_id}")
        self.scene_id = result.scene_id.strip()
        self.scene_name = result.scene_name.strip()
        self.scene_cards = list(result.cards)
        self.grounding_trace = list(result.trace)
        if result.scene_name.strip():
            self.scene_hint = result.scene_name.strip()
        if not any(title in " ".join(self.steps) for title in (card.title for card in self.scene_cards)):
            self.steps = [
                f"在{card.title}完成一项与议程相关的可观察动作"
                for card in self.scene_cards[:3]
            ]


class LandmarkAgendaPlanner:
    def __init__(
        self,
        llm: BaseLLM,
        tools: AgendaToolBundle,
        *,
        max_rounds: int = _MAX_ROUNDS,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._max_rounds = max(1, max_rounds)

    def compose_tomorrow_agenda(
        self,
        *,
        profile_narrative: str,
        world_background: str = "",
        target_date: str | None = None,
        recent_landmark_intents: list[str] | None = None,
    ) -> LandmarkAgendaDraftResult:
        tomorrow = target_date or (date.today() + timedelta(days=1)).isoformat()
        state = self._init_draft(
            profile_narrative=profile_narrative,
            world_background=world_background,
            target_date=tomorrow,
            recent_landmark_intents=recent_landmark_intents or [],
        )
        grounding = self._tools.ground_scene(state.grounding_cue())
        state.apply_grounding(grounding)
        trace: list[LandmarkAgendaRevision] = [
            LandmarkAgendaRevision(
                round=0,
                thought="绑定 storyview scene",
                action="ground_scene",
                observation=self._tools.scene_grounding_context(grounding),
                patch_summary=f"scene_id={state.scene_id}",
            )
        ]
        for round_idx in range(1, self._max_rounds + 1):
            decision = self._decide_action(state, trace, round_idx)
            action = str(decision.get("action", "")).strip()
            thought = str(decision.get("thought", "")).strip()
            if action == "finish":
                if not state.is_converged():
                    observation = (
                        "尚未满足收敛条件：需要 scene_id、更具体的 full_context、"
                        "scene_hint、至少 3 条引用 scene cards 的 steps 与 success_criteria。"
                    )
                    trace.append(
                        LandmarkAgendaRevision(
                            round=round_idx,
                            thought=thought,
                            action=action,
                            observation=observation,
                            patch_summary="finish 被拒绝",
                        )
                    )
                    continue
                trace.append(
                    LandmarkAgendaRevision(
                        round=round_idx,
                        thought=thought,
                        action=action,
                        observation="议程已收敛。",
                        patch_summary="finish",
                    )
                )
                break

            observation = self._run_tool(action, str(decision.get("query", "")).strip())
            revision = self._revise(state, observation, trace, round_idx, last_thought=thought)
            trace.append(revision)
            if round_idx == self._max_rounds and not state.is_converged():
                break

        agenda = state.to_agenda(target_date=tomorrow, revision_trace=trace)
        return LandmarkAgendaDraftResult(agenda=agenda, revision_trace=trace)

    def preview_public_cue(self, agenda: LandmarkAgenda) -> str:
        return build_landmark_agenda_public_cue(agenda)

    def _init_draft(
        self,
        *,
        profile_narrative: str,
        world_background: str,
        target_date: str,
        recent_landmark_intents: list[str],
    ) -> _DraftState:
        recent_block = "\n".join(f"- {line}" for line in recent_landmark_intents) or "（无）"
        prompt = (
            f"【身份与状态】\n{profile_narrative or '（暂无）'}\n\n"
            f"【世界观背景】\n{world_background or '（暂无）'}\n\n"
            f"【目标日期】\n{target_date}\n\n"
            f"【近期已完成地标意图（勿重复）】\n{recent_block}\n\n"
            "请起草明天的一个粗粒度 LandmarkAgenda。"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_INIT_SYSTEM), HumanMessage(content=prompt)]
        )
        payload = _extract_json(raw)
        return _DraftState.from_payload(payload)

    def _decide_action(
        self,
        state: _DraftState,
        trace: list[LandmarkAgendaRevision],
        round_idx: int,
    ) -> dict:
        history = "\n".join(
            f"R{item.round}: {item.action} -> {item.patch_summary or item.observation[:120]}"
            for item in trace[-4:]
        ) or "（首轮）"
        prompt = (
            f"【当前议程草案】\n"
            f"title={state.title}\n"
            f"summary={state.summary}\n"
            f"full_context={_join_sentences(state.sentences)}\n"
            f"scene_id={state.scene_id}\n"
            f"scene_name={state.scene_name}\n"
            f"scene_hint={state.scene_hint}\n"
            f"scene_cards={[card.title for card in state.scene_cards]}\n"
            f"steps={state.steps}\n"
            f"success_criteria={state.success_criteria}\n"
            f"constraints={state.constraints}\n\n"
            f"【修订历史】\n{history}\n\n"
            f"【当前轮次】{round_idx}/{self._max_rounds}\n"
            "请选择下一步动作。只能围绕已绑定 scene/cards 修订，不得发明新地点。"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_DECIDE_SYSTEM), HumanMessage(content=prompt)]
        )
        return _extract_json(raw)

    def _run_tool(self, action: str, query: str) -> str:
        if action == "recall_memory":
            lines = self._tools.recall_memory(query or "明天行动议程")
            if not lines:
                return "（未检索到相关记忆）"
            return "\n".join(f"- {line}" for line in lines)
        if action == "inspect_journal":
            return self._tools.inspect_journal()
        if action == "inspect_chronicle":
            return self._tools.inspect_chronicle()
        raise ValueError(f"unknown agenda planner action: {action}")

    def _revise(
        self,
        state: _DraftState,
        observation: str,
        trace: list[LandmarkAgendaRevision],
        round_idx: int,
        *,
        last_thought: str,
    ) -> LandmarkAgendaRevision:
        prompt = (
            f"【当前议程草案】\n"
            f"title={state.title}\n"
            f"summary={state.summary}\n"
            f"full_context={_join_sentences(state.sentences)}\n"
            f"scene_hint={state.scene_hint}\n"
            f"steps={state.steps}\n"
            f"success_criteria={state.success_criteria}\n"
            f"constraints={state.constraints}\n\n"
            f"【工具观察】\n{observation}\n\n"
            "请输出 patch 修订当前议程。"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_REVISE_SYSTEM), HumanMessage(content=prompt)]
        )
        payload = _extract_json(raw)
        patches = payload.get("patches", [])
        patch_summary = str(payload.get("patch_summary", "")).strip()
        thought = str(payload.get("thought", "")).strip() or last_thought
        if isinstance(patches, list):
            for patch in patches:
                if isinstance(patch, dict):
                    self._apply_patch(state, patch)
        state.normalize()
        return LandmarkAgendaRevision(
            round=round_idx,
            thought=thought,
            action="revise",
            observation=observation,
            patch_summary=patch_summary or f"applied {len(patches)} patches",
        )

    def _apply_patch(self, state: _DraftState, patch: dict) -> None:
        op = str(patch.get("op", "")).strip()
        if op == "set_field":
            field = str(patch.get("field", "")).strip()
            text = str(patch.get("text", "")).strip()
            if field == "title":
                state.title = text
            elif field == "summary":
                state.summary = text
            elif field == "scene_hint":
                state.scene_hint = text
            return
        if op == "add_sentence":
            text = str(patch.get("text", "")).strip()
            if text:
                state.sentences.append(text)
            return
        if op == "remove_sentence":
            index = int(patch.get("index", -1))
            if 0 <= index < len(state.sentences):
                state.sentences.pop(index)
            return
        if op == "replace_sentence":
            index = int(patch.get("index", -1))
            text = str(patch.get("text", "")).strip()
            if 0 <= index < len(state.sentences) and text:
                state.sentences[index] = text
            return
        if op == "set_list":
            field = str(patch.get("field", "")).strip()
            items = [
                str(item).strip() for item in patch.get("items", []) if str(item).strip()
            ]
            if field == "steps":
                state.steps = items
            elif field == "success_criteria":
                state.success_criteria = items
            elif field == "constraints":
                state.constraints = items
            return
        if op == "append_ref":
            field = str(patch.get("field", "")).strip()
            text = str(patch.get("text", "")).strip()
            if not text:
                return
            if field == "memory_refs":
                state.memory_refs.append(text)
            elif field == "journal_refs":
                state.journal_refs.append(text)
