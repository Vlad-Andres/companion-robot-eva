"""
utils/http_client.py — Minimal async HTTP client built on the standard library.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HTTPRequestError(RuntimeError):
    def __init__(self, message: str, *, status: Optional[int] = None, body: Optional[bytes] = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def join_url(base_url: str, endpoint: str) -> str:
    return f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"


def _request_json_sync(
    *,
    method: str,
    url: str,
    body: Optional[bytes],
    timeout_seconds: float,
    headers: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    req_headers: Dict[str, str] = {"Accept": "application/json"}
    if headers:
        req_headers.update(dict(headers))

    req = Request(url=url, method=method.upper(), data=body, headers=req_headers)
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            resp_body = resp.read()
            if not resp_body:
                return {}
            return json.loads(resp_body.decode("utf-8"))
    except HTTPError as exc:
        exc_body = exc.read() if hasattr(exc, "read") else None
        raise HTTPRequestError(
            f"HTTP {exc.code} calling {url}",
            status=exc.code,
            body=exc_body,
        ) from exc
    except URLError as exc:
        raise HTTPRequestError(f"Network error calling {url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HTTPRequestError(f"Invalid JSON response from {url}: {exc}") from exc


async def request_json(
    *,
    method: str,
    url: str,
    body: Optional[bytes],
    timeout_seconds: float,
    headers: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        _request_json_sync,
        method=method,
        url=url,
        body=body,
        timeout_seconds=timeout_seconds,
        headers=headers,
    )


async def post_json(
    *,
    url: str,
    payload: Any,
    timeout_seconds: float,
    headers: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    merged_headers: Dict[str, str] = {"Content-Type": "application/json"}
    if headers:
        merged_headers.update(dict(headers))
    return await request_json(
        method="POST",
        url=url,
        body=body,
        timeout_seconds=timeout_seconds,
        headers=merged_headers,
    )


async def post_bytes_for_json(
    *,
    url: str,
    payload: bytes,
    content_type: str,
    timeout_seconds: float,
    headers: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    merged_headers: Dict[str, str] = {"Content-Type": content_type}
    if headers:
        merged_headers.update(dict(headers))
    return await request_json(
        method="POST",
        url=url,
        body=payload,
        timeout_seconds=timeout_seconds,
        headers=merged_headers,
    )

