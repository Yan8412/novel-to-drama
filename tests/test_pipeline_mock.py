"""模拟模式下的完整流水线测试：设定 -> 大纲 -> 章节 -> 去AI味 -> 角色/分镜 -> 图片 -> 视频 -> 成片。"""
import shutil
import subprocess

import pytest

from app.jobs import JobContext
from app.models import JobInfo
from app.providers import build_image, build_llm, build_video
from app.services import episodes as E
from app.services import media as M
from app.services import novel as N
from app.services import visual as V


def ctx_for(project):
    return JobContext(JobInfo(id="job_test", project_id=project.id, kind="test"))


async def test_outline_and_chapters(store, project):
    llm = build_llm("mock")
    ctx = ctx_for(project)
    outline = await N.generate_outline(store, llm, project.id, ctx)
    assert outline.title
    assert len(outline.chapters) == 2
    assert outline.character_bible
    assert "林晚" in outline.character_bible

    p = store.load(project.id)
    assert [c.index for c in p.chapters] == [1, 2]
    assert all(c.status == "empty" for c in p.chapters)

    # 第一章：初稿 + 去 AI 味
    ch = await N.generate_chapter(store, llm, project.id, 1, ctx, humanize=True)
    assert ch.status == "humanized"
    assert ch.draft_text and ch.text
    assert ch.summary
    assert 400 < ch.word_count < 1600

    # 第二章会收到第一章摘要作为前情
    ch2 = await N.generate_chapter(store, llm, project.id, 2, ctx, humanize=False)
    assert ch2.status == "drafted"
    assert ch2.text == ch2.draft_text

    # 单独改写：基于初稿
    ch2b = await N.humanize_chapter(store, llm, project.id, 2, ctx, source="draft")
    assert ch2b.status == "humanized"

    p = store.load(project.id)
    assert all(c.status == "humanized" for c in p.chapters)


async def test_generate_all_chapters_only_missing(store, project):
    llm = build_llm("mock")
    ctx = ctx_for(project)
    await N.generate_outline(store, llm, project.id, ctx)
    result = await N.generate_all_chapters(store, llm, project.id, ctx, humanize=False)
    assert result["chapters"] == [1, 2]
    # 再跑一次只补缺失，应当不做任何事
    result = await N.generate_all_chapters(store, llm, project.id, ctx, humanize=False)
    assert result["chapters"] == []


async def test_full_pipeline_to_episode_video(store, project, settings):
    if not shutil.which(settings.ffmpeg_path):
        pytest.skip("需要 ffmpeg")
    llm = build_llm("mock")
    image = build_image("mock")
    video = build_video("mock")
    ctx = ctx_for(project)

    await N.generate_outline(store, llm, project.id, ctx)
    await N.generate_all_chapters(store, llm, project.id, ctx, humanize=True)

    sheets = await V.generate_character_sheets(store, llm, project.id, ctx)
    names = {s.name for s in sheets}
    assert {"林晚", "顾言"} <= names
    # 用户给定的外貌应被采用
    lin = next(s for s in sheets if s.name == "林晚")
    assert "齐肩黑发" in lin.description

    await V.generate_all_visual_plans(store, llm, project.id, ctx)
    p = store.load(project.id)
    for ci in (1, 2):
        v = p.get_visuals(ci)
        assert v is not None
        assert len(v.shots) == 3
        assert v.scenes and v.props
        for s in v.shots:
            assert s.image_prompt and s.video_prompt
            assert s.duration_sec in (5, 10)
            # 一致性：出场角色的外貌关键词必须出现在首帧提示词中
            for name in s.characters:
                key = V.character_keys(p)[name]
                assert key[:12] in s.image_prompt

    # 图片：角色 + 场景 + 道具 + 分镜
    res = await M.generate_images(store, image, project.id, ctx)
    assert res["generated"] == 2 + sum(len(v.scenes) + len(v.props) + len(v.shots) for v in p.visuals.values())
    p = store.load(project.id)
    assert all(s.asset for s in p.character_sheets)
    for v in p.visuals.values():
        for s in v.shots:
            assert s.image is not None
            assert store.resolve_asset(project.id, s.image.path).exists()

    # 再次只补缺失：应当为 0
    res = await M.generate_images(store, image, project.id, ctx)
    assert res["generated"] == 0

    # 单张重新生成
    shot = p.get_visuals(1).shots[0]
    old_path = shot.image.path
    res = await M.generate_images(store, image, project.id, ctx, only_missing=False, item_ids=[shot.id])
    assert res["generated"] == 1
    assert store.load(project.id).get_visuals(1).shots[0].image.path != old_path

    # 剧集：默认一章一集
    async with store.edit(project.id) as pp:
        eps = E.define_episodes(pp)
    assert [e.chapter_indices for e in eps] == [[1], [2]]

    p = store.load(project.id)
    est = E.estimate_episode(p, p.episodes[0], settings)
    assert est["shot_count"] == 3 and est["pending_video_count"] == 3 and est["shots_missing_image"] == 0
    assert est["estimated_cost_cny"] == pytest.approx(3 * settings.cost_per_video_clip_cny)
    assert not est["ready_to_render"]

    # 视频：手动按集触发
    res = await M.generate_shot_videos(store, video, project.id, ctx, chapter_indices=p.episodes[0].chapter_indices)
    assert res["generated"] == 3
    p = store.load(project.id)
    assert p.episodes[0].status == "videos_done"
    assert E.estimate_episode(p, p.episodes[0], settings)["ready_to_render"]

    # 成片
    asset = await E.render_episode(store, settings, project.id, 1, ctx)
    out = store.resolve_asset(project.id, asset.path)
    assert out.exists() and out.stat().st_size > 10_000
    assert store.load(project.id).episodes[0].status == "rendered"

    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        dur = float(subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip())
        assert dur >= 3 * 1  # 模拟视频每段至少 1 秒

    # 第二集尚未生成视频，不能成片
    with pytest.raises(ValueError):
        await E.render_episode(store, settings, project.id, 2, ctx)


async def test_define_episodes_grouping(store, project):
    llm = build_llm("mock")
    ctx = ctx_for(project)
    await N.generate_outline(store, llm, project.id, ctx)
    async with store.edit(project.id) as p:
        eps = E.define_episodes(p, chapters_per_episode=2)
    assert len(eps) == 1 and eps[0].chapter_indices == [1, 2]


async def test_video_requires_frames(store, project):
    llm = build_llm("mock")
    video = build_video("mock")
    ctx = ctx_for(project)
    await N.generate_outline(store, llm, project.id, ctx)
    await N.generate_all_chapters(store, llm, project.id, ctx, humanize=False)
    await V.generate_visual_plan(store, llm, project.id, 1, ctx)
    with pytest.raises(ValueError, match="首帧"):
        await M.generate_shot_videos(store, video, project.id, ctx, chapter_indices=[1])
