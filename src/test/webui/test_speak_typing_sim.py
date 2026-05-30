from __future__ import annotations

from webui.speak_typing_sim import calc_typing_delay_ms


def _frontend_anim_ms(text: str) -> int:
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
    return sum(36 + min(len(c) * 22, 320) for c in chunks)


def test_calc_typing_delay_empty():
    assert calc_typing_delay_ms("") == 0
    assert calc_typing_delay_ms("   ") == 0


def test_calc_typing_delay_short_post_buffer():
    """生成后出站：短缓冲，不按全文长延迟。"""
    delay = calc_typing_delay_ms("你好")
    assert 180 <= delay <= 900


def test_calc_typing_delay_caps_at_max():
    long_text = "你" * 500
    assert calc_typing_delay_ms(long_text) == 900


def test_combined_typing_pace_reasonable_for_typical_replies():
    """后端短缓冲 + 前端动画：常见句长下约 4–18 字/秒（体感可接受）。"""
    samples = [
        "你好，在吗？",
        "今天架构有进展，值得和你聊聊。",
        "我回想了一下刚才的对话，觉得有几个点可以和你分享，不知道你现在方便听吗？",
    ]
    for text in samples:
        total_ms = calc_typing_delay_ms(text) + _frontend_anim_ms(text)
        cps = len(text) / (total_ms / 1000.0)
        assert 4.0 <= cps <= 26.0, (text, total_ms, cps)
