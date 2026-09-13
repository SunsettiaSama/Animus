"""桌宠实体：idle / walk / drag / thrown 四态 + 程序化动画。

美术源：demos/pygame_town/assets/chars/*.png（Kenney CC0，32×32），
运行时放大 scale 倍并做呼吸/行走/挤压拉伸程序动画。
"""

from __future__ import annotations

import random
from pathlib import Path

import pygame

CHAR_DIR = Path(__file__).resolve().parents[1] / "pygame_town" / "assets" / "chars"

GRAVITY = 1600.0          # px/s²（抛掷下落）
GROUND_BOUNCE = 0.30      # 落地反弹系数
GROUND_FRICTION = 0.86    # 落地水平摩擦（每帧）
WALK_SPEED = 70.0         # px/s
WANDER_MIN_GAP = 5.0      # 闲逛最短间隔 s
WANDER_MAX_GAP = 12.0


class Pet:
    """状态机：IDLE →(随机)→ WALK →(到点)→ IDLE；鼠标抓起 → DRAG →(松手)→ THROWN → IDLE。"""

    IDLE, WALK, DRAG, THROWN = "idle", "walk", "drag", "thrown"

    def __init__(
        self,
        *,
        char: str = "mai",
        scale: int = 3,
        ground_y: float = 0.0,
        bounds: tuple[float, float] = (0.0, 400.0),
    ) -> None:
        raw = pygame.image.load(str(CHAR_DIR / f"{char}.png")).convert_alpha()
        size = raw.get_width() * scale
        self.base: pygame.Surface = pygame.transform.smoothscale(raw, (size, size))
        self.size = size

        self.x = (bounds[0] + bounds[1]) / 2
        self.y = ground_y
        self.ground_y = ground_y
        self.vx = 0.0
        self.vy = 0.0
        self.bounds = bounds

        self.state = self.IDLE
        self.facing = 1            # 1 右 / -1 左
        self.walk_target: float | None = None
        self._wander_timer = random.uniform(WANDER_MIN_GAP, WANDER_MAX_GAP)

        self.anim_t = 0.0
        self.squash = 1.0          # 1 正常；<1 压扁；>1 拉长
        self.blink_t = 0.0
        self.emote: str = ""       # 非空时头顶显示表情
        self.emote_t = 0.0
        self.eyes_closed = False   # wait/silence 姿态

    # ── 姿态触发（供气泡层/交互层调用） ─────────────────────────────────────

    def show_emote(self, text: str, duration: float = 1.6) -> None:
        self.emote = text
        self.emote_t = duration

    def close_eyes(self, duration: float = 1.5) -> None:
        self.eyes_closed = True
        self.blink_t = duration

    def squish(self) -> None:
        self.squash = 0.72

    # ── 交互 ───────────────────────────────────────────────────────────────

    def contains_point(self, px: float, py: float) -> bool:
        half = self.size / 2
        return (
            self.x - half <= px <= self.x + half
            and self.y - self.size <= py <= self.y + half * 0.3
        )

    def grab(self, mx: float, my: float) -> None:
        self.state = self.DRAG
        self.walk_target = None
        self.vx = self.vy = 0.0
        self.grab_dx = self.x - mx
        self.grab_dy = self.y - my
        self.squash = 1.15

    def drag_to(self, mx: float, my: float) -> None:
        if self.state != self.DRAG:
            return
        self.vx = (mx + self.grab_dx - self.x) * 12.0   # 低通：供抛掷初速
        self.vy = (my + self.grab_dy - self.y) * 12.0
        self.x = mx + self.grab_dx
        self.y = my + self.grab_dy
        if abs(self.vx) > 20:
            self.facing = 1 if self.vx > 0 else -1

    def release(self) -> None:
        if self.state != self.DRAG:
            return
        speed = (abs(self.vx) + abs(self.vy)) ** 0.5
        self.state = self.THROWN if speed > 140 else self.IDLE
        if self.state == self.IDLE:
            self.vx = self.vy = 0.0
            self.y = self.ground_y
            self.squash = 0.75

    # ── 帧更新 ─────────────────────────────────────────────────────────────

    def update(self, dt: float, *, disturb: bool = False) -> None:
        self.anim_t += dt
        if self.emote_t > 0:
            self.emote_t -= dt
            if self.emote_t <= 0:
                self.emote = ""
        if self.blink_t > 0:
            self.blink_t -= dt
            if self.blink_t <= 0:
                self.eyes_closed = False

        # squash 回弹到 1
        self.squash += (1.0 - self.squash) * min(1.0, dt * 9.0)

        if self.state == self.IDLE:
            self._idle(dt, disturb)
        elif self.state == self.WALK:
            self._walk(dt)
        elif self.state == self.THROWN:
            self._fly(dt)

    def _idle(self, dt: float, disturb: bool) -> None:
        self.y = self.ground_y
        if disturb:
            return  # 对话进行中不乱跑
        self._wander_timer -= dt
        if self._wander_timer <= 0:
            self._wander_timer = random.uniform(WANDER_MIN_GAP, WANDER_MAX_GAP)
            if random.random() < 0.6:
                lo, hi = self.bounds
                target = random.uniform(lo, hi)
                if abs(target - self.x) > self.size:
                    self.walk_target = target
                    self.state = self.WALK
                    self.facing = 1 if target > self.x else -1

    def _walk(self, dt: float) -> None:
        if self.walk_target is None:
            self.state = self.IDLE
            return
        delta = self.walk_target - self.x
        step = WALK_SPEED * dt
        if abs(delta) <= step:
            self.x = self.walk_target
            self.state = self.IDLE
            self.squash = 0.82
            return
        self.x += step * self.facing
        self._clamp_x()

    def _fly(self, dt: float) -> None:
        self.vy += GRAVITY * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self._clamp_x()
        if self.y >= self.ground_y:
            self.y = self.ground_y
            if abs(self.vy) > 220:
                self.vy = -self.vy * GROUND_BOUNCE
                self.vx *= GROUND_FRICTION
                self.squash = 0.65
            else:
                self.vy = 0.0
                self.vx = 0.0
                self.state = self.IDLE
                self.squash = 0.72

    def _clamp_x(self) -> None:
        lo, hi = self.bounds
        if self.x < lo:
            self.x = lo
            self.vx = abs(self.vx) * GROUND_BOUNCE
        elif self.x > hi:
            self.x = hi
            self.vx = -abs(self.vx) * GROUND_BOUNCE

    # ── 渲染 ───────────────────────────────────────────────────────────────

    def draw(self, screen: pygame.Surface) -> None:
        surf = self.base
        w = surf.get_width()
        h = surf.get_height()
        # 呼吸：idle 缓慢起伏；walk 蹦跳；squash 作用于高度
        if self.state == self.IDLE:
            breathe = 1.0 + 0.035 * ((self.anim_t * 1.8) % 2.0 - 1.0) ** 2
            hop = 0.0
        elif self.state == self.WALK:
            breathe = 1.0
            hop = -abs(((self.anim_t * 6.0) % 2.0) - 1.0) * self.size * 0.12
        else:
            breathe = 1.0
            hop = 0.0
        sh = h * self.squash * breathe
        sw = w * (2.0 - self.squash) * 0.5 + w * 0.5  # 挤压保体积
        scaled = pygame.transform.smoothscale(
            surf, (max(2, int(sw)), max(2, int(sh)))
        )
        if self.facing < 0:
            scaled = pygame.transform.flip(scaled, True, False)
        rect = scaled.get_rect(midbottom=(int(self.x), int(self.y + hop)))
        screen.blit(scaled, rect)

        # 影子
        if self.state in (self.THROWN, self.WALK) or hop:
            shadow_w = int(w * 0.5 * max(0.3, 1.0 - (self.ground_y - self.y) / (self.size * 3)))
            shadow = pygame.Surface((shadow_w, 4), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (30, 30, 30, 70), shadow.get_rect())
            screen.blit(shadow, (int(self.x - shadow_w / 2), int(self.ground_y) - 2))

        # 眯眼（wait/silence）：头顶小 z z
        if self.eyes_closed:
            zzz = PET_FONT.render("z z", True, (120, 120, 130))
            screen.blit(zzz, (int(self.x) + self.size // 3, int(self.y) - self.size - 6))

        # 表情
        if self.emote:
            em = PET_FONT.render(self.emote, True, (255, 120, 90))
            screen.blit(
                em,
                (int(self.x) - em.get_width() // 2, int(self.y) - self.size - em.get_height() - 8),
            )


# 延迟初始化的字体（pygame.init 后由 main 注入）
PET_FONT = None


def init_pet_font(size: int = 13) -> None:
    global PET_FONT
    PET_FONT = pygame.font.SysFont("microsoftyahei,simhei,consolas", size)
