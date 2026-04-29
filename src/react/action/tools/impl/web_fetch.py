from __future__ import annotations

from typing import ClassVar

import httpx
from pydantic import BaseModel, Field

from react.action.base import BaseAction


class WebFetchArgs(BaseModel):
    url: str = Field(..., description="要抓取的网页 URL")
    max_chars: int = Field(4000, ge=100, le=20000, description="返回的最大字符数，默认 4000")


class WebFetchAction(BaseAction):
    name: str = "web_fetch"
    description: str = (
        "抓取指定 URL 的完整网页内容，转换为纯文本后返回。"
        "适合在 web_search 找到链接后读取详情。"
        "参数：url（目标网址），max_chars（最大返回字符数，默认 4000）"
    )
    args_model: ClassVar[type[BaseModel]] = WebFetchArgs

    def execute(self, url: str, max_chars: int = 4000, **kwargs) -> str:
        import html2text

        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = True
        converter.body_width = 0

        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ReActBot/1.0)"},
        )
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "html" in content_type:
            text = converter.handle(response.text)
        else:
            text = response.text

        text = text.strip()
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[内容已截断，共 {len(text)} 字符，仅显示前 {max_chars} 字符]"

        return f"[{url}]\n\n{text}" if text else f"[{url}]\n\n（页面内容为空）"
