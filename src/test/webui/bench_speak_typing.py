"""逐字呈现（speak simulated）速度基准。"""
from __future__ import annotations

from webui.speak_typing_sim import calc_typing_delay_ms


def frontend_anim_ms(text: str) -> tuple[int, int]:
    chunks: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in "。！？；，、\n" or len(buf) >= 14:
            chunks.append(buf)
            buf = ""
    if buf:
        chunks.append(buf)
    if not chunks:
        chunks = [text]
    total = sum(36 + min(len(c) * 22, 320) for c in chunks)
    return total, len(chunks)


def main() -> None:
    samples = [
        ("短句", "你好，在吗？"),
        ("一句", "今天架构有进展，值得和你聊聊。"),
        ("一段", "我回想了一下刚才的对话，觉得有几个点可以和你分享，不知道你现在方便听吗？"),
        ("长段", "你" * 50),
    ]
    print("backend_short_buffer + frontend_anim (调整后)")
    print(f"{'label':<8} {'chars':>5} {'backend':>8} {'front':>8} {'total':>8} {'cps':>7}")
    for label, text in samples:
        backend = calc_typing_delay_ms(text)
        front, _ = frontend_anim_ms(text)
        total = backend + front
        cps = len(text) / (total / 1000) if total else 0.0
        print(f"{label:<8} {len(text):>5} {backend:>8} {front:>8} {total:>8} {cps:>7.1f}")


if __name__ == "__main__":
    main()
