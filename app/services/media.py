"""图片与视频生成：把厂商返回的字节保存为项目资产。"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import List, Optional, Tuple

from ..jobs import JobContext
from ..models import Asset, new_id
from ..providers.base import ImageProvider, MediaResult, VideoProvider
from ..storage import ProjectStore

IMAGE_KINDS = ("characters", "scenes", "props", "storyboard")


def _safe_name(s: str, limit: int = 24) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", s).strip("_")
    return s[:limit] or "item"


def save_media(store: ProjectStore, project_id: str, sub: str, filename_base: str, result: MediaResult, prompt: str) -> Asset:
    folder = store.asset_dir(project_id, sub)
    filename = f"{_safe_name(filename_base)}_{new_id()}.{result.ext}"
    path = folder / filename
    path.write_bytes(result.data)
    rel = str(Path("assets") / sub / filename).replace("\\", "/")
    return Asset(kind="video" if result.ext in ("mp4", "mov") else "image", path=rel, provider=result.provider, model=result.model, prompt=prompt, meta=result.meta)


# ---------------------------------------------------------------------------
# 图片
# ---------------------------------------------------------------------------


def list_image_targets(project, chapter_index: Optional[int], kinds: Tuple[str, ...], only_missing: bool) -> List[Tuple[str, str, str, str]]:
    """返回 (kind, item_id, name, prompt) 列表。"""
    targets: List[Tuple[str, str, str, str]] = []
    if "characters" in kinds:
        for it in project.character_sheets:
            if it.image_prompt and (not only_missing or it.asset is None):
                targets.append(("characters", it.id, it.name, it.image_prompt))
    chapter_indices = [chapter_index] if chapter_index is not None else sorted(int(k) for k in project.visuals.keys())
    for ci in chapter_indices:
        v = project.get_visuals(ci)
        if not v:
            continue
        if "scenes" in kinds:
            targets += [("scenes", it.id, it.name, it.image_prompt) for it in v.scenes if it.image_prompt and (not only_missing or it.asset is None)]
        if "props" in kinds:
            targets += [("props", it.id, it.name, it.image_prompt) for it in v.props if it.image_prompt and (not only_missing or it.asset is None)]
        if "storyboard" in kinds:
            targets += [("storyboard", s.id, f"ch{ci}_shot{s.index}", s.image_prompt) for s in v.shots if s.image_prompt and (not only_missing or s.image is None)]
    return targets


def _assign_image(project, item_id: str, asset: Asset) -> bool:
    for it in project.character_sheets:
        if it.id == item_id:
            it.asset = asset
            return True
    for v in project.visuals.values():
        for it in v.scenes + v.props:
            if it.id == item_id:
                it.asset = asset
                return True
        for s in v.shots:
            if s.id == item_id:
                s.image = asset
                s.video = None  # 首帧变了，旧视频失效
                return True
    return False


async def generate_images(
    store: ProjectStore,
    provider: ImageProvider,
    project_id: str,
    ctx: JobContext,
    *,
    chapter_index: Optional[int] = None,
    kinds: Tuple[str, ...] = IMAGE_KINDS,
    only_missing: bool = True,
    item_ids: Optional[List[str]] = None,
    concurrency: int = 2,
) -> dict:
    project = store.load(project_id)
    targets = list_image_targets(project, chapter_index, kinds, only_missing)
    if item_ids:
        targets = [t for t in targets if t[1] in set(item_ids)]
    if not targets:
        ctx.progress(1.0, "没有需要生成的图片")
        return {"generated": 0}
    aspect = project.settings.aspect_ratio
    sem = asyncio.Semaphore(max(1, concurrency))
    done = 0
    failures: List[str] = []
    ctx.progress(0.0, f"共 {len(targets)} 张图片待生成（{provider.name}/{provider.model}）")

    async def one(kind: str, item_id: str, name: str, prompt: str) -> None:
        nonlocal done
        async with sem:
            ctx.check_cancelled()
            try:
                # 角色设定图使用竖幅更合适（全身立绘）
                ratio = "3:4" if kind == "characters" else aspect
                result = await provider.generate(prompt, aspect_ratio=ratio, progress=lambda m: ctx.log(f"[{name}] {m}"))
                asset = save_media(store, project_id, f"images/{kind}", name, result, prompt)
                async with store.edit(project_id) as p:
                    _assign_image(p, item_id, asset)
            except Exception as e:  # noqa: BLE001
                failures.append(f"{name}: {e}")
                ctx.log(f"[{name}] 失败：{e}")
            finally:
                done += 1
                ctx.progress(done / len(targets), f"图片 {done}/{len(targets)}：{name}")

    await asyncio.gather(*(one(*t) for t in targets))
    if failures and len(failures) == len(targets):
        raise RuntimeError("全部图片生成失败：" + failures[0])
    return {"generated": len(targets) - len(failures), "failed": failures}


# ---------------------------------------------------------------------------
# 视频
# ---------------------------------------------------------------------------


def list_video_targets(project, chapter_indices: List[int], only_missing: bool, shot_ids: Optional[List[str]] = None):
    out = []
    for ci in chapter_indices:
        v = project.get_visuals(ci)
        if not v:
            continue
        for s in v.shots:
            if shot_ids and s.id not in shot_ids:
                continue
            if only_missing and s.video is not None:
                continue
            out.append((ci, s))
    return out


async def generate_shot_videos(
    store: ProjectStore,
    provider: VideoProvider,
    project_id: str,
    ctx: JobContext,
    *,
    chapter_indices: List[int],
    only_missing: bool = True,
    shot_ids: Optional[List[str]] = None,
    concurrency: int = 2,
) -> dict:
    project = store.load(project_id)
    targets = list_video_targets(project, chapter_indices, only_missing, shot_ids)
    missing_frames = [f"第{ci}章 镜头{s.index}" for ci, s in targets if s.image is None]
    if missing_frames:
        raise ValueError("以下镜头还没有首帧图，请先生成分镜图片：" + "、".join(missing_frames[:10]))
    if not targets:
        ctx.progress(1.0, "没有需要生成的视频")
        return {"generated": 0}
    aspect = project.settings.aspect_ratio
    sem = asyncio.Semaphore(max(1, concurrency))
    done = 0
    failures: List[str] = []
    ctx.progress(0.0, f"共 {len(targets)} 段视频待生成（{provider.name}/{provider.model}）")

    async def one(ci: int, shot) -> None:
        nonlocal done
        label = f"第{ci}章 镜头{shot.index}"
        async with sem:
            ctx.check_cancelled()
            try:
                image_path = store.resolve_asset(project_id, shot.image.path)
                result = await provider.image_to_video(
                    image_path, shot.video_prompt or shot.action, duration_sec=shot.duration_sec, aspect_ratio=aspect, progress=lambda m: ctx.log(f"[{label}] {m}")
                )
                asset = save_media(store, project_id, "videos/shots", f"ch{ci}_shot{shot.index}", result, shot.video_prompt)
                async with store.edit(project_id) as p:
                    v = p.get_visuals(ci)
                    if v:
                        for s in v.shots:
                            if s.id == shot.id:
                                s.video = asset
                    _refresh_episode_status(p)
            except Exception as e:  # noqa: BLE001
                failures.append(f"{label}: {e}")
                ctx.log(f"[{label}] 失败：{e}")
            finally:
                done += 1
                ctx.progress(done / len(targets), f"视频 {done}/{len(targets)}：{label}")

    await asyncio.gather(*(one(ci, s) for ci, s in targets))
    if failures and len(failures) == len(targets):
        raise RuntimeError("全部视频生成失败：" + failures[0])
    return {"generated": len(targets) - len(failures), "failed": failures}


def _refresh_episode_status(project) -> None:
    for ep in project.episodes:
        shots = [s for ci in ep.chapter_indices for s in ((project.get_visuals(ci).shots if project.get_visuals(ci) else []))]
        if not shots:
            continue
        with_video = sum(1 for s in shots if s.video)
        if ep.video and ep.status == "rendered":
            continue
        ep.status = "videos_done" if with_video == len(shots) else ("videos_partial" if with_video else "pending")
