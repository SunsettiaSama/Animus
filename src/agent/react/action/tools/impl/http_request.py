from __future__ import annotations

from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field

from ....action.base import BaseAction


class HttpRequestArgs(BaseModel):
    url: str = Field(..., min_length=1, description="目标 URL")
    method: str = Field("GET", description="HTTP 方法：GET / POST / PUT / DELETE / PATCH，默认 GET")
    headers: dict = Field(default_factory=dict, description="自定义请求头（JSON 对象）")
    body: str = Field("", description="请求体（字符串），用于 POST/PUT/PATCH")
    json_body: dict = Field(default_factory=dict, description="JSON 请求体（对象），与 body 二选一")
    timeout: int = Field(15, ge=1, le=120, description="超时秒数，默认 15")
    max_response_chars: int = Field(5000, ge=100, le=50000, description="最大响应字符数，默认 5000")


class HttpRequestAction(BaseAction):
    name: str = "http_request"
    description: str = (
        "发送通用 HTTP 请求（GET/POST/PUT/DELETE/PATCH），支持自定义 headers 和 JSON body。"
        "参数：url（目标地址），method（HTTP 方法，默认 GET），headers（自定义请求头），"
        "body（字符串请求体），json_body（JSON 对象请求体），timeout（超时秒数，默认 15），"
        "max_response_chars（最大响应字符数，默认 5000）"
    )
    args_model: ClassVar[type[BaseModel]] = HttpRequestArgs

    sandbox: Any = None

    def execute(
        self,
        url: str,
        method: str = "GET",
        headers: dict | None = None,
        body: str = "",
        json_body: dict | None = None,
        timeout: int = 15,
        max_response_chars: int = 5000,
        **kwargs,
    ) -> str:
        if self.sandbox is not None:
            self.sandbox.assert_url_allowed(url)

        method = method.upper().strip()
        req_headers = headers or {}
        content: bytes | None = None
        json_payload: dict | None = None

        if json_body:
            json_payload = json_body
        elif body:
            content = body.encode("utf-8")
            if "content-type" not in {k.lower() for k in req_headers}:
                req_headers["Content-Type"] = "text/plain; charset=utf-8"

        response = httpx.request(
            method=method,
            url=url,
            headers=req_headers,
            content=content,
            json=json_payload,
            timeout=timeout,
            follow_redirects=True,
        )

        text = response.text
        if len(text) > max_response_chars:
            text = text[:max_response_chars] + f"\n\n[响应已截断，共 {len(response.text)} 字符]"

        return (
            f"HTTP {method} {url}\n"
            f"状态码：{response.status_code}\n"
            f"Content-Type：{response.headers.get('content-type', '未知')}\n\n"
            f"{text}"
        )
