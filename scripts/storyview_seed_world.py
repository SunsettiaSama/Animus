#!/usr/bin/env python3
"""Seed a story world into MySQL for storyview engine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config.infra.db_config import DBConfig
from infra.db.mysql import MySQLClient
from storyview import StoryWorldview
from storyview.store.mysql import StoryStoreBundle


def seed_tavern(stores: StoryStoreBundle, world_id: str) -> None:
    wv = StoryWorldview.default()
    stores.world.ensure(
        world_id,
        title=wv.title,
        era=wv.era,
        setting=wv.setting,
        tone=wv.tone,
        canon_json={
            "prefer": list(wv.canon),
            "forbidden": ["宣称拥有真实肉体", "宏大史诗腔"],
            "must": [],
        },
    )
    stores.runtime.ensure(world_id)
    loc_bar = stores.lore.insert_location(
        world_id,
        name="小酒馆",
        description="灯光昏黄，木质吧台，空气里有麦酒与木屑味",
        atmosphere="温暖、低语、偶尔杯盏轻响",
        location_id=f"{world_id}-loc-bar",
    )
    loc_room = stores.lore.insert_location(
        world_id,
        name="吧台区",
        description="吧台后方陈列着瓶罐，调酒师在此忙碌",
        parent_id=loc_bar,
        location_id=f"{world_id}-loc-counter",
    )
    ent_bartender = stores.lore.insert_entity(
        world_id,
        name="调酒师",
        kind="npc",
        description="沉默专注，手法熟练",
        location_id=loc_room,
        state={"mixing": False},
        entity_id=f"{world_id}-ent-bartender",
    )
    ent_lamp = stores.lore.insert_entity(
        world_id,
        name="煤油灯",
        kind="object",
        description="在吧台一角轻轻摇晃，投下暖色光晕",
        location_id=loc_room,
        entity_id=f"{world_id}-ent-lamp",
    )
    stores.lore.insert_entity(
        world_id,
        name="椅子",
        kind="object",
        description="靠墙的旧木椅，座面磨得发亮",
        location_id=loc_room,
        entity_id=f"{world_id}-ent-chair",
    )
    scene_inner_id = stores.scene.nodes.upsert(
        world_id,
        name="小酒馆内室",
        narrative=(
            "你看到右手边有个茶壶，正前方是一道门，推开门，外面是鸟语花香。"
            "房间内壁炉正在静静燃烧着，发出劈里啪啦的声响。"
        ),
        location_id=loc_bar,
        tags=["酒馆", "内室", "壁炉"],
        scene_id=f"{world_id}-scene-inner",
    )
    scene_bamboo_id = stores.scene.nodes.upsert(
        world_id,
        name="青竹坞",
        narrative=(
            "你站在一片竹林边缘，风过处竹叶沙沙作响，"
            "小径向深处延伸，空气里有清冽的草香。"
        ),
        tags=["竹林", "青竹坞", "户外"],
        scene_id=f"{world_id}-scene-bamboo",
    )
    edge_id = stores.scene.edges.link(
        world_id,
        from_scene_id=scene_inner_id,
        to_scene_id=scene_bamboo_id,
        transition_text=(
            "出门后，你沿着小路走约十公里，会来到一片竹林，当地人叫它青竹坞。"
        ),
        edge_id=f"{world_id}-edge-inner-bamboo",
    )
    with stores.runtime._db.conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE story_runtime
                SET current_location_id = %s
                WHERE world_id = %s
                """,
                (loc_bar, world_id),
            )
    lore_id = stores.lore.insert_lore(
        world_id,
        category="scene",
        title="酒馆吧台",
        body=(
            "你发现了这个房间中存在一把椅子，一个煤油灯，以及一个调酒师；"
            "调酒师的调酒器正在哗啦啦的响动，让酒混合均匀。"
        ),
        tags=["酒馆", "吧台", "调酒师"],
        weight=20,
        links=[("location", loc_room), ("entity", ent_bartender), ("entity", ent_lamp)],
    )
    arc_id = stores.outline.insert_arc(world_id, "虚实日常", arc_id=f"{world_id}-arc-main")
    stores.outline.insert_beat(
        arc_id,
        seq=1,
        summary="在酒馆吧台边观察周围并整理思绪",
        required=False,
        beat_id=f"{world_id}-beat-1",
    )
    print(
        json.dumps(
            {
                "world_id": world_id,
                "lore_id": lore_id,
                "location": loc_room,
                "scene_inner_id": scene_inner_id,
                "scene_bamboo_id": scene_bamboo_id,
                "edge_id": edge_id,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed storyview world")
    parser.add_argument("--world-id", default="default")
    parser.add_argument("--preset", default="tavern", choices=["tavern"])
    args = parser.parse_args()
    cfg = DBConfig.load_default()
    if not cfg.mysql.enabled:
        raise RuntimeError("mysql.enabled 未开启，请配置 config/infra/db.yaml")
    client = MySQLClient(cfg.mysql.url)
    stores = StoryStoreBundle(client)
    stores.init_schema()
    if args.preset == "tavern":
        seed_tavern(stores, args.world_id.strip())
    else:
        raise ValueError(f"unknown preset: {args.preset}")


if __name__ == "__main__":
    main()
