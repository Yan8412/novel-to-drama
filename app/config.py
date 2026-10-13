"""应用配置：从 .env / 环境变量读取。密钥只在这里读取，绝不打印或写入日志。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

LLM_PROVIDERS = ("mock", "deepseek", "qwen")
IMAGE_PROVIDERS = ("mock", "wanx", "jimeng")
VIDEO_PROVIDERS = ("mock", "kling", "jimeng")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8-sig",  # 兼容 Windows 记事本保存的带 BOM 文件
        extra="ignore",
        case_sensitive=False,
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8000
    data_dir: str = "./data"
    ffmpeg_path: str = "ffmpeg"

    llm_provider: str = "mock"
    visual_llm_provider: Optional[str] = None
    image_provider: str = "mock"
    video_provider: str = "mock"

    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    dashscope_api_key: Optional[str] = None
    dashscope_base_url: str = "https://dashscope.aliyuncs.com"
    qwen_model: str = "qwen-plus"
    wanx_model: str = "wan2.2-t2i-flash"
    wanx_image_size: str = "1280*720"

    volc_access_key: Optional[str] = None
    volc_secret_key: Optional[str] = None
    volc_region: str = "cn-north-1"
    jimeng_t2i_req_key: str = "jimeng_t2i_v40"
    jimeng_i2v_req_key: str = "jimeng_ti2v_v30_pro"
    jimeng_image_width: int = 1280
    jimeng_image_height: int = 720

    kling_access_key: Optional[str] = None
    kling_secret_key: Optional[str] = None
    kling_base_url: str = "https://api-beijing.klingai.com"
    kling_model: str = "kling-v2-6"
    kling_mode: str = "std"

    cost_per_image_cny: float = 0.2
    cost_per_video_clip_cny: float = 3.0

    task_poll_interval: float = 5.0
    task_poll_timeout: float = 900.0

    # ---- 派生属性 ----
    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def projects_path(self) -> Path:
        p = self.data_path / "projects"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def key_status(self) -> dict:
        """只返回「是否已配置」布尔值，绝不返回密钥内容。"""
        return {
            "deepseek": bool(self.deepseek_api_key),
            "dashscope": bool(self.dashscope_api_key),
            "volc": bool(self.volc_access_key and self.volc_secret_key),
            "kling": bool(self.kling_access_key and self.kling_secret_key),
        }

    def provider_available(self, kind: str, name: str) -> bool:
        ks = self.key_status()
        if name == "mock":
            return True
        if kind == "llm":
            return {"deepseek": ks["deepseek"], "qwen": ks["dashscope"]}.get(name, False)
        if kind == "image":
            return {"wanx": ks["dashscope"], "jimeng": ks["volc"]}.get(name, False)
        if kind == "video":
            return {"kling": ks["kling"], "jimeng": ks["volc"]}.get(name, False)
        return False


class RuntimeSelection:
    """界面上可随时切换的厂商选择，持久化在 data/app_settings.json。
    .env 中的 *_PROVIDER 作为默认值。"""

    FIELDS = ("llm_provider", "visual_llm_provider", "image_provider", "video_provider")

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.data_path / "app_settings.json"
        self._data: dict = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, field: str) -> str:
        val = self._data.get(field) or getattr(self.settings, field) or ""
        if field == "visual_llm_provider" and not val:
            val = self.get("llm_provider")
        return val

    def update(self, values: dict) -> None:
        for k, v in values.items():
            if k in self.FIELDS:
                self._data[k] = v or None
        self.save()

    def as_dict(self) -> dict:
        return {f: self.get(f) for f in self.FIELDS}


_settings: Optional[Settings] = None
_selection: Optional[RuntimeSelection] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_selection() -> RuntimeSelection:
    global _selection
    if _selection is None:
        _selection = RuntimeSelection(get_settings())
    return _selection


def reset_settings_for_tests(**overrides) -> Settings:
    """测试用：重建配置对象。"""
    global _settings, _selection
    _settings = Settings(_env_file=None, **overrides)  # type: ignore[call-arg]
    _selection = RuntimeSelection(_settings)
    return _settings
