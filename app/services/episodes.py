"""剧集：按章节划分剧集、费用预估、用 ffmpeg 拼接每集视频。"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from ..config import Settings
from ..jobs import JobContext
from ..models import Asset, Episode, Project
from ..providers.base import aspect_to_size
from ..storage import ProjectStore


def define_episodes(project: Project, chapters_per_episode: Optional[int] = None) -> List[Episode]:
    """默认一章一集；也可以每 N 章一集。保留已渲染的剧集视频（若章节划分未变）。"""
    n = max(1, chapters_per_episode or project.settings.chapters_per_episode or 1)
    project.settings.chapters_per_episode = n
    indices = [c.index for c in project.chapters] or list(range(1, project.settings.chapter_count + 1))
    old = {tuple(e.chapter_indices): e for e in project.episodes}
    episodes: List[Episode] = []
    for i in range(0, len(indices), n):
        group = indices[i : i + n]
        ep_index = len(episodes) + 1
        titles = [project.get_chapter(ci).title for ci in group if project.get_chapter(ci)]
        title = f"第{ep_index}集" + (f"：{titles[0]}" if len(titles) == 1 and titles[0] else "")
        prev = old.get(tuple(group))
        ep = Episode(index=ep_index, title=prev.title if prev and prev.title else title, chapter_indices=group, video=prev.video if prev else None, status=prev.status if prev else "pending")
        episodes.append(ep)
    project.episodes = episodes
    return episodes


def estimate_episode(project: Project, episode: Episode, settings: Settings) -> dict:
    shots = []
    missing_plan = []
    for ci in episode.chapter_indices:
        v = project.get_visuals(ci)
        if not v:
            missing_plan.append(ci)
            continue
        shots.extend(v.shots)
    total = len(shots)
    with_image = sum(1 for s in shots if s.image)
    with_video = sum(1 for s in shots if s.video)
    pending_videos = sum(1 for s in shots if s.image and not s.video)
    duration = sum(s.duration_sec for s in shots)
    pending_duration = sum(s.duration_sec for s in shots if s.image and not s.video)
    unit = settings.cost_per_video_clip_cny
    return {
        "episode_index": episode.index,
        "chapters": episode.chapter_indices,
        "chapters_without_plan": missing_plan,
        "shot_count": total,
        "shots_with_image": with_image,
        "shots_with_video": with_video,
        "shots_missing_image": total - with_image,
        "pending_video_count": pending_videos,
        "pending_video_seconds": pending_duration,
        "total_seconds": duration,
        "unit_cost_cny": unit,
        "estimated_cost_cny": round(pending_videos * unit * (2 if project.settings.shot_duration_sec >= 10 else 1), 2),
        "ready_to_render": total > 0 and with_video == total,
    }


def _ffmpeg(settings: Settings) -> str:
    path = shutil.which(settings.ffmpeg_path) or settings.ffmpeg_path
    if not (shutil.which(settings.ffmpeg_path) or Path(path).exists()):
        raise RuntimeError("未找到 ffmpeg。请安装 ffmpeg 并把路径写入 .env 的 FFMPEG_PATH。")
    return path


def _run(cmd: List[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败：{proc.stderr[-800:]}")


def concat_videos(ffmpeg: str, inputs: List[Path], output: Path, width: int, height: int, fps: int = 24) -> None:
    """先把每段统一成相同编码/尺寸，再用 concat demuxer 无损拼接。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        normalized: List[Path] = []
        for i, src in enumerate(inputs):
            dst = tdp / f"part_{i:03d}.mp4"
            # 统一分辨率/帧率/编码；没有音轨的片段补一条静音轨，保证 concat 时流结构一致
            audio_map = "0:a:0" if _has_audio(ffmpeg, src) else "1:a:0"
            _run(
                [
                    ffmpeg, "-y", "-loglevel", "error",
                    "-i", str(src),
                    "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                    "-map", "0:v:0", "-map", audio_map,
                    "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2",
                    "-shortest", "-movflags", "+faststart",
                    str(dst),
                ]
            )
            normalized.append(dst)
        list_file = tdp / "list.txt"
        list_file.write_text("".join(f"file '{p.as_posix()}'\n" for p in normalized), encoding="utf-8")
        _run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", "-movflags", "+faststart", str(output)])


def _has_audio(ffmpeg: str, src: Path) -> bool:
    ffprobe = Path(ffmpeg).with_name(Path(ffmpeg).name.replace("ffmpeg", "ffprobe"))
    probe = str(ffprobe) if ffprobe.exists() else (shutil.which("ffprobe") or "")
    if not probe:
        return False
    proc = subprocess.run([probe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(src)], capture_output=True, text=True)
    return "audio" in (proc.stdout or "")


async def render_episode(store: ProjectStore, settings: Settings, project_id: str, episode_index: int, ctx: JobContext) -> Asset:
    project = store.load(project_id)
    ep = project.get_episode(episode_index)
    if ep is None:
        raise ValueError("剧集不存在，请先划分剧集")
    clips: List[Path] = []
    for ci in ep.chapter_indices:
        v = project.get_visuals(ci)
        if not v:
            raise ValueError(f"第 {ci} 章还没有分镜")
        for s in v.shots:
            if not s.video:
                raise ValueError(f"第 {ci} 章镜头 {s.index} 还没有视频，请先生成")
            clips.append(store.resolve_asset(project_id, s.video.path))
    if not clips:
        raise ValueError("本集没有任何镜头视频")
    ffmpeg = _ffmpeg(settings)
    w, h = aspect_to_size(project.settings.aspect_ratio, 1280)
    out_dir = store.asset_dir(project_id, "episodes")
    output = out_dir / f"episode_{episode_index:02d}.mp4"
    ctx.progress(0.1, f"正在用 ffmpeg 拼接 {len(clips)} 段视频…")
    await asyncio.to_thread(concat_videos, ffmpeg, clips, output, w, h)
    asset = Asset(kind="video", path=f"assets/episodes/{output.name}", provider="ffmpeg", model="concat", prompt="", meta={"clips": len(clips), "width": w, "height": h})
    async with store.edit(project_id) as p:
        e = p.get_episode(episode_index)
        if e:
            e.video = asset
            e.status = "rendered"
    ctx.progress(1.0, f"第 {episode_index} 集已生成：{asset.path}")
    return asset
