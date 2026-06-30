from __future__ import annotations

from typing import Protocol

from storyview.types import SceneUnit


class StorySceneBootstrapTarget(Protocol):
    def list_scenes(self, world_id: str) -> list[SceneUnit]: ...

    def upsert_scene(
        self,
        world_id: str,
        *,
        name: str,
        narrative: str,
        location_id: str | None = None,
        tags: list[str] | None = None,
        scene_id: str | None = None,
    ) -> str: ...

    def link_scenes(
        self,
        world_id: str,
        *,
        from_scene_id: str,
        to_scene_id: str,
        transition_text: str,
        weight: int = 10,
    ) -> str: ...

    def apply_scene(
        self,
        world_id: str,
        scene_id: str,
        *,
        transition_text: str = "",
    ) -> object: ...


def ensure_default_world_scenes(
    target: StorySceneBootstrapTarget,
    world_id: str,
) -> dict[str, str]:
    """Create a minimal traversable world only when the world has no scenes."""
    if target.list_scenes(world_id):
        return {}

    home_loc = f"{world_id}-home-loc"
    home_id = target.upsert_scene(
        world_id,
        name="营地帐篷",
        narrative="边境探险队的营地帐篷，标本箱、烘干网与半满的野外记录本堆在折叠桌旁。",
        location_id=home_loc,
        tags=["home"],
        scene_id=f"{world_id}-scene-home",
    )
    desk_id = target.upsert_scene(
        world_id,
        name="标本整理台",
        narrative="帐篷内的标本整理台，放大镜、翅脉图谱与昨夜采到的蓟类花冠样本并排摆着。",
        location_id=home_loc,
        tags=["desk"],
        scene_id=f"{world_id}-scene-desk",
    )
    overlook_id = target.upsert_scene(
        world_id,
        name="林缘观察点",
        narrative="营地外缘通向缓坡林线，雨后泥径未干，蓟类花冠与停栖痕在斜光里隐约可见。",
        location_id=f"{world_id}-yard-loc",
        tags=["yard"],
        scene_id=f"{world_id}-scene-overlook",
    )
    target.link_scenes(
        world_id,
        from_scene_id=home_id,
        to_scene_id=desk_id,
        transition_text="你回到整理台前，核对记录本与图谱。",
        weight=20,
    )
    target.link_scenes(
        world_id,
        from_scene_id=home_id,
        to_scene_id=overlook_id,
        transition_text="你系好记录本，走出帐篷，朝林缘缓坡而去。",
        weight=15,
    )
    target.apply_scene(world_id, home_id)
    return {"home": home_id, "desk": desk_id, "overlook": overlook_id}
