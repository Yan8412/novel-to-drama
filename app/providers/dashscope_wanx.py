"""阿里云百炼 DashScope —— 通义万相 文生图（异步任务 + 轮询）。

接口文档：https://help.aliyun.com/zh/model-studio/text-to-image-v2-api-reference
- wan2.5 及更早：POST /api/v1/services/aigc/text2image/image-synthesis  （input.prompt）
- wan2.6-t2i   ：POST /api/v1/services/aigc/image-generation/generation  （input.messages）
- 查询：GET /api/v1/tasks/{task_id}，task_status: PENDING/RUNNING/SUCCEEDED/FAILED/CANCELLED
"""
from __future__ import annotations

from typing import Optional

from .base import (
    ImageProvider,
    MediaResult,
    ProgressCb,
    ProviderError,
    ProviderNotConfigured,
    aspect_to_size,
    download,
    guess_ext,
    make_client,
    poll_until,
    with_retries,
)


class WanxImageProvider(ImageProvider):
    name = "wanx"

    def __init__(
        self,
        *,
        api_key: Optional[str],
        base_url: str = "https://dashscope.aliyuncs.com",
        model: str = "wan2.2-t2i-flash",
        size: str = "",
        poll_interval: float = 5.0,
        poll_timeout: float = 600.0,
    ):
        if not api_key:
            raise ProviderNotConfigured("DashScope（通义万相）未配置 DASHSCOPE_API_KEY")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.size = size
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    def _headers(self, async_mode: bool = False) -> dict:
        h = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        if async_mode:
            h["X-DashScope-Async"] = "enable"
        return h

    def _size_for(self, aspect_ratio: str) -> str:
        if self.size:
            return self.size
        if self.model.startswith("wan2.5") or self.model.startswith("wan2.6"):
            # 这两代模型要求总像素在 1280*1280 ~ 1440*1440 之间
            w, h = aspect_to_size(aspect_ratio, 1440)
            scale = (1280 * 1280 / (w * h)) ** 0.5
            if scale > 1:
                w, h = (-(-int(w * scale) // 16)) * 16, (-(-int(h * scale) // 16)) * 16  # 向上取整到 16 的倍数
            return f"{w}*{h}"
        w, h = aspect_to_size(aspect_ratio, 1280)
        return f"{w}*{h}"

    def _build_request(self, prompt: str, negative_prompt: str, aspect_ratio: str) -> tuple[str, dict]:
        size = self._size_for(aspect_ratio)
        if self.model.startswith("wan2.6"):
            url = f"{self.base_url}/api/v1/services/aigc/image-generation/generation"
            body = {
                "model": self.model,
                "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
                "parameters": {"size": size, "n": 1, "negative_prompt": negative_prompt or "", "watermark": False, "prompt_extend": True},
            }
        else:
            url = f"{self.base_url}/api/v1/services/aigc/text2image/image-synthesis"
            body = {
                "model": self.model,
                "input": {"prompt": prompt, **({"negative_prompt": negative_prompt} if negative_prompt else {})},
                "parameters": {"size": size, "n": 1, "prompt_extend": True, "watermark": False},
            }
        return url, body

    @staticmethod
    def extract_image_url(task_json: dict) -> Optional[str]:
        output = task_json.get("output") or {}
        results = output.get("results") or []
        for r in results:
            if isinstance(r, dict) and r.get("url"):
                return r["url"]
        for choice in output.get("choices") or []:
            content = (choice.get("message") or {}).get("content") or []
            for part in content:
                if isinstance(part, dict) and part.get("image"):
                    return part["image"]
        return None

    async def generate(self, prompt, *, negative_prompt="", aspect_ratio="16:9", progress: ProgressCb = None) -> MediaResult:
        url, body = self._build_request(prompt, negative_prompt, aspect_ratio)
        async with make_client() as client:

            async def submit():
                resp = await client.post(url, json=body, headers=self._headers(async_mode=True))
                resp.raise_for_status()
                return resp.json()

            data = await with_retries(submit, label="万相提交任务 ")
            if data.get("code"):
                raise ProviderError(f"万相提交失败：{data.get('code')} {data.get('message')}")
            task_id = (data.get("output") or {}).get("task_id")
            if not task_id:
                raise ProviderError(f"万相未返回 task_id：{str(data)[:300]}")
            if progress:
                progress(f"万相任务已提交：{task_id}")

            async def fetch():
                async def _get():
                    r = await client.get(f"{self.base_url}/api/v1/tasks/{task_id}", headers=self._headers())
                    r.raise_for_status()
                    return r.json()

                return await with_retries(_get, label="万相查询任务 ")

            def done(j: dict) -> bool:
                return (j.get("output") or {}).get("task_status") in ("SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN")

            result = await poll_until(fetch, done, interval=self.poll_interval, timeout=self.poll_timeout, progress=progress, label="万相图片")
            output = result.get("output") or {}
            if output.get("task_status") != "SUCCEEDED":
                raise ProviderError(f"万相图片任务失败：{output.get('code')} {output.get('message')}")
            img_url = self.extract_image_url(result)
            if not img_url:
                raise ProviderError(f"万相任务成功但没有图片 URL：{str(output)[:300]}")
            content = await download(client, img_url)
        return MediaResult(data=content, ext=guess_ext(img_url, "png"), provider=self.name, model=self.model, meta={"task_id": task_id, "usage": result.get("usage")})
