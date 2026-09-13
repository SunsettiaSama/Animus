"""桌宠互动 demo — 接入 Soul/Speak 的桌面宠物。

与 pygame_town 的差别：不是"世界 demo"，而是把 soul 角色放生到桌面上——
无边框置顶透明窗口、可拖拽抛掷、自主闲逛、流式气泡对话，
沉默/等待/主动开场等主体性行为全部可视。

Run (Soul Ready first):
  set PYTHONPATH=src
  python demos/desktop_pet/main.py
  python demos/desktop_pet/main.py --char he --scale 4
  python demos/desktop_pet/main.py --smoke   # 无头自检（不连 soul）
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pygame

from bubbles import BubbleLayer
from pet import Pet, init_pet_font
from soul_link import SoulLink
from win32_window import MAGIC_KEY, make_pet_window, reassert_topmost

WIN_W, WIN_H = 460, 560
INPUT_BAR_H = 26
POLL_PULSE_S = 0.5          # typing pulse 周期
IDLE_TOPMOST_S = 30.0       # 周期性重申置顶


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="desktop pet wired to soul")
    ap.add_argument("--char", default="mai", choices=["mai", "he", "moss", "player"])
    ap.add_argument("--scale", type=int, default=3)
    ap.add_argument("--channel", default="desktop-pet")
    ap.add_argument("--session", default="live:desktop-pet")
    ap.add_argument("--smoke", action="store_true", help="headless 自检（不连 soul）")
    return ap.parse_args()


class DesktopPetApp:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        pygame.init()
        init_pet_font(13)
        self.font = pygame.font.SysFont("microsoftyahei,simhei,consolas", 15)
        self.small = pygame.font.SysFont("microsoftyahei,simhei,consolas", 12)

        self.screen = make_pet_window((WIN_W, WIN_H), title="desktop-pet")
        self.clock = pygame.time.Clock()

        # 桌宠贴着窗口底部；活动边界留出左右余量
        margin = 30
        ground_y = float(WIN_H - INPUT_BAR_H - args.scale * 6)
        self.pet = Pet(
            char=args.char,
            scale=args.scale,
            ground_y=ground_y,
            bounds=(margin, WIN_W - margin),
        )
        self.bubbles = BubbleLayer(self.font)
        self.link = (
            SoulLink(self.bubbles, self.pet, channel_id=args.channel, session_id=args.session)
            if not args.smoke
            else None
        )

        self.typing = False
        self.draft = ""
        self.status = "soul: connecting" if self.link else "smoke mode"
        self._pulse_t = 0.0
        self._topmost_t = 0.0
        self._click_candidate: tuple[float, float] | None = None
        self._click_t = 0.0
        self.running = True

    # ── 交互 ───────────────────────────────────────────────────────────────

    def _flush_send(self) -> None:
        text = self.draft.strip()
        self.draft = ""
        self.typing = False
        if not text or self.link is None:
            return
        if self.link.send_user_message(text):
            self.status = f"you: {text[:28]}"
            self.bubbles.add_local(f"我：{text}", duration=4.0)
        else:
            self.status = "soul not ready"

    def _handle_event(self, ev: pygame.event.Event) -> None:
        if ev.type == pygame.QUIT:
            self.running = False
            return
        if ev.type != pygame.KEYDOWN:
            return

        if self.typing:
            if ev.key == pygame.K_RETURN:
                self._flush_send()
            elif ev.key == pygame.K_ESCAPE:
                self.typing = False
                self.draft = ""
            elif ev.key == pygame.K_BACKSPACE:
                self.draft = self.draft[:-1]
            elif ev.unicode and ev.unicode.isprintable() and len(self.draft) < 120:
                self.draft += ev.unicode
            return

        if ev.key == pygame.K_ESCAPE:
            self.running = False          # 按住拖走不想聊了直接关；无歧义
        elif ev.key == pygame.K_RETURN:
            if self.link is not None:
                self.typing = True
                self.draft = ""

    def _handle_mouse(self, ev: pygame.event.Event) -> None:
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.pet.contains_point(*ev.pos):
                self.pet.grab(*ev.pos)
                self._click_candidate = ev.pos
                self._click_t = 0.28
        elif ev.type == pygame.MOUSEMOTION and self.pet.state == Pet.DRAG:
            self.pet.drag_to(*ev.pos)
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            if self.pet.state == Pet.DRAG:
                self.pet.release()
                # 短按未拖动 → 互动：随机小反应（真对话请按 Enter）
                if (
                    self._click_candidate
                    and abs(ev.pos[0] - self._click_candidate[0]) < 6
                    and abs(ev.pos[1] - self._click_candidate[1]) < 6
                ):
                    self.pet.squish()
                    self.pet.show_emote(__import__("random").choice(["❤", "♪", "!", "?"]), 1.4)
                self._click_candidate = None

    # ── 帧更新 ─────────────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        disturb = self.typing or any(b.typing for b in self.bubbles.bubbles)
        self.pet.update(dt, disturb=disturb)
        self.bubbles.update(dt)

        if self._click_t > 0:
            self._click_t -= dt
            if self._click_t <= 0:
                self._click_candidate = None

        if self.link is not None:
            self.link.tick()
            if self.link.is_ready():
                self.status = "soul: ready"
            # 打字 pulse：仅打字期间每 0.5s 上报草稿
            self._pulse_t += dt
            if self.typing and self._pulse_t >= POLL_PULSE_S:
                self._pulse_t = 0.0
                self.link.send_typing_pulse(self.draft)

        self._topmost_t += dt
        if self._topmost_t >= IDLE_TOPMOST_S:
            self._topmost_t = 0.0
            reassert_topmost()

    # ── 渲染 ───────────────────────────────────────────────────────────────

    def draw(self) -> None:
        self.screen.fill(MAGIC_KEY)   # 品红 = 透明
        self.pet.draw(self.screen)
        self.bubbles.draw(self.screen, self.pet.x, self.pet.y - self.pet.size)

        # 状态角标（弱化显示）
        flag = self.small.render(self.status, True, (150, 150, 150))
        self.screen.blit(flag, (8, 6))

        # 输入条
        if self.typing:
            bar_y = WIN_H - INPUT_BAR_H
            pygame.draw.rect(
                self.screen, (250, 248, 242),
                (4, bar_y, WIN_W - 8, INPUT_BAR_H - 6), border_radius=8,
            )
            pygame.draw.rect(
                self.screen, (70, 62, 54),
                (4, bar_y, WIN_W - 8, INPUT_BAR_H - 6), 1, border_radius=8,
            )
            caret = ">" if (time.monotonic() * 2) % 2 < 1 else " "
            line = self.font.render(f"{caret} {self.draft}", True, (40, 36, 32))
            self.screen.blit(line, (14, bar_y + 3))
            hint = self.small.render("Enter 发送 · Esc 取消", True, (150, 145, 138))
            self.screen.blit(hint, (WIN_W - hint.get_width() - 14, bar_y + 5))
        else:
            hint = self.small.render("Enter 说话 · 拖拽抛掷 · 点它", True, (170, 168, 164))
            self.screen.blit(hint, (WIN_W - hint.get_width() - 8, WIN_H - 20))

        pygame.display.flip()

    def run(self) -> None:
        if self.link is not None:
            self.link.start()
        while self.running:
            dt = min(0.033, self.clock.tick(60) / 1000.0)
            for ev in pygame.event.get():
                if ev.type in (pygame.KEYDOWN, pygame.QUIT):
                    self._handle_event(ev)
                elif ev.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION, pygame.MOUSEBUTTONUP):
                    self._handle_mouse(ev)
            self.update(dt)
            self.draw()
        if self.link is not None:
            self.link.close()
        pygame.quit()


def run_smoke() -> None:
    """无头自检：窗口创建/实体物理/气泡排版，不连 soul。"""
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    args = parse_args()
    app = DesktopPetApp(args)
    app.link = None

    # 物理：抓起 → 抛出 → 落地
    app.pet.grab(100, 100)
    app.pet.drag_to(60, 80)
    app.pet.release()
    assert app.pet.state in (Pet.THROWN, Pet.IDLE)
    for _ in range(120):
        app.pet.update(1 / 60)
    assert app.pet.state == Pet.IDLE, f"pet not settled: {app.pet.state}"
    assert abs(app.pet.y - app.pet.ground_y) < 1.0

    # 气泡：流式追加 → finish → 过期
    app.bubbles.begin_turn(proactive=True)
    app.bubbles.append_speak("今天桌面上有点安静呢。")
    app.bubbles.end_turn("今天桌面上有点安静呢。")
    for _ in range(10):
        app.bubbles.update(0.1)
    assert any("安静" in b.text for b in app.bubbles.bubbles)

    # 沉默契约：finish 空 answer 不出泡
    app.bubbles.begin_turn(proactive=False)
    app.bubbles.end_turn("")
    assert not any(b.typing for b in app.bubbles.bubbles)

    for _ in range(5):
        app.update(0.016)
        app.draw()
    pygame.quit()
    print(f"smoke ok  pet=({app.pet.x:.0f},{app.pet.y:.0f}) bubbles={len(app.bubbles.bubbles)}")


def main() -> None:
    args = parse_args()
    if args.smoke:
        run_smoke()
        return
    os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
    DesktopPetApp(args).run()


if __name__ == "__main__":
    main()
