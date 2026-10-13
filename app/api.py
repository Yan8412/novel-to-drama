"""HTTP API。所有耗时操作返回 job，前端轮询 /api/jobs/{id}。"""
from __future__ import annotations

import shutil
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import prompts as P
from .config import IMAGE_PROVIDERS, LLM_PROVIDERS, VIDEO_PROVIDERS, get_selection, get_settings
from .jobs import get_job_manager
from .models import ChapterVisuals, Episode, NovelSettings, Outline, Project, VisualItem
from .providers import current_image, current_llm, current_video, current_visual_llm
from .providers.base import ProviderError
from .services import episodes as E
from .services import media as M
from .services import novel as N
from .services import visual as V
from .storage import get_store

router = APIRouter()


def _project_or_404(project_id: str) -> Project:
    store = get_store()
    if not store.exists(project_id):
        raise HTTPException(404, "项目不存在")
    return store.load(project_id)


def _job_response(job) -> dict:
    return job.model_dump()


def _guard_running(project_id: str) -> None:
    running = get_job_manager().running_for(project_id)
    if running:
        raise HTTPException(409, f"该项目已有任务在运行（{running[0].kind}），请等待完成或取消后再试")


def _provider_or_400(builder):
    try:
        return builder()
    except ProviderError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


class SelectionUpdate(BaseModel):
    llm_provider: Optional[str] = None
    visual_llm_provider: Optional[str] = None
    image_provider: Optional[str] = None
    video_provider: Optional[str] = None


@router.get("/config")
def get_config():
    s = get_settings()
    sel = get_selection()
    return {
        "selection": sel.as_dict(),
        "key_status": s.key_status(),
        "options": {
            "llm": [{"name": n, "available": s.provider_available("llm", n)} for n in LLM_PROVIDERS],
            "image": [{"name": n, "available": s.provider_available("image", n)} for n in IMAGE_PROVIDERS],
            "video": [{"name": n, "available": s.provider_available("video", n)} for n in VIDEO_PROVIDERS],
        },
        "models": {
            "deepseek": s.deepseek_model,
            "qwen": s.qwen_model,
            "wanx": s.wanx_model,
            "jimeng_image": s.jimeng_t2i_req_key,
            "jimeng_video": s.jimeng_i2v_req_key,
            "kling": f"{s.kling_model}/{s.kling_mode}",
        },
        "cost": {"per_image_cny": s.cost_per_image_cny, "per_video_clip_cny": s.cost_per_video_clip_cny},
        "ffmpeg_ok": bool(shutil.which(s.ffmpeg_path)) or s.ffmpeg_path not in ("ffmpeg", "ffmpeg.exe"),
        "data_dir": str(s.data_path),
        "default_prompts": P.defaults(),
    }


@router.put("/config")
def update_config(body: SelectionUpdate):
    s = get_settings()
    values = body.model_dump(exclude_none=True)
    for k, v in values.items():
        kind = "llm" if "llm" in k else ("image" if "image" in k else "video")
        valid = {"llm": LLM_PROVIDERS, "image": IMAGE_PROVIDERS, "video": VIDEO_PROVIDERS}[kind]
        if v and v not in valid:
            raise HTTPException(400, f"{k} 的取值无效：{v}")
        if v and not s.provider_available(kind, v):
            raise HTTPException(400, f"{v} 尚未配置密钥，请在 .env 中填写后重启")
    get_selection().update(values)
    return get_config()


# ---------------------------------------------------------------------------
# 项目
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str = "未命名项目"
    settings: Optional[NovelSettings] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    settings: Optional[NovelSettings] = None


@router.get("/projects")
def list_projects():
    return [p.summary_dict() for p in get_store().list_projects()]


@router.post("/projects")
def create_project(body: ProjectCreate):
    project = Project(name=body.name, settings=body.settings or NovelSettings())
    get_store().create(project)
    return project


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    return _project_or_404(project_id)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str):
    _project_or_404(project_id)
    get_store().delete(project_id)
    return {"ok": True}


@router.put("/projects/{project_id}")
async def update_project(project_id: str, body: ProjectUpdate):
    _project_or_404(project_id)
    async with get_store().edit(project_id) as p:
        if body.name is not None:
            p.name = body.name
        if body.settings is not None:
            p.settings = body.settings
        return p


# ---------------------------------------------------------------------------
# 大纲
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/outline/generate")
def generate_outline(project_id: str):
    _project_or_404(project_id)
    _guard_running(project_id)
    llm = _provider_or_400(current_llm)
    store = get_store()
    job = get_job_manager().start(project_id, "outline", lambda ctx: _wrap(N.generate_outline(store, llm, project_id, ctx)))
    return _job_response(job)


@router.put("/projects/{project_id}/outline")
async def update_outline(project_id: str, body: Outline):
    _project_or_404(project_id)
    async with get_store().edit(project_id) as p:
        p.outline = body
        p.settings.chapter_count = len(body.chapters) or p.settings.chapter_count
        p.ensure_chapters()
        p.chapters = [c for c in p.chapters if c.index <= len(body.chapters)]
        for c in p.chapters:
            co = next((x for x in body.chapters if x.index == c.index), None)
            if co and c.status == "empty":
                c.title = co.title
        return p


# ---------------------------------------------------------------------------
# 章节
# ---------------------------------------------------------------------------


class ChapterGenBody(BaseModel):
    humanize: bool = True


class ChaptersGenAllBody(BaseModel):
    humanize: bool = True
    only_missing: bool = True


class HumanizeBody(BaseModel):
    source: str = "current"  # current | draft


class ChapterUpdate(BaseModel):
    title: Optional[str] = None
    text: Optional[str] = None
    draft_text: Optional[str] = None
    summary: Optional[str] = None


@router.post("/projects/{project_id}/chapters/{index}/generate")
def generate_chapter(project_id: str, index: int, body: ChapterGenBody):
    _project_or_404(project_id)
    _guard_running(project_id)
    llm = _provider_or_400(current_llm)
    store = get_store()
    job = get_job_manager().start(project_id, f"chapter:{index}", lambda ctx: _wrap(N.generate_chapter(store, llm, project_id, index, ctx, humanize=body.humanize)))
    return _job_response(job)


@router.post("/projects/{project_id}/chapters/generate-all")
def generate_all_chapters(project_id: str, body: ChaptersGenAllBody):
    _project_or_404(project_id)
    _guard_running(project_id)
    llm = _provider_or_400(current_llm)
    store = get_store()
    job = get_job_manager().start(project_id, "chapters:all", lambda ctx: N.generate_all_chapters(store, llm, project_id, ctx, humanize=body.humanize, only_missing=body.only_missing))
    return _job_response(job)


@router.post("/projects/{project_id}/chapters/{index}/humanize")
def humanize_chapter(project_id: str, index: int, body: HumanizeBody):
    _project_or_404(project_id)
    _guard_running(project_id)
    llm = _provider_or_400(current_llm)
    store = get_store()
    job = get_job_manager().start(project_id, f"humanize:{index}", lambda ctx: _wrap(N.humanize_chapter(store, llm, project_id, index, ctx, source=body.source)))
    return _job_response(job)


@router.put("/projects/{project_id}/chapters/{index}")
async def update_chapter(project_id: str, index: int, body: ChapterUpdate):
    _project_or_404(project_id)
    async with get_store().edit(project_id) as p:
        p.ensure_chapters()
        ch = p.get_chapter(index)
        if ch is None:
            raise HTTPException(404, "章节不存在")
        if body.title is not None:
            ch.title = body.title
        if body.text is not None:
            ch.text = body.text
            if ch.status == "empty" and body.text.strip():
                ch.status = "drafted"
        if body.draft_text is not None:
            ch.draft_text = body.draft_text
        if body.summary is not None:
            ch.summary = body.summary
        return ch


# ---------------------------------------------------------------------------
# 角色设定图 / 分镜
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/characters/generate")
def generate_characters(project_id: str):
    _project_or_404(project_id)
    _guard_running(project_id)
    llm = _provider_or_400(current_visual_llm)
    store = get_store()
    job = get_job_manager().start(project_id, "characters", lambda ctx: _wrap(V.generate_character_sheets(store, llm, project_id, ctx)))
    return _job_response(job)


@router.put("/projects/{project_id}/characters")
async def update_characters(project_id: str, body: List[VisualItem]):
    _project_or_404(project_id)
    async with get_store().edit(project_id) as p:
        p.character_sheets = body
        return p.character_sheets


@router.post("/projects/{project_id}/chapters/{index}/visual/generate")
def generate_visual(project_id: str, index: int):
    _project_or_404(project_id)
    _guard_running(project_id)
    llm = _provider_or_400(current_visual_llm)
    store = get_store()
    job = get_job_manager().start(project_id, f"visual:{index}", lambda ctx: _wrap(V.generate_visual_plan(store, llm, project_id, index, ctx)))
    return _job_response(job)


class VisualAllBody(BaseModel):
    only_missing: bool = True


@router.post("/projects/{project_id}/visual/generate-all")
def generate_visual_all(project_id: str, body: VisualAllBody):
    _project_or_404(project_id)
    _guard_running(project_id)
    llm = _provider_or_400(current_visual_llm)
    store = get_store()
    job = get_job_manager().start(project_id, "visual:all", lambda ctx: V.generate_all_visual_plans(store, llm, project_id, ctx, only_missing=body.only_missing))
    return _job_response(job)


@router.put("/projects/{project_id}/chapters/{index}/visual")
async def update_visual(project_id: str, index: int, body: ChapterVisuals):
    _project_or_404(project_id)
    body.chapter_index = index
    async with get_store().edit(project_id) as p:
        p.set_visuals(body)
        return body


# ---------------------------------------------------------------------------
# 图片
# ---------------------------------------------------------------------------


class ImageGenBody(BaseModel):
    chapter_index: Optional[int] = None
    kinds: List[str] = Field(default_factory=lambda: list(M.IMAGE_KINDS))
    only_missing: bool = True
    item_ids: Optional[List[str]] = None


@router.post("/projects/{project_id}/images/estimate")
def estimate_images(project_id: str, body: ImageGenBody):
    project = _project_or_404(project_id)
    targets = M.list_image_targets(project, body.chapter_index, tuple(body.kinds), body.only_missing)
    if body.item_ids:
        targets = [t for t in targets if t[1] in set(body.item_ids)]
    s = get_settings()
    return {"count": len(targets), "unit_cost_cny": s.cost_per_image_cny, "estimated_cost_cny": round(len(targets) * s.cost_per_image_cny, 2), "by_kind": {k: sum(1 for t in targets if t[0] == k) for k in M.IMAGE_KINDS}}


@router.post("/projects/{project_id}/images/generate")
def generate_images(project_id: str, body: ImageGenBody):
    _project_or_404(project_id)
    _guard_running(project_id)
    provider = _provider_or_400(current_image)
    store = get_store()
    job = get_job_manager().start(
        project_id,
        "images",
        lambda ctx: M.generate_images(store, provider, project_id, ctx, chapter_index=body.chapter_index, kinds=tuple(body.kinds), only_missing=body.only_missing, item_ids=body.item_ids),
    )
    return _job_response(job)


# ---------------------------------------------------------------------------
# 剧集 / 视频
# ---------------------------------------------------------------------------


class DefineEpisodesBody(BaseModel):
    chapters_per_episode: Optional[int] = None


@router.post("/projects/{project_id}/episodes/define")
async def define_episodes(project_id: str, body: DefineEpisodesBody):
    _project_or_404(project_id)
    async with get_store().edit(project_id) as p:
        p.ensure_chapters()
        E.define_episodes(p, body.chapters_per_episode)
        return p.episodes


@router.put("/projects/{project_id}/episodes")
async def update_episodes(project_id: str, body: List[Episode]):
    _project_or_404(project_id)
    async with get_store().edit(project_id) as p:
        p.episodes = body
        return p.episodes


@router.get("/projects/{project_id}/episodes/{index}/estimate")
def estimate_episode(project_id: str, index: int):
    project = _project_or_404(project_id)
    ep = project.get_episode(index)
    if ep is None:
        raise HTTPException(404, "剧集不存在")
    return E.estimate_episode(project, ep, get_settings())


class VideoGenBody(BaseModel):
    only_missing: bool = True
    shot_ids: Optional[List[str]] = None


@router.post("/projects/{project_id}/episodes/{index}/videos/generate")
def generate_episode_videos(project_id: str, index: int, body: VideoGenBody):
    project = _project_or_404(project_id)
    ep = project.get_episode(index)
    if ep is None:
        raise HTTPException(404, "剧集不存在")
    _guard_running(project_id)
    provider = _provider_or_400(current_video)
    store = get_store()
    job = get_job_manager().start(
        project_id,
        f"videos:ep{index}",
        lambda ctx: M.generate_shot_videos(store, provider, project_id, ctx, chapter_indices=ep.chapter_indices, only_missing=body.only_missing, shot_ids=body.shot_ids),
    )
    return _job_response(job)


@router.post("/projects/{project_id}/episodes/{index}/render")
def render_episode(project_id: str, index: int):
    _project_or_404(project_id)
    _guard_running(project_id)
    store = get_store()
    job = get_job_manager().start(project_id, f"render:ep{index}", lambda ctx: _wrap(E.render_episode(store, get_settings(), project_id, index, ctx)))
    return _job_response(job)


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = get_job_manager().get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return _job_response(job)


@router.get("/projects/{project_id}/jobs")
def list_jobs(project_id: str):
    return [_job_response(j) for j in get_job_manager().list(project_id)[:20]]


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not get_job_manager().cancel(job_id):
        raise HTTPException(404, "任务不存在")
    return {"ok": True}


# ---------------------------------------------------------------------------
# 文件
# ---------------------------------------------------------------------------

files_router = APIRouter()


@files_router.get("/files/{project_id}/{path:path}")
def get_file(project_id: str, path: str):
    store = get_store()
    try:
        target = store.resolve_asset(project_id, path)
    except ValueError:
        raise HTTPException(400, "非法路径")
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target)


async def _wrap(coro) -> dict:
    """把返回 pydantic 模型的协程包装成 job 结果 dict。"""
    result = await coro
    if hasattr(result, "model_dump"):
        return {"ok": True, "type": type(result).__name__}
    if isinstance(result, list):
        return {"ok": True, "count": len(result)}
    return result if isinstance(result, dict) else {"ok": True}
