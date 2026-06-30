from __future__ import annotations

from storyview.fate.dice import DiceResult
from storyview.gm.resolve import ActionResolver
from storyview.gm.state_patch import parse_state_patch
from storyview.gm.story import StoryDirector
from storyview.scene import SceneComposer
from storyview.scene.network import SceneNetwork
from storyview.types import (
    ArcStartPolicy,
    GMAnswer,
    LocationSnapshotReason,
    SceneUnit,
    StoryEventKind,
)


class _FakeSceneNodes:
    def __init__(self, scenes: list[SceneUnit]) -> None:
        self._scenes = {s.id: s for s in scenes}

    def get(self, scene_id: str) -> SceneUnit | None:
        return self._scenes.get(scene_id)

    def list_by_world(self, world_id: str) -> list[SceneUnit]:
        return [s for s in self._scenes.values() if s.world_id == world_id]

    def find_by_location(self, world_id: str, location_id: str) -> SceneUnit | None:
        for scene in self.list_by_world(world_id):
            if scene.location_id == location_id:
                return scene
        return None

    def upsert(self, *args, **kwargs) -> str:
        return kwargs.get("scene_id") or "scene-new"


class _FakeSceneEdges:
    def out_edges(self, scene_id: str):
        return []

    def link(self, *args, **kwargs) -> str:
        return "edge-1"

    def list_by_world(self, world_id: str):
        return []


class _FakeRuntime:
    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}

    def ensure(self, world_id: str) -> dict:
        if world_id not in self._rows:
            self._rows[world_id] = {"current_location_id": "home-loc", "world_time": ""}
        return self._rows[world_id]

    def get(self, world_id: str) -> dict | None:
        return self._rows.get(world_id)

    def apply_patch(self, world_id: str, patch) -> None:
        row = self.ensure(world_id)
        if patch.move_to_location_id:
            row["current_location_id"] = patch.move_to_location_id

    def update_snapshot(self, world_id: str, text: str) -> None:
        self.ensure(world_id)["snapshot"] = text

    def resolve_current_scene_id(self, world_id: str) -> str | None:
        loc = self.ensure(world_id).get("current_location_id")
        if loc == "home-loc":
            return "scene-home"
        if loc == "desk-loc":
            return "scene-desk"
        return None

    def snapshot_text(self, world_id: str) -> str:
        row = self.ensure(world_id)
        return str(row.get("snapshot") or "")


class _FakeLocationSnapshots:
    def __init__(self) -> None:
        self._rows: list = []

    def append(self, snapshot) -> str:
        self._rows.append(snapshot)
        return snapshot.snapshot_id

    def last(self, world_id: str):
        rows = [row for row in self._rows if row.world_id == world_id]
        return rows[-1] if rows else None

    def list_recent(self, world_id: str, *, limit: int = 10):
        rows = [row for row in self._rows if row.world_id == world_id]
        return rows[-limit:]


class _FakeWorld:
    def ensure(self, world_id: str) -> None:
        return None

    def get(self, world_id: str) -> dict:
        return {"title": "test", "setting": "", "era": "", "tone": ""}

    def canon_rules(self, world_id: str) -> dict:
        return {"prefer": [], "forbidden": [], "must": []}


class _FakeLore:
    def retrieve_for_cue(self, world_id: str, cue: str, *, current_location_id=None):
        return [], [], []


class _FakeEvents:
    def __init__(self) -> None:
        self._events: dict[str, dict] = {}

    def create_open(self, world_id: str, *, kind: str, cue: str, scene_text: str) -> str:
        event_id = f"evt-{len(self._events) + 1}"
        self._events[event_id] = {
            "id": event_id,
            "world_id": world_id,
            "status": "open",
            "scene_text": scene_text,
        }
        return event_id

    def get(self, event_id: str) -> dict | None:
        return self._events.get(event_id)

    def mark_resolved(self, event_id: str, scene_text: str) -> None:
        if event_id in self._events:
            self._events[event_id]["status"] = "resolved"

    def append_log(self, *args, **kwargs) -> None:
        return None


class _FakeStores:
    def __init__(self) -> None:
        self.world = _FakeWorld()
        self.lore = _FakeLore()
        self.runtime = _FakeRuntime()
        self.events = _FakeEvents()
        self.scene = type(
            "SceneStore",
            (),
            {
                "nodes": _FakeSceneNodes(
                    [
                        SceneUnit(
                            id="scene-home",
                            world_id="w1",
                            name="家",
                            narrative="你在家里。",
                            location_id="home-loc",
                            tags=("home",),
                        ),
                        SceneUnit(
                            id="scene-desk",
                            world_id="w1",
                            name="窗边书桌",
                            narrative="你在窗边书桌旁。",
                            location_id="desk-loc",
                            tags=("desk",),
                        ),
                    ]
                ),
                "edges": _FakeSceneEdges(),
            },
        )()
        self.location_snapshots = _FakeLocationSnapshots()


def _director() -> StoryDirector:
    stores = _FakeStores()
    network = SceneNetwork(stores.scene.nodes, stores.scene.edges, runtime=stores.runtime)
    composer = SceneComposer(stores, llm=None, scene_network=network)
    resolver = ActionResolver(stores, llm=None)
    return StoryDirector(stores, network, composer, resolver, llm=None)


def test_parse_state_patch_ignores_extra_text_after_json() -> None:
    patch = parse_state_patch(
        "[STATE_PATCH]\n"
        '{"move_to_location_id": "home-loc", "entity_deltas": {}, "flags": {}}\n'
        "主持补充了一句非 JSON 文本。\n"
        "[/STATE_PATCH]"
    )

    assert patch.move_to_location_id == "home-loc"


def test_parse_state_patch_tolerates_python_literals_and_trailing_comma() -> None:
    patch = parse_state_patch(
        "[STATE_PATCH]\n"
        '{"move_to_location_id": None, "entity_deltas": {}, "flags": {},}\n'
        "[/STATE_PATCH]"
    )

    assert patch.move_to_location_id is None


def test_parse_state_patch_falls_back_on_malformed_entity_deltas() -> None:
    patch = parse_state_patch(
        "[STATE_PATCH]\n"
        '{"move_to_location_id": "yard-loc", "entity_deltas": {broken}, "flags": {}}\n'
        "[/STATE_PATCH]"
    )

    assert patch.move_to_location_id == "yard-loc"
    assert patch.entity_deltas == {}
    assert patch.flags == {}


def test_parse_state_patch_ignores_line_comments() -> None:
    patch = parse_state_patch(
        "[STATE_PATCH]\n"
        '{"move_to_location_id": null, "entity_deltas": {}, "flags": {}} // no move\n'
        "[/STATE_PATCH]"
    )

    assert patch.move_to_location_id is None


def test_ask_gm_returns_question_and_scene():
    director = _director()
    question = director.ask("w1", "雨后庭院", kind=StoryEventKind.landmark)
    assert question.world_id == "w1"
    assert question.scene_id == "scene-home"
    assert question.question
    assert question.choices
    assert question.open_choice is True
    assert "家" in question.question or "雨后" in question.question


def test_answer_gm_with_fixed_dice():
    director = _director()
    question = director.ask("w1", "观察灯", kind=StoryEventKind.landmark)
    answer = GMAnswer(
        question_id=question.question_id,
        text="你走近那盏灯。",
        intent="走近灯",
    )
    outcome = director.answer(
        question,
        answer,
        dice=DiceResult(value=42, tendency="平平淡淡"),
        with_dice=False,
    )
    assert outcome.dice_value == 42
    assert outcome.scene_packet.event_id
    assert outcome.resolved.resolution_text
    assert outcome.influence.salience > 0


def test_ask_gm_with_journal_public_cue():
    director = _director()
    cue = (
        "【触发来源】journal_landmark\n"
        "【journal_landmark_id】lm-1\n"
        "【公开预约意图】在雨后的庭院里观察一盏将熄未熄的灯"
    )
    question = director.ask("w1", cue, kind=StoryEventKind.landmark)
    assert question.cue == cue
    assert question.scene_id == "scene-home"
    snapshots = director.list_location_snapshots("w1", limit=5)
    assert snapshots
    assert snapshots[-1].reason == LocationSnapshotReason.arc_start.value


def test_home_start_policy_resets_to_home():
    director = _director()
    stores = director._stores
    stores.runtime.ensure("w1")["current_location_id"] = "desk-loc"
    question = director.ask(
        "w1",
        "观察灯",
        kind=StoryEventKind.landmark,
        start_policy=ArcStartPolicy.home,
    )
    assert question.scene_id == "scene-home"
    assert stores.runtime.ensure("w1")["current_location_id"] == "home-loc"


def test_answer_gm_records_location_snapshot():
    director = _director()
    question = director.ask("w1", "观察灯", kind=StoryEventKind.landmark)
    before = len(director.list_location_snapshots("w1", limit=10))
    answer = GMAnswer(
        question_id=question.question_id,
        text="你走近那盏灯。",
        intent="走近灯",
    )
    director.answer(question, answer, with_dice=False)
    after = director.list_location_snapshots("w1", limit=10)
    assert len(after) >= before + 1
    assert after[-1].reason == LocationSnapshotReason.gm_answer.value
