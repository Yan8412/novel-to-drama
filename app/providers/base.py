"""厂商适配层的统一接口。所有真实厂商与模拟厂商都实现这些接口。"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

ProgressCb = Optional[Callable[[str], None]]


class ProviderError(Exception):
    """厂商调用失败（已脱敏，不包含密钥）。"""


class ProviderNotConfigured(ProviderError):
    """缺少密钥或配置。"""


@dataclass
class MediaResult:
    data: bytes
    ext: str  # png / jpg / mp4
    provider: str
    model: str
    meta: Dict[str, Any] = field(default_factory=dict)


class LLMProvider:
    name: str = "base"
    model: str = ""

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        temperature: float = 0.8,
        max_tokens: Optional[int] = None,
        tag: str = "",
        hints: Optional[dict] = None,
    ) -> str:
        raise NotImplementedError


class ImageProvider:
    name: str = "base"
    model: str = ""

    async def generate(
        self,
        prompt: str,
        *,
        negative_prompt: str = "",
        aspect_ratio: str = "16:9",
        progress: ProgressCb = None,
    ) -> MediaResult:
        raise NotImplementedError


class VideoProvider:
    name: str = "base"
    model: str = ""

    async def image_to_video(
        self,
        image_path: Path,
        prompt: str,
        *,
        duration_sec: int = 5,
        aspect_ratio: str = "16:9",
        negative_prompt: str = "",
        progress: ProgressCb = None,
    ) -> MediaResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = httpx.Timeout(connect=30.0, read=600.0, write=120.0, pool=30.0)


def make_client(**kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True, **kwargs)


def aspect_to_size(aspect_ratio: str, base: int = 1280) -> tuple[int, int]:
    """把 16:9 / 9:16 / 1:1 / 4:3 / 3:4 转成像素尺寸（长边 = base）。"""
    try:
        w, h = [int(x) for x in aspect_ratio.replace("：", ":").split(":")]
    except Exception:
        w, h = 16, 9
    if w >= h:
        return base, int(round(base * h / w / 16) * 16)
    return int(round(base * w / h / 16) * 16), base


async def poll_until(
    fetch: Callable[[], Awaitable[Any]],
    is_done: Callable[[Any], bool],
    *,
    interval: float,
    timeout: float,
    progress: ProgressCb = None,
    label: str = "任务",
) -> Any:
    """通用异步任务轮询。"""
    start = time.monotonic()
    attempt = 0
    while True:
        attempt += 1
        result = await fetch()
        if is_done(result):
            return result
        elapsed = time.monotonic() - start
        if elapsed > timeout:
            raise ProviderError(f"{label}等待超时（{int(timeout)} 秒）")
        if progress:
            progress(f"{label}生成中…（已等待 {int(elapsed)} 秒）")
        await asyncio.sleep(interval)


async def download(client: httpx.AsyncClient, url: str) -> bytes:
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.content


def guess_ext(url: str, default: str) -> str:
    path = url.split("?")[0].lower()
    for ext in ("png", "jpg", "jpeg", "webp", "mp4", "mov"):
        if path.endswith("." + ext):
            return "jpg" if ext == "jpeg" else ext
    return default


async def with_retries(fn: Callable[[], Awaitable[Any]], *, attempts: int = 3, base_delay: float = 2.0, label: str = "") -> Any:
    """对 429 / 5xx / 网络错误做指数退避重试。"""
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            return await fn()
        except httpx.HTTPStatusError as e:
            last = e
            status = e.response.status_code
            if status not in (408, 429) and status < 500:
                raise ProviderError(f"{label}请求失败 HTTP {status}: {_safe_body(e.response)}") from None
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last = e
        if i < attempts - 1:
            await asyncio.sleep(base_delay * (2**i))
    if isinstance(last, httpx.HTTPStatusError):
        raise ProviderError(f"{label}请求失败 HTTP {last.response.status_code}: {_safe_body(last.response)}") from None
    raise ProviderError(f"{label}网络错误：{last}") from None


def _safe_body(resp: httpx.Response, limit: int = 500) -> str:
    try:
        return resp.text[:limit]
    except Exception:
        return "<无法读取响应>"
