"""OpenAI 兼容的文本大模型：DeepSeek、通义千问（DashScope compatible-mode）。"""
from __future__ import annotations

from typing import Optional

from .base import LLMProvider, ProviderError, ProviderNotConfigured, make_client, with_retries


class OpenAICompatibleLLM(LLMProvider):
    def __init__(self, *, name: str, api_key: Optional[str], chat_url: str, model: str, supports_json_mode: bool = True):
        if not api_key:
            raise ProviderNotConfigured(f"{name} 未配置 API Key")
        self.name = name
        self.model = model
        self._api_key = api_key
        self.chat_url = chat_url
        self.supports_json_mode = supports_json_mode

    async def complete(self, system, user, *, json_mode=False, temperature=0.8, max_tokens=None, tag="", hints=None) -> str:
        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        if json_mode and self.supports_json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        async with make_client() as client:

            async def call():
                resp = await client.post(self.chat_url, json=body, headers=headers)
                resp.raise_for_status()
                return resp.json()

            data = await with_retries(call, label=f"{self.name} ")

        try:
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"{self.name} 返回格式异常：{str(data)[:300]}")
        if not content.strip():
            raise ProviderError(f"{self.name} 返回了空内容（finish_reason={choice.get('finish_reason')}）")
        return content


def make_deepseek(api_key: Optional[str], base_url: str, model: str) -> OpenAICompatibleLLM:
    base = base_url.rstrip("/")
    # DeepSeek 同时支持 /chat/completions 与 /v1/chat/completions
    url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
    return OpenAICompatibleLLM(name="deepseek", api_key=api_key, chat_url=url, model=model)


def make_qwen(api_key: Optional[str], dashscope_base_url: str, model: str) -> OpenAICompatibleLLM:
    base = dashscope_base_url.rstrip("/")
    if "compatible-mode" not in base:
        base = base + "/compatible-mode/v1"
    return OpenAICompatibleLLM(name="qwen", api_key=api_key, chat_url=base + "/chat/completions", model=model)
