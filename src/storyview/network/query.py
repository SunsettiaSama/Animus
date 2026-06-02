from __future__ import annotations

from storyview.network.render import build_inject_text
from storyview.types import SceneCandidate, SceneEdge, SceneLocateResult, SceneUnit


def _tokenize(query: str) -> list[str]:
    normalized = query.replace("，", " ").replace(",", " ").replace("。", " ")
    return [part.strip() for part in normalized.split() if part.strip()]


def _score_scene(scene: SceneUnit, tokens: list[str]) -> int:
    if not tokens:
        return 0
    haystack = " ".join(
        [
            scene.name,
            scene.narrative,
            " ".join(scene.tags),
        ]
    ).lower()
    score = 0
    for token in tokens:
        needle = token.lower()
        if needle in scene.name.lower():
            score += 4
        if needle in haystack:
            score += 2
    return score


def _score_edge(edge: SceneEdge, tokens: list[str]) -> int:
    if not tokens:
        return 0
    text = edge.transition_text.lower()
    score = 0
    for token in tokens:
        if token.lower() in text:
            score += 3
    return score


class SceneQueryEngine:
    def locate(
        self,
        world_id: str,
        query: str,
        *,
        scenes: list[SceneUnit],
        edges: list[SceneEdge],
        current_scene_id: str | None = None,
    ) -> SceneLocateResult:
        _ = world_id
        tokens = _tokenize(query)
        scene_by_id = {scene.id: scene for scene in scenes}

        if current_scene_id and not tokens:
            current = scene_by_id.get(current_scene_id)
            if current is not None:
                inject = build_inject_text(current)
                return SceneLocateResult(
                    scene=current,
                    inject_text=inject,
                    matched_by="current",
                )

        if current_scene_id and tokens:
            outgoing = [edge for edge in edges if edge.from_scene_id == current_scene_id]
            best_edge: SceneEdge | None = None
            best_edge_score = 0
            for edge in outgoing:
                edge_score = _score_edge(edge, tokens)
                if edge_score > best_edge_score:
                    best_edge_score = edge_score
                    best_edge = edge
            if best_edge is not None and best_edge_score > 0:
                target = scene_by_id.get(best_edge.to_scene_id)
                if target is not None:
                    inject = build_inject_text(
                        target,
                        transition_text=best_edge.transition_text,
                    )
                    return SceneLocateResult(
                        scene=target,
                        transition_text=best_edge.transition_text,
                        inject_text=inject,
                        matched_by="edge",
                    )

        if current_scene_id and not any(_score_scene(scene_by_id[sid], tokens) for sid in [current_scene_id] if sid in scene_by_id):
            current = scene_by_id.get(current_scene_id)
            if current is not None and not tokens:
                inject = build_inject_text(current)
                return SceneLocateResult(
                    scene=current,
                    inject_text=inject,
                    matched_by="current",
                )

        best_scene: SceneUnit | None = None
        best_score = 0
        for scene in scenes:
            score = _score_scene(scene, tokens)
            if score > best_score:
                best_score = score
                best_scene = scene

        if best_scene is not None and best_score > 0:
            matched_by = "scene_name" if any(t.lower() in best_scene.name.lower() for t in tokens) else "scene_narrative"
            inject = build_inject_text(best_scene)
            return SceneLocateResult(
                scene=best_scene,
                inject_text=inject,
                matched_by=matched_by,
            )

        if current_scene_id:
            current = scene_by_id.get(current_scene_id)
            if current is not None:
                inject = build_inject_text(current)
                return SceneLocateResult(
                    scene=current,
                    inject_text=inject,
                    matched_by="current",
                )

        return SceneLocateResult(scene=None, inject_text="", matched_by="")

    def locate_candidates(
        self,
        world_id: str,
        query: str,
        *,
        scenes: list[SceneUnit],
        edges: list[SceneEdge],
        current_scene_id: str | None = None,
        limit: int = 3,
    ) -> list[SceneCandidate]:
        _ = world_id
        if limit < 1:
            return []
        tokens = _tokenize(query)
        scene_by_id = {scene.id: scene for scene in scenes}
        current = scene_by_id.get(current_scene_id) if current_scene_id else None
        ranked: list[SceneCandidate] = []

        if current_scene_id and tokens:
            for edge in edges:
                if edge.from_scene_id != current_scene_id:
                    continue
                edge_score = _score_edge(edge, tokens)
                if edge_score <= 0:
                    continue
                target = scene_by_id.get(edge.to_scene_id)
                if target is None:
                    continue
                ranked.append(
                    SceneCandidate(
                        scene=target,
                        transition_text=edge.transition_text,
                        matched_by="edge",
                        score=edge_score + edge.weight,
                    )
                )

        for scene in scenes:
            score = _score_scene(scene, tokens)
            if score <= 0:
                continue
            matched_by = (
                "scene_name"
                if any(token.lower() in scene.name.lower() for token in tokens)
                else "scene_narrative"
            )
            ranked.append(
                SceneCandidate(
                    scene=scene,
                    matched_by=matched_by,
                    score=score,
                )
            )

        best: dict[str, SceneCandidate] = {}
        for candidate in ranked:
            scene_id = candidate.scene.id
            previous = best.get(scene_id)
            if previous is None or candidate.score > previous.score:
                best[scene_id] = candidate

        sorted_candidates = sorted(best.values(), key=lambda item: item.score, reverse=True)
        if not sorted_candidates:
            if current is not None:
                sorted_candidates = [
                    SceneCandidate(scene=current, matched_by="current", score=0)
                ]
        return sorted_candidates[:limit]
