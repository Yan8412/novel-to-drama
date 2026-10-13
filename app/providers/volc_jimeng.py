"""火山引擎 即梦 AI（视觉智能开放平台）—— 文生图 / 图生视频。

接口：https://visual.volcengineapi.com?Action=CVSync2AsyncSubmitTask&Version=2022-08-31
     https://visual.volcengineapi.com?Action=CVSync2AsyncGetResult&Version=2022-08-31
鉴权：火山引擎 HMAC-SHA256 V4 签名（Region=cn-north-1，Service=cv）
文生图  req_key：jimeng_t2i_v40 / jimeng_t2i_v31 / jimeng_t2i_v30
图生视频 req_key：jimeng_ti2v_v30_pro（1080P，支持首帧）/ jimeng_i2v_first_v30（720P 首帧）
状态：data.status in in_queue / generating / done / not_found / expired
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import quote

from .base import (
    ImageProvider,
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

VISUAL_HOST = "visual.volcengineapi.com"
API_VERSION = "2022-08-31"
SUCCESS_CODE = 10000


# ---------------------------------------------------------------------------
# 签名
# ---------------------------------------------------------------------------


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _uri_encode(s: str) -> str:
    return quote(s, safe="-_.~")


def sign_volc_request(
    *,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    method: str,
    host: str,
    path: str,
    query: Dict[str, str],
    body: bytes,
    now: Optional[dt.datetime] = None,
) -> Dict[str, str]:
    """生成火山引擎 V4 签名所需的请求头。返回 headers（含 Authorization）。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    content_type = "application/json"
    payload_hash = _sha256_hex(body)
    canonical_query = "&".join(f"{_uri_encode(k)}={_uri_encode(str(query[k]))}" for k in sorted(query))
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical_headers = (
        f"content-type:{content_type}\n" f"host:{host}\n" f"x-content-sha256:{payload_hash}\n" f"x-date:{x_date}\n"
    )
    canonical_request = "\n".join([method.upper(), path, canonical_query, canonical_headers, signed_headers, payload_hash])
    credential_scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = "\n".join(["HMAC-SHA256", x_date, credential_scope, _sha256_hex(canonical_request.encode("utf-8"))])
    k_date = _hmac(secret_key.encode("utf-8"), short_date)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    k_signing = _hmac(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = f"HMAC-SHA256 Credential={access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
    return {
        "Content-Type": content_type,
        "Host": host,
        "X-Date": x_date,
        "X-Content-Sha256": payload_hash,
        "Authorization": authorization,
    }


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


class VolcVisualClient:
    def __init__(self, access_key: Optional[str], secret_key: Optional[str], region: str = "cn-north-1", host: str = VISUAL_HOST):
        if not access_key or not secret_key:
            raise ProviderNotConfigured("火山引擎（即梦）未配置 VOLC_ACCESS_KEY / VOLC_SECRET_KEY")
        self._ak = access_key
        self._sk = secret_key
        self.region = region
        self.host = host

    async def call(self, client, action: str, body: dict) -> dict:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        query = {"Action": action, "Version": API_VERSION}
        headers = sign_volc_request(
            access_key=self._ak,
            secret_key=self._sk,
            region=self.region,
            service="cv",
            method="POST",
            host=self.host,
            path="/",
            query=query,
            body=payload,
        )
        url = f"https://{self.host}/?Action={action}&Version={API_VERSION}"

        async def _do():
            resp = await client.post(url, content=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

        data = await with_retries(_do, label=f"即梦 {action} ")
        code = data.get("code")
        if code != SUCCESS_CODE:
            raise ProviderError(f"即梦 {action} 失败：code={code} message={data.get('message')} request_id={data.get('request_id')}")
        return data

    async def submit(self, client, body: dict) -> str:
        data = await self.call(client, "CVSync2AsyncSubmitTask", body)
        task_id = (data.get("data") or {}).get("task_id")
        if not task_id:
            raise ProviderError(f"即梦未返回 task_id：{str(data)[:300]}")
        return task_id

    async def get_result(self, client, req_key: str, task_id: str, req_json: Optional[dict] = None) -> dict:
        body = {"req_key": req_key, "task_id": task_id}
        if req_json:
            body["req_json"] = json.dumps(req_json, ensure_ascii=False)
        data = await self.call(client, "CVSync2AsyncGetResult", body)
        return data.get("data") or {}

    async def wait(self, client, req_key: str, task_id: str, *, interval: float, timeout: float, progress: ProgressCb, label: str, req_json: Optional[dict] = None) -> dict:
        async def fetch():
            return await self.get_result(client, req_key, task_id, req_json)

        def done(d: dict) -> bool:
            return d.get("status") in ("done", "failed", "not_found", "expired")

        result = await poll_until(fetch, done, interval=interval, timeout=timeout, progress=progress, label=label)
        if result.get("status") != "done":
            raise ProviderError(f"即梦{label}任务状态异常：{result.get('status')} {str(result)[:200]}")
        return result


def _file_to_b64(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


class JimengImageProvider(ImageProvider):
    name = "jimeng"

    def __init__(self, *, access_key, secret_key, region="cn-north-1", req_key="jimeng_t2i_v40", width=1280, height=720, poll_interval=5.0, poll_timeout=600.0):
        self.client = VolcVisualClient(access_key, secret_key, region)
        self.model = req_key
        self.width = width
        self.height = height
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    def _dims(self, aspect_ratio: str) -> tuple[int, int]:
        try:
            a, b = [int(x) for x in aspect_ratio.split(":")]
        except Exception:
            return self.width, self.height
        long_side = max(self.width, self.height)
        if a >= b:
            return long_side, int(round(long_side * b / a / 16) * 16)
        return int(round(long_side * a / b / 16) * 16), long_side

    async def generate(self, prompt, *, negative_prompt="", aspect_ratio="16:9", progress: ProgressCb = None) -> MediaResult:
        w, h = self._dims(aspect_ratio)
        body = {"req_key": self.model, "prompt": prompt, "width": w, "height": h, "return_url": True}
        async with make_client() as client:
            task_id = await self.client.submit(client, body)
            if progress:
                progress(f"即梦图片任务已提交：{task_id}")
            result = await self.client.wait(
                client, self.model, task_id, interval=self.poll_interval, timeout=self.poll_timeout, progress=progress, label="即梦图片", req_json={"return_url": True}
            )
            urls = result.get("image_urls") or []
            if urls:
                content = await download(client, urls[0])
                ext = guess_ext(urls[0], "jpg")
            else:
                b64s = result.get("binary_data_base64") or []
                if not b64s:
                    raise ProviderError(f"即梦图片任务完成但没有图片数据：{str(result)[:200]}")
                content = base64.b64decode(b64s[0])
                ext = "jpg"
        return MediaResult(data=content, ext=ext, provider=self.name, model=self.model, meta={"task_id": task_id})


class JimengVideoProvider(VideoProvider):
    name = "jimeng"

    def __init__(self, *, access_key, secret_key, region="cn-north-1", req_key="jimeng_ti2v_v30_pro", poll_interval=8.0, poll_timeout=1200.0):
        self.client = VolcVisualClient(access_key, secret_key, region)
        self.model = req_key
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    async def image_to_video(self, image_path, prompt, *, duration_sec=5, aspect_ratio="16:9", negative_prompt="", progress: ProgressCb = None) -> MediaResult:
        frames = 241 if duration_sec >= 10 else 121  # 121 帧≈5 秒，241 帧≈10 秒
        body = {
            "req_key": self.model,
            "prompt": prompt,
            "binary_data_base64": [_file_to_b64(image_path)],
            "frames": frames,
            "seed": -1,
        }
        async with make_client() as client:
            task_id = await self.client.submit(client, body)
            if progress:
                progress(f"即梦视频任务已提交：{task_id}")
            result = await self.client.wait(client, self.model, task_id, interval=self.poll_interval, timeout=self.poll_timeout, progress=progress, label="即梦视频")
            video_url = result.get("video_url")
            if not video_url:
                raise ProviderError(f"即梦视频任务完成但没有 video_url：{str(result)[:200]}")
            content = await download(client, video_url)
        return MediaResult(data=content, ext=guess_ext(video_url, "mp4"), provider=self.name, model=self.model, meta={"task_id": task_id, "frames": frames})
