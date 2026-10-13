"""可灵 Kling 开放平台 —— 图生视频（JWT 鉴权 + 异步轮询）。

文档：https://app.klingai.com/cn/dev/document-api
- 鉴权：HS256 JWT，payload {iss: AccessKey, exp: now+1800, nbf: now-5}，Authorization: Bearer <token>
- 提交：POST /v1/videos/image2video  {model_name, image(base64 或 URL), prompt, mode, duration}
- 查询：GET  /v1/videos/image2video/{task_id}
  task_status: submitted / processing / succeed / failed；结果 data.task_result.videos[0].url
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Optional

from .base import (
    MediaResult,
    ProgressCb,
    ProviderError,
    ProviderNotConfigured,
    VideoProvider,
    download,
    guess_ext,
    make_client,
    poll_until,
    with_retries,
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_kling_jwt(access_key: str, secret_key: str, ttl: int = 1800, now: Optional[int] = None) -> str:
    """生成可灵所需的 HS256 JWT（不依赖第三方库）。"""
    now = int(time.time()) if now is None else now
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"iss": access_key, "exp": now + ttl, "nbf": now - 5}
    seg = _b64url(json.dumps(header, separators=(",", ":")).encode()) + "." + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret_key.encode("utf-8"), seg.encode("ascii"), hashlib.sha256).digest()
    return seg + "." + _b64url(sig)


class KlingVideoProvider(VideoProvider):
    name = "kling"

    def __init__(
        self,
        *,
        access_key: Optional[str],
        secret_key: Optional[str],
        base_url: str = "https://api-beijing.klingai.com",
        model: str = "kling-v2-6",
        mode: str = "std",
        poll_interval: float = 8.0,
        poll_timeout: float = 1200.0,
    ):
        if not access_key or not secret_key:
            raise ProviderNotConfigured("可灵 Kling 未配置 KLING_ACCESS_KEY / KLING_SECRET_KEY")
        self._ak = access_key
        self._sk = secret_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.mode = mode
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {make_kling_jwt(self._ak, self._sk)}", "Content-Type": "application/json"}

    @staticmethod
    def _check(data: dict, label: str) -> dict:
        if data.get("code") != 0:
            raise ProviderError(f"可灵{label}失败：code={data.get('code')} message={data.get('message')} request_id={data.get('request_id')}")
        return data.get("data") or {}

    async def image_to_video(self, image_path, prompt, *, duration_sec=5, aspect_ratio="16:9", negative_prompt="", progress: ProgressCb = None) -> MediaResult:
        image_b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")  # 不带 data: 前缀
        body = {
            "model_name": self.model,
            "image": image_b64,
            "prompt": prompt[:2500],
            "mode": self.mode,
            "duration": "10" if duration_sec >= 10 else "5",
        }
        if negative_prompt:
            body["negative_prompt"] = negative_prompt[:2500]
        if self.model.startswith("kling-v1"):
            body["cfg_scale"] = 0.5

        async with make_client() as client:

            async def submit():
                resp = await client.post(f"{self.base_url}/v1/videos/image2video", json=body, headers=self._headers())
                resp.raise_for_status()
                return resp.json()

            data = self._check(await with_retries(submit, label="可灵提交任务 "), "提交任务")
            task_id = data.get("task_id")
            if not task_id:
                raise ProviderError("可灵未返回 task_id")
            if progress:
                progress(f"可灵视频任务已提交：{task_id}")

            async def fetch():
                async def _get():
                    r = await client.get(f"{self.base_url}/v1/videos/image2video/{task_id}", headers=self._headers())
                    r.raise_for_status()
                    return r.json()

                return self._check(await with_retries(_get, label="可灵查询任务 "), "查询任务")

            def done(d: dict) -> bool:
                return d.get("task_status") in ("succeed", "failed")

            result = await poll_until(fetch, done, interval=self.poll_interval, timeout=self.poll_timeout, progress=progress, label="可灵视频")
            if result.get("task_status") != "succeed":
                raise ProviderError(f"可灵视频任务失败：{result.get('task_status_msg')}")
            videos = (result.get("task_result") or {}).get("videos") or []
            if not videos or not videos[0].get("url"):
                raise ProviderError(f"可灵任务成功但没有视频 URL：{str(result)[:200]}")
            url = videos[0]["url"]
            content = await download(client, url)
        return MediaResult(data=content, ext=guess_ext(url, "mp4"), provider=self.name, model=self.model, meta={"task_id": task_id, "duration": videos[0].get("duration")})
