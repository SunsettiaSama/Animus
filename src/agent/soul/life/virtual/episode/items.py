from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.life.experience.domain.episode import (
    EpisodeItemType,
    LandmarkEpisode,
    TypedMemoryItemDraft,
)
from agent.soul.life.virtual.episode.builder import (
    _stable_item_id,
    build_episode_summary_item,
    heuristic_lessons,
)


_EXTRACT_SYSTEM = """\
你是记忆抽取系统。从一次 landmark 体验 episode 中抽取 typed memory item。
类型只能是：observation、subjective_reaction、lesson_or_hypothesis。
- observation：外部可观察事实，不含主观推断
- subjective_reaction：身体感受、情绪、判断或归因
- lesson_or_hypothesis：由经历沉淀的经验或未证实假设（未证实须 is_hypothesis=true）

每条 item 输出 JSON 数组元素：
{"item_type":"...", "text":"...", "focus":"<=12字", "step_index":1, "is_hypothesis":false}
只输出 JSON 数组，不要解释。"""


def extract_typed_memory_items(
    episode: LandmarkEpisode,
    *,
    llm=None,
) -> list[TypedMemoryItemDraft]:
    if llm is not None:
        llm_items = _llm_extract(episode, llm)
        if llm_items:
            return _with_core_items(episode, llm_items)
    return _with_core_items(episode, _heuristic_extract(episode))


def _with_core_items(
    episode: LandmarkEpisode,
    items: list[TypedMemoryItemDraft],
) -> list[TypedMemoryItemDraft]:
    core: list[TypedMemoryItemDraft] = [build_episode_summary_item(episode)]
    for step in episode.arc_steps:
        core.append(
            TypedMemoryItemDraft(
                item_id=_stable_item_id(
                    episode.episode_id,
                    "arc_step",
                    str(step.step_index),
                    step.objective_result[:60],
                ),
                item_type=EpisodeItemType.arc_step,
                text=step.objective_result[:240] or step.soul_answer[:240],
                focus=f"第{step.step_index}拍",
                step_index=step.step_index,
                scene_id=step.scene_id or episode.scene_id,
                source_arc_step=step.step_index,
            )
        )
    seen = {item.item_id for item in core}
    for item in items:
        if item.item_id in seen:
            continue
        seen.add(item.item_id)
        core.append(item)
    heuristic = heuristic_lessons(episode)
    existing_lesson_steps = {
        item.source_arc_step or item.step_index
        for item in core
        if item.item_type == EpisodeItemType.lesson_or_hypothesis
    }
    for step_index, lesson, is_hypothesis in heuristic:
        if step_index in existing_lesson_steps:
            continue
        item_id = _stable_item_id(episode.episode_id, "lesson", str(step_index), lesson[:60])
        if item_id in seen:
            continue
        seen.add(item_id)
        core.append(
            TypedMemoryItemDraft(
                item_id=item_id,
                item_type=EpisodeItemType.lesson_or_hypothesis,
                text=lesson,
                focus="待验证" if is_hypothesis else "经验",
                scene_id=episode.scene_id,
                is_hypothesis=is_hypothesis,
                step_index=step_index,
                source_arc_step=step_index,
            )
        )
    episode.agent_lessons_or_questions = [
        item.text
        for item in core
        if item.item_type == EpisodeItemType.lesson_or_hypothesis
    ][:4]
    return core


def _heuristic_extract(episode: LandmarkEpisode) -> list[TypedMemoryItemDraft]:
    items: list[TypedMemoryItemDraft] = []
    for step in episode.arc_steps:
        objective = step.objective_result.strip()
        if objective:
            items.append(
                TypedMemoryItemDraft(
                    item_id=_stable_item_id(
                        episode.episode_id,
                        "observation",
                        str(step.step_index),
                        objective[:60],
                    ),
                    item_type=EpisodeItemType.observation,
                    text=objective[:240],
                    focus=f"发现{step.step_index}",
                    step_index=step.step_index,
                    scene_id=step.scene_id or episode.scene_id,
                    source_arc_step=step.step_index,
                )
            )
        reaction = step.subjective_reaction.strip()
        if reaction:
            items.append(
                TypedMemoryItemDraft(
                    item_id=_stable_item_id(
                        episode.episode_id,
                        "subjective_reaction",
                        str(step.step_index),
                        reaction[:60],
                    ),
                    item_type=EpisodeItemType.subjective_reaction,
                    text=reaction[:240],
                    focus="感受",
                    step_index=step.step_index,
                    scene_id=step.scene_id or episode.scene_id,
                    source_arc_step=step.step_index,
                )
            )
    if episode.subjective_journal.strip():
        items.append(
            TypedMemoryItemDraft(
                item_id=_stable_item_id(
                    episode.episode_id,
                    "subjective_reaction",
                    "journal",
                    episode.subjective_journal[:60],
                ),
                item_type=EpisodeItemType.subjective_reaction,
                text=episode.subjective_journal[:240],
                focus="主观余波",
                scene_id=episode.scene_id,
            )
        )
    return items


def _llm_extract(episode: LandmarkEpisode, llm) -> list[TypedMemoryItemDraft]:
    step_lines = []
    for step in episode.arc_steps:
        step_lines.append(
            f"{step.step_index}. 客观={step.objective_result} / 主观={step.subjective_reaction}"
        )
    prompt = (
        f"意图：{episode.intention}\n"
        f"场景：{episode.scene_name or episode.scene_id}\n"
        f"弧摘要：{episode.objective_summary}\n"
        f"各拍：\n" + "\n".join(step_lines)
    )
    raw = llm.generate_messages(
        [SystemMessage(content=_EXTRACT_SYSTEM), HumanMessage(content=prompt)]
    ).strip()
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return []
    payload = json.loads(match.group(0))
    items: list[TypedMemoryItemDraft] = []
    for entry in payload:
        item_type_raw = str(entry.get("item_type", "")).strip()
        if item_type_raw not in {
            EpisodeItemType.observation.value,
            EpisodeItemType.subjective_reaction.value,
            EpisodeItemType.lesson_or_hypothesis.value,
        }:
            continue
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        step_index = int(entry.get("step_index", 0) or 0)
        item_type = EpisodeItemType(item_type_raw)
        items.append(
            TypedMemoryItemDraft(
                item_id=_stable_item_id(
                    episode.episode_id,
                    item_type.value,
                    str(step_index),
                    text[:60],
                ),
                item_type=item_type,
                text=text[:240],
                focus=str(entry.get("focus", "")).strip()[:12] or item_type.value[:12],
                step_index=step_index,
                scene_id=episode.scene_id,
                source_arc_step=step_index,
                is_hypothesis=bool(entry.get("is_hypothesis", False)),
            )
        )
    return items
