"""气泡系统：把 soul 的 speak 流渲染成桌宠头顶的对话气泡。

字段消费契约与 WebUI 一致（protocol/speak_fields.js 的 Python 镜像）：
- speak   → 主气泡（正在生成的文本打字机式追加）
- observe / outline → 次级灰泡（叙事/场景，弱化显示）
- silence / wait → 不出泡，转成桌宠姿态（眯眼 z z）
- agent_typing(meta.active) → 打字中指示
- 其余（thought/tag/chunk/state/finish）→ 忽略
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pygame

MAX_TEXT_PER_BUBBLE = 240
MAX_BUBBLES = 3
BUBBLE_LINE_CHARS = 16
BUBBLE_BG = (250, 248, 242)
BUBBLE_BG_DIM = (238, 238, 236)
BUBBLE_BORDER = (70, 62, 54)


def _wrap(text: str, cols: int) -> list[str]:
    lines: list[str] = []
    for para in text.splitlines() or [""]:
        chunk = para
        while len(chunk) > cols:
            lines.append(chunk[:cols])
            chunk = chunk[cols:]
        lines.append(chunk)
    return lines


@dataclass
class Bubble:
    text: str = ""
    dim: bool = False            # 次级（叙事/场景）
    typing: bool = False         # 流式生成中
    age: float = 0.0
    life: float = 6.0
    _raf: list = field(default_factory=list)  # 占位：防抖动

    def remain(self) -> float:
        return max(0.6, 1.2 + len(self.text) * 0.055)

    def done(self) -> bool:
        return (not self.typing) and self.age >= self.remain()


class BubbleLayer:
    """维护最多 MAX_BUBBLES 个气泡；锚点为桌宠头顶 (anchor_x, anchor_y)。"""

    def __init__(self, font: pygame.font.Font) -> None:
        self.font = font
        self.small = pygame.font.SysFont(
            "microsoftyahei,simhei,consolas", max(11, font.get_height() - 3)
        )
        self.bubbles: list[Bubble] = []
        self.dots_t = 0.0

    # ── soul 流接口 ────────────────────────────────────────────────────────

    def begin_turn(self, *, proactive: bool) -> None:
        """turn_start：清掉已完成的旧泡，保留在流的。"""
        self.bubbles = [b for b in self.bubbles if b.typing][-1:]
        if proactive:
            self.bubbles.append(Bubble(text="（主动找你）", dim=True, life=2.0))

    def append_speak(self, text: str) -> None:
        bubble = self._typing_bubble(dim=False)
        if bubble is None:
            bubble = Bubble(typing=True)
            self.bubbles.append(bubble)
        bubble.text = (bubble.text + text)[:MAX_TEXT_PER_BUBBLE]

    def append_narrative(self, text: str) -> None:
        bubble = self._typing_bubble(dim=True)
        if bubble is None:
            bubble = Bubble(typing=True, dim=True, life=5.0)
            self.bubbles.append(bubble)
        bubble.text = (bubble.text + text)[:MAX_TEXT_PER_BUBBLE]

    def set_typing(self, active: bool) -> None:
        bubble = self._typing_bubble(dim=False)
        if active and bubble is None and not any(b.typing for b in self.bubbles):
            self.bubbles.append(Bubble(typing=True))
        if not active:
            for b in self.bubbles:
                if b.typing and not b.text:
                    b.typing = False

    def end_turn(self, answer: str = "") -> None:
        """turn_finish：停止打字态；空回恩（模型选择沉默）→ 轻「……」。"""
        live = [b for b in self.bubbles if b.typing]
        if live:
            for b in live:
                b.typing = False
            return
        if answer.strip():
            self.bubbles.append(Bubble(text=answer.strip()[:MAX_TEXT_PER_BUBBLE]))
        # answer 为空 = 模型行使沉默权：不出泡（桌宠保持安静）。

    def note_silence(self) -> None:
        """显式 silence/wait 字段：不出泡。"""
        return

    def add_local(self, text: str, duration: float = 3.0) -> None:
        self.bubbles.append(Bubble(text=text, life=duration))

    # ── 内部 ───────────────────────────────────────────────────────────────

    def _typing_bubble(self, *, dim: bool) -> Bubble | None:
        for b in reversed(self.bubbles):
            if b.typing and b.dim == dim:
                return b
        return None

    # ── 帧更新与渲染 ───────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        self.dots_t += dt
        for b in self.bubbles:
            b.age += dt
        self.bubbles = [b for b in self.bubbles if not b.done()]
        self.bubbles = self.bubbles[-MAX_BUBBLES:]

    def draw(self, screen: pygame.Surface, anchor_x: float, anchor_top: float) -> None:
        y = anchor_top - 10.0
        for bubble in reversed(self.bubbles):
            used = self.font if not bubble.dim else self.small
            lines = _wrap(bubble.text, BUBBLE_LINE_CHARS if not bubble.dim else 22)
            if bubble.typing:
                dots = "." * (1 + int(self.dots_t * 2.0) % 3)
                shown = lines or [""]
                if not bubble.text:
                    lines = [dots]
            rendered = [
                used.render(line, True, (60, 54, 48) if not bubble.dim else (110, 108, 104))
                for line in lines[-5:]
            ]
            if not rendered:
                continue
            pad_x, pad_y = 8, 6
            w = max(p.get_width() for p in rendered) + pad_x * 2
            h = sum(p.get_height() for p in rendered) + pad_y * 2 - 2
            bx = int(min(max(4, anchor_x - w / 2), screen.get_width() - w - 4))
            by = int(y - h)
            bg = BUBBLE_BG_DIM if bubble.dim else BUBBLE_BG
            pygame.draw.rect(screen, bg, (bx, by, w, h), border_radius=8)
            pygame.draw.rect(screen, BUBBLE_BORDER, (bx, by, w, h), 1, border_radius=8)
            # 尾巴指向桌宠
            tail_x = int(min(max(bx + 12, anchor_x), bx + w - 12))
            pygame.draw.polygon(
                screen, bg,
                [(tail_x - 5, by + h - 1), (tail_x + 5, by + h - 1), (int(anchor_x), by + h + 6)],
            )
            pygame.draw.polygon(
                screen, BUBBLE_BORDER,
                [(tail_x - 5, by + h), (tail_x + 5, by + h), (int(anchor_x), by + h + 6)],
            )
            ty = by + pad_y
            for p in rendered:
                screen.blit(p, (bx + pad_x, ty))
                ty += p.get_height()
            y = by - 6.0
