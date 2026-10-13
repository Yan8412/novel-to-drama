"""从大模型输出中稳健地提取 JSON。"""
from __future__ import annotations

import json
import re
from typing import Any

from ..providers.base import ProviderError

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def extract_json(text: str) -> Any:
    text = text.strip()
    if not text:
        raise ProviderError("模型返回为空，无法解析 JSON")
    candidates = [text]
    for m in _FENCE_RE.finditer(text):
        candidates.append(m.group(1).strip())
    # 截取第一个 { 到最后一个 } / 第一个 [ 到最后一个 ]
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        s, e = text.find(open_ch), text.rfind(close_ch)
        if s != -1 and e > s:
            candidates.append(text[s : e + 1])
    last_err: Exception | None = None
    for c in candidates:
        try:
            return json.loads(c)
        except Exception as e:  # noqa: BLE001
            last_err = e
            try:
                return json.loads(_repair(c))
            except Exception:
                continue
    raise ProviderError(f"无法解析模型返回的 JSON：{last_err}；原文开头：{text[:200]}")


def _repair(s: str) -> str:
    """修复常见小问题：尾逗号、中文引号、单引号键。"""
    s = re.sub(r",\s*([}\]])", r"\1", s)
    s = s.replace("“", '"').replace("”", '"')
    return s


def as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,，;；、\n]", value) if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]
