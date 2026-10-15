"""同域浏览器代理；兼容推理接口仍由 vvoice.main 提供。"""
from __future__ import annotations

import httpx
from fastapi import Request, HTTPException
from fastapi.responses import Response


async def proxy(request: Request, path: str) -> Response:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 28 * 1024 * 1024:
            raise HTTPException(413, "request too large")
    headers = {key: value for key, value in request.headers.items() if key.lower() in {"authorization", "content-type", "range", "if-none-match"}}
    try:
        async with httpx.AsyncClient(timeout=150) as client:
            response = await client.request(request.method, f"http://127.0.0.1:7080/{path}", params=request.query_params, content=bytes(body), headers=headers)
    except httpx.HTTPError:
        raise HTTPException(503, "Voice workbench is unavailable") from None
    excluded = {"transfer-encoding", "connection", "content-encoding", "content-length"}
    return Response(response.content, status_code=response.status_code, headers={key: value for key, value in response.headers.items() if key.lower() not in excluded})
