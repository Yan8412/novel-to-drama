"""真实厂商冒烟测试：只对已配置密钥的厂商做最小调用，报告哪些可用。

用法（在项目根目录）：
    python scripts/smoke_real.py            # 文本 + 一张小图（跳过视频以省钱）
    python scripts/smoke_real.py --video    # 额外生成一段 5 秒视频（会产生费用）
    python scripts/smoke_real.py --only deepseek,wanx

绝不会打印密钥内容，只打印「是否已配置」。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.providers import build_image, build_llm, build_video  # noqa: E402
from app.providers.base import ProviderError, ProviderNotConfigured  # noqa: E402
from app.providers.mock import render_placeholder_image  # noqa: E402

KEY_ENV_NAMES = {
    "deepseek": ["DEEPSEEK_API_KEY"],
    "qwen": ["DASHSCOPE_API_KEY"],
    "wanx": ["DASHSCOPE_API_KEY"],
    "jimeng": ["VOLC_ACCESS_KEY", "VOLC_SECRET_KEY"],
    "kling": ["KLING_ACCESS_KEY", "KLING_SECRET_KEY"],
}


async def smoke_llm(name: str, s) -> str:
    llm = build_llm(name, s)
    t = time.monotonic()
    out = await llm.complete("你是一个只回答一个词的助手。", "请只回复两个字：成功", temperature=0, max_tokens=20)
    return f"OK  模型={llm.model}  耗时={time.monotonic() - t:.1f}s  返回={out.strip()[:30]!r}"


async def smoke_image(name: str, s, out_dir: Path) -> str:
    img = build_image(name, s)
    t = time.monotonic()
    res = await img.generate("一只橘猫坐在窗台上，傍晚暖光，写实摄影", aspect_ratio="16:9", progress=lambda m: print("     ", m))
    path = out_dir / f"smoke_{name}.{res.ext}"
    path.write_bytes(res.data)
    return f"OK  模型={img.model}  耗时={time.monotonic() - t:.0f}s  已保存 {path}（{len(res.data) // 1024} KB）"


async def smoke_video(name: str, s, out_dir: Path, frame: Path) -> str:
    vid = build_video(name, s)
    t = time.monotonic()
    res = await vid.image_to_video(frame, "镜头缓慢推进，猫转头看向窗外", duration_sec=5, aspect_ratio="16:9", progress=lambda m: print("     ", m))
    path = out_dir / f"smoke_{name}.{res.ext}"
    path.write_bytes(res.data)
    return f"OK  模型={vid.model}  耗时={time.monotonic() - t:.0f}s  已保存 {path}（{len(res.data) // 1024} KB）"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", action="store_true", help="同时测试视频厂商（会产生费用）")
    ap.add_argument("--only", default="", help="只测试这些厂商，逗号分隔：deepseek,qwen,wanx,jimeng,kling")
    args = ap.parse_args()
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    s = get_settings()
    out_dir = s.data_path / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("密钥配置状态（不显示内容）：")
    for prov, names in KEY_ENV_NAMES.items():
        kind = {"deepseek": "llm", "qwen": "llm", "wanx": "image", "jimeng": "image/video", "kling": "video"}[prov]
        print(f"  {prov:9s} {kind:12s} {' + '.join(names):40s} {'已配置' if s.provider_available('llm' if prov in ('deepseek', 'qwen') else ('image' if prov in ('wanx', 'jimeng') else 'video'), prov) else '未配置'}")
    print()

    results: dict[str, str] = {}

    async def run(label: str, coro):
        if only and label.split(":")[0] not in only:
            return
        print(f"[{label}] 测试中…")
        try:
            results[label] = await coro
        except ProviderNotConfigured as e:
            results[label] = f"跳过（未配置）：{e}"
        except ProviderError as e:
            results[label] = f"失败：{e}"
        except Exception as e:  # noqa: BLE001
            results[label] = f"异常：{type(e).__name__}: {e}"
        print(f"   -> {results[label]}")

    for name in ("deepseek", "qwen"):
        if s.provider_available("llm", name):
            await run(f"{name}:text", smoke_llm(name, s))
    for name in ("wanx", "jimeng"):
        if s.provider_available("image", name):
            await run(f"{name}:image", smoke_image(name, s, out_dir))
    if args.video:
        frame = out_dir / "smoke_frame.png"
        frame.write_bytes(render_placeholder_image("smoke test frame", 1280, 720, "SMOKE"))
        for name in ("kling", "jimeng"):
            if s.provider_available("video", name):
                await run(f"{name}:video", smoke_video(name, s, out_dir, frame))
    else:
        print("[视频] 已跳过（加 --video 参数才会真实调用视频厂商）")

    print("\n===== 汇总 =====")
    if not results:
        print("没有任何已配置密钥的厂商。请在 .env 中填写后重试，或直接使用模拟模式。")
        return 0
    for k, v in results.items():
        print(f"{k:16s} {v}")
    return 0 if all(v.startswith("OK") or v.startswith("跳过") for v in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
