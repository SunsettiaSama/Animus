from __future__ import annotations

from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field

from ....action.base import BaseAction


class WebFetchArgs(BaseModel):
    url: str = Field(..., description="要抓取的网页 URL（仅支持 http / https）")
    max_chars: int = Field(4000, ge=100, le=20000, description="返回的最大字符数，默认 4000")
    timeout: int = Field(15, ge=1, le=120, description="请求超时秒数，默认 15")
    max_response_bytes: int = Field(
        2_000_000,
        ge=65_536,
        le=20_000_000,
        description="允许的原始响应体最大字节数，超出则不解码正文，默认 2MB",
    )


def _split_mime(content_type: str) -> tuple[str, str]:
    if not content_type:
        return ("", "")
    part = content_type.split(";")[0].strip().lower()
    if "/" not in part:
        return ("", part)
    main, sub = part.split("/", 1)
    return (main, sub)


def _reject_as_non_text(main: str, sub: str) -> bool:
    if main in ("image", "audio", "video"):
        return True
    if main == "application" and sub in (
        "pdf",
        "zip",
        "gzip",
        "x-gzip",
        "x-brotli",
        "octet-stream",
        "msword",
        "vnd.ms-excel",
        "vnd.openxmlformats-officedocument.wordprocessingml.document",
        "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "x-msdownload",
    ):
        return True
    return False


class WebFetchAction(BaseAction):
    name: str = "web_fetch"
    description: str = (
        "抓取指定 URL 的响应体，HTML 会转为可读纯文本，JSON/XML 等按文本返回。"
        "自动拒绝明显二进制类型（如 PDF、图片）。"
        "可选择 max_response_bytes 限制原始响应大小，避免异常大页面占用内存。"
        "若配置了沙箱，会套用与 http_request 相同的 URL 域名策略。"
        "参数：url（http/https），max_chars（最大返回字符数，默认 4000），"
        "timeout（超时秒数，默认 15），max_response_bytes（响应体字节上限，默认 2MB）"
    )
    args_model: ClassVar[type[BaseModel]] = WebFetchArgs

    sandbox: Any = None

    def execute(
        self,
        url: str,
        max_chars: int = 4000,
        timeout: int = 15,
        max_response_bytes: int = 2_000_000,
        **kwargs,
    ) -> str:
        from urllib.parse import urlparse

        import html2text

        raw_url = url.strip()
        parsed = urlparse(raw_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"web_fetch 仅允许 http/https URL，收到 {parsed.scheme!r}"
            )

        if self.sandbox is not None:
            self.sandbox.assert_url_allowed(raw_url)

        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = True
        converter.body_width = 0

        response = httpx.get(
            raw_url,
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36 ReActBot/1.0"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "text/plain;q=0.8,*/*;q=0.7"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        response.raise_for_status()

        raw_len = len(response.content)
        if raw_len > max_response_bytes:
            return (
                f"[{raw_url}]\n\n"
                f"（响应体过大：约 {raw_len} 字节，超过上限 {max_response_bytes} 字节，已中止处理）"
            )

        ct = response.headers.get("content-type", "") or ""
        main, sub = _split_mime(ct)
        if _reject_as_non_text(main, sub):
            n = len(response.content)
            return (
                f"[{raw_url}]\n\n"
                f"（非文本资源 Content-Type: {ct or '未知'}，大小约 {n} 字节，未解码正文）"
            )

        hdr_lower = ct.lower()
        if "charset" not in hdr_lower:
            enc = response.apparent_encoding
            if enc:
                response.encoding = enc

        ct_lower = ct.lower()
        if "html" in ct_lower or sub == "xhtml+xml":
            text = converter.handle(response.text)
        else:
            text = response.text

        full = text.strip()
        total = len(full)
        if total > max_chars:
            body = (
                full[:max_chars]
                + f"\n\n[内容已截断，共 {total} 字符，仅显示前 {max_chars} 字符]"
            )
        else:
            body = full

        return f"[{raw_url}]\n\n{body}" if body else f"[{raw_url}]\n\n（页面内容为空）"
