"""厂商工厂：根据配置与界面选择返回对应的适配器实例。"""
from __future__ import annotations

from typing import Optional

from ..config import IMAGE_PROVIDERS, LLM_PROVIDERS, VIDEO_PROVIDERS, Settings, get_selection, get_settings
from .base import ImageProvider, LLMProvider, ProviderError, ProviderNotConfigured, VideoProvider
from .mock import MockImage, MockLLM, MockVideo


def build_llm(name: str, settings: Optional[Settings] = None) -> LLMProvider:
    s = settings or get_settings()
    if name == "mock":
        return MockLLM()
    if name == "deepseek":
        from .openai_compat import make_deepseek

        return make_deepseek(s.deepseek_api_key, s.deepseek_base_url, s.deepseek_model)
    if name == "qwen":
        from .openai_compat import make_qwen

        return make_qwen(s.dashscope_api_key, s.dashscope_base_url, s.qwen_model)
    raise ProviderError(f"未知的文本模型厂商：{name}（可选：{', '.join(LLM_PROVIDERS)}）")


def build_image(name: str, settings: Optional[Settings] = None) -> ImageProvider:
    s = settings or get_settings()
    if name == "mock":
        return MockImage()
    if name == "wanx":
        from .dashscope_wanx import WanxImageProvider

        return WanxImageProvider(
            api_key=s.dashscope_api_key,
            base_url=s.dashscope_base_url,
            model=s.wanx_model,
            size=s.wanx_image_size,
            poll_interval=s.task_poll_interval,
            poll_timeout=s.task_poll_timeout,
        )
    if name == "jimeng":
        from .volc_jimeng import JimengImageProvider

        return JimengImageProvider(
            access_key=s.volc_access_key,
            secret_key=s.volc_secret_key,
            region=s.volc_region,
            req_key=s.jimeng_t2i_req_key,
            width=s.jimeng_image_width,
            height=s.jimeng_image_height,
            poll_interval=s.task_poll_interval,
            poll_timeout=s.task_poll_timeout,
        )
    raise ProviderError(f"未知的图片厂商：{name}（可选：{', '.join(IMAGE_PROVIDERS)}）")


def build_video(name: str, settings: Optional[Settings] = None) -> VideoProvider:
    s = settings or get_settings()
    if name == "mock":
        return MockVideo(ffmpeg_path=s.ffmpeg_path)
    if name == "kling":
        from .kling import KlingVideoProvider

        return KlingVideoProvider(
            access_key=s.kling_access_key,
            secret_key=s.kling_secret_key,
            base_url=s.kling_base_url,
            model=s.kling_model,
            mode=s.kling_mode,
            poll_interval=max(5.0, s.task_poll_interval),
            poll_timeout=max(s.task_poll_timeout, 1200.0),
        )
    if name == "jimeng":
        from .volc_jimeng import JimengVideoProvider

        return JimengVideoProvider(
            access_key=s.volc_access_key,
            secret_key=s.volc_secret_key,
            region=s.volc_region,
            req_key=s.jimeng_i2v_req_key,
            poll_interval=max(5.0, s.task_poll_interval),
            poll_timeout=max(s.task_poll_timeout, 1200.0),
        )
    raise ProviderError(f"未知的视频厂商：{name}（可选：{', '.join(VIDEO_PROVIDERS)}）")


# ---- 按当前界面选择构建 ----


def current_llm() -> LLMProvider:
    return build_llm(get_selection().get("llm_provider"))


def current_visual_llm() -> LLMProvider:
    return build_llm(get_selection().get("visual_llm_provider"))


def current_image() -> ImageProvider:
    return build_image(get_selection().get("image_provider"))


def current_video() -> VideoProvider:
    return build_video(get_selection().get("video_provider"))


__all__ = [
    "LLMProvider",
    "ImageProvider",
    "VideoProvider",
    "ProviderError",
    "ProviderNotConfigured",
    "build_llm",
    "build_image",
    "build_video",
    "current_llm",
    "current_visual_llm",
    "current_image",
    "current_video",
]
