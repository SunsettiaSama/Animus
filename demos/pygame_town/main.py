"""Minimal Stardew-like town demo over Speak WS (channel pygame-town).

Deps (demo only): pygame, websocket-client
Run (Soul Ready first):
  set PYTHONPATH=src
  python demos/pygame_town/main.py
  python demos/pygame_town/main.py --smoke
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import pygame

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
DEMO_DIR = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from client.speak_ws import SpeakWsClient
from day import DayClock
from presenter import SpeakPresenter
from town_director import TownDirector
from world import CABIN, COLORS, FENCE, PLAZA, World

LOG_PATH = ROOT / ".react" / "demos" / "pygame_town" / "plaza_chat.jsonl"
HELP = "WASD move | E crop | Enter talk | N next phase | Esc quit"


def _ack_proactive(client: SpeakWsClient, msg: dict) -> None:
    did = str(msg.get("delivery_id") or "").strip()
    meta = msg.get("meta")
    if not did and isinstance(meta, dict):
        did = str(meta.get("delivery_id") or "").strip()
    if did:
        client.acknowledge_proactive(did)


def _draw_bubble(screen, font, text: str, x: float, y: float) -> None:
    if not text:
        return
    lines = []
    chunk = text
    while len(chunk) > 18:
        lines.append(chunk[:18])
        chunk = chunk[18:]
    lines.append(chunk)
    lines = lines[:4]
    pads = [font.render(line, True, (20, 20, 20)) for line in lines]
    w = max(p.get_width() for p in pads) + 12
    h = sum(p.get_height() for p in pads) + 10
    bx = int(x - w / 2)
    by = int(y - h - 18)
    pygame.draw.rect(screen, (250, 245, 230), (bx, by, w, h), border_radius=6)
    pygame.draw.rect(screen, (60, 50, 40), (bx, by, w, h), 1, border_radius=6)
    yy = by + 5
    for p in pads:
        screen.blit(p, (bx + 6, yy))
        yy += p.get_height()


def _draw_world(screen, world: World, font, hud_font, day: DayClock, status: str, draft: str) -> None:
    tile = world.tile
    for y, row in enumerate(world.grid):
        for x, kind in enumerate(row):
            color = COLORS.get(kind, (0, 0, 0))
            pygame.draw.rect(screen, color, (x * tile, y * tile, tile, tile))
            if kind == CABIN:
                pygame.draw.rect(screen, (70, 40, 30), (x * tile + 4, y * tile + 4, tile - 8, tile - 8))
            if kind == FENCE:
                pygame.draw.line(
                    screen,
                    (50, 40, 30),
                    (x * tile, y * tile + tile // 2),
                    (x * tile + tile, y * tile + tile // 2),
                    3,
                )
            if kind == PLAZA:
                pygame.draw.circle(
                    screen,
                    (150, 130, 100),
                    (x * tile + tile // 2, y * tile + tile // 2),
                    3,
                )

    for crop in world.crops:
        cx = crop.tile_x * tile + tile // 2
        cy = crop.tile_y * tile + tile // 2
        if crop.harvested:
            continue
        if crop.ready:
            pygame.draw.circle(screen, (60, 180, 70), (cx, cy), 8)
        elif crop.watered:
            pygame.draw.circle(screen, (90, 140, 200), (cx, cy), 6)
        else:
            pygame.draw.circle(screen, (150, 120, 60), (cx, cy), 5)

    for agent in world.agents:
        pygame.draw.circle(screen, agent.color, (int(agent.x), int(agent.y)), 12)
        if agent.talking:
            pygame.draw.circle(screen, (255, 255, 255), (int(agent.x), int(agent.y)), 14, 2)
        label = hud_font.render(agent.name, True, (255, 255, 255))
        screen.blit(label, (int(agent.x) - label.get_width() // 2, int(agent.y) + 14))
        _draw_bubble(screen, font, agent.bubble, agent.x, agent.y)

    pygame.draw.rect(
        screen,
        (240, 220, 120),
        (int(world.player_x) - 10, int(world.player_y) - 10, 20, 20),
    )
    pygame.draw.rect(
        screen,
        (40, 40, 20),
        (int(world.player_x) - 10, int(world.player_y) - 10, 20, 20),
        2,
    )

    hud = (
        f"Day {day.day} {day.phase} | harvest {world.harvest_count} | {status} | {HELP}"
    )
    screen.blit(hud_font.render(hud, True, (255, 255, 255)), (8, 6))
    if draft is not None:
        bar = hud_font.render(f"> {draft}", True, (255, 240, 180))
        screen.blit(bar, (8, world.pixel_size()[1] - 28))


def run_smoke() -> None:
    """Headless-ish: crop interact + one plaza Speak turn + JSONL line."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    world = World()
    crop = world.nearest_crop(
        (world.crops[0].tile_x + 0.5) * world.tile,
        (world.crops[0].tile_y + 0.5) * world.tile,
    )
    if crop is None:
        raise RuntimeError("smoke: no crop")
    world.player_x = (crop.tile_x + 0.5) * world.tile
    world.player_y = (crop.tile_y + 0.5) * world.tile
    if world.interact_crop() != "watered":
        raise RuntimeError("smoke: water failed")
    if world.interact_crop() != "harvested":
        raise RuntimeError("smoke: harvest failed")

    day = DayClock()
    day.phase_index = 1  # noon -> he+mai on plaza
    day.apply_schedule(world.agents)
    world.sync_agent_targets()
    for agent in world.agents:
        agent.x, agent.y = agent.target_xy

    presenter = SpeakPresenter()
    before = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
    director = TownDirector(presenter, LOG_PATH, max_rounds=2, cooldown_s=1.0)
    client = SpeakWsClient(
        session_id=f"pygame-town-smoke-{uuid.uuid4().hex[:8]}",
        channel_id="pygame-town",
    )
    client.connect(timeout_s=20.0)
    # drain enter-greeting / proactive noise before plaza turns
    settle_until = time.monotonic() + 3.0
    while time.monotonic() < settle_until:
        for msg in client.poll():
            _ack_proactive(client, msg)
        time.sleep(0.05)

    plaza = world.agents_on_plaza()
    if len(plaza) < 2:
        raise RuntimeError(f"smoke: plaza agents={ [a.name for a in plaza] }")
    if not director.maybe_start(plaza, client.send_user_message):
        raise RuntimeError("smoke: director failed to start")

    deadline = time.monotonic() + 180.0
    finishes = 0
    while time.monotonic() < deadline and (director.active or finishes < 1):
        for msg in client.poll():
            _ack_proactive(client, msg)
            mtype = str(msg.get("type"))
            if mtype == "error":
                print(f"smoke speak error: {msg.get('message')}")
            was_waiting = director._waiting_finish
            was_round = director.round_i
            director.on_message(msg, client.send_user_message)
            if mtype == "turn_finish" and was_waiting and not bool(msg.get("server_initiated")):
                finishes += 1
                print(
                    f"smoke turn_finish round={was_round} "
                    f"answer={str(msg.get('answer', '') or presenter.last_answer)[:80]!r}"
                )
        if finishes >= 2 and not director.active:
            break
        time.sleep(0.05)

    client.close()
    pygame.quit()
    after = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
    if finishes < 1 or len(after) <= len(before):
        raise RuntimeError(
            f"smoke failed finishes={finishes} log_grew={len(after) > len(before)} path={LOG_PATH}"
        )
    print(f"smoke ok finishes={finishes} log={LOG_PATH}")


def main() -> None:
    if "--smoke" in sys.argv:
        run_smoke()
        return

    os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
    pygame.init()
    pygame.display.set_caption("pygame_town — Speak plaza demo")
    world = World()
    w, h = world.pixel_size()
    screen = pygame.display.set_mode((w, h + 36))
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("microsoftyahei,simhei,consolas", 16)
    hud_font = pygame.font.SysFont("microsoftyahei,simhei,consolas", 14)

    day = DayClock()
    day.apply_schedule(world.agents)
    world.sync_agent_targets()

    presenter = SpeakPresenter()
    director = TownDirector(presenter, LOG_PATH, max_rounds=4, cooldown_s=10.0)

    client = SpeakWsClient(
        session_id=f"pygame-town-{uuid.uuid4().hex[:10]}",
        channel_id="pygame-town",
    )
    status = "connecting"
    client.connect(timeout_s=20.0)
    status = "ready"

    typing = False
    draft = ""
    player_focus = None
    player_await_finish = False
    running = True

    while running:
        dt = clock.tick(60) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if typing:
                        typing = False
                        draft = ""
                    else:
                        running = False
                elif typing:
                    if event.key == pygame.K_RETURN:
                        text = draft.strip()
                        draft = ""
                        typing = False
                        if text and player_focus is not None and not director.active:
                            presenter.bind(player_focus)
                            player_await_finish = client.send_user_message(text)
                            status = f"talk->{player_focus.name}"
                    elif event.key == pygame.K_BACKSPACE:
                        draft = draft[:-1]
                    else:
                        ch = event.unicode
                        if ch and ch.isprintable() and len(draft) < 80:
                            draft += ch
                else:
                    if event.key == pygame.K_n:
                        phase = day.advance()
                        day.apply_schedule(world.agents)
                        world.sync_agent_targets()
                        status = f"phase->{phase}"
                    elif event.key == pygame.K_e:
                        result = world.interact_crop()
                        if result:
                            status = result
                    elif event.key == pygame.K_RETURN:
                        near = world.nearest_agent(world.player_x, world.player_y)
                        if near is not None and not director.active and not presenter.busy:
                            player_focus = near
                            typing = True
                            draft = ""
                            status = f"input->{near.name}"

        if not typing:
            keys = pygame.key.get_pressed()
            world.update_player(dt, keys)

        for agent in world.agents:
            agent.update(dt)

        for msg in client.poll():
            mtype = str(msg.get("type", ""))
            if mtype == "error":
                status = f"error:{msg.get('message')}"
            _ack_proactive(client, msg)

            if director.active:
                director.on_message(msg, client.send_user_message)
            elif player_await_finish:
                presenter.on_message(msg)
                if mtype == "turn_finish":
                    player_await_finish = False
                    status = "player_done"
            elif mtype in ("turn_start", "speak_event", "turn_finish"):
                plaza = world.agents_on_plaza()
                if plaza and presenter.focus is None:
                    presenter.bind(plaza[0])
                presenter.on_message(msg)

        if (
            not director.active
            and not player_await_finish
            and not typing
            and not presenter.busy
        ):
            plaza = world.agents_on_plaza()
            if director.maybe_start(plaza, client.send_user_message):
                status = "plaza_chat"

        screen.fill((30, 40, 30))
        _draw_world(
            screen,
            world,
            font,
            hud_font,
            day,
            status,
            draft if typing else "",
        )
        pygame.display.flip()

    client.close()
    pygame.quit()


if __name__ == "__main__":
    main()
