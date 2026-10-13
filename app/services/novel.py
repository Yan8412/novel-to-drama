"""小说生成：大纲 -> 逐章正文（角色圣经 + 滚动摘要）-> 去 AI 味改写。"""
from __future__ import annotations

import re
from typing import List, Optional

from .. import prompts as P
from ..jobs import JobContext
from ..models import Chapter, ChapterOutline, Outline, Project
from ..providers.base import LLMProvider
from ..storage import ProjectStore
from .llm_json import as_str_list, extract_json

MAX_HUMANIZE_CHUNK = 2600  # 每次改写的最大字数，避免输出被截断


def _resolved(project: Project) -> dict:
    return P.resolve(project.settings.style_prompts)


# ---------------------------------------------------------------------------
# 大纲
# ---------------------------------------------------------------------------


def parse_outline(data: dict, expected_chapters: int) -> Outline:
    chapters: List[ChapterOutline] = []
    for i, c in enumerate(data.get("chapters") or [], start=1):
        if not isinstance(c, dict):
            continue
        try:
            idx = int(c.get("index") or i)
        except Exception:
            idx = i
        chapters.append(
            ChapterOutline(
                index=idx,
                title=str(c.get("title") or f"第{idx}章"),
                summary=str(c.get("summary") or ""),
                key_events=as_str_list(c.get("key_events")),
                characters=as_str_list(c.get("characters")),
                hook=str(c.get("hook") or ""),
            )
        )
    chapters.sort(key=lambda c: c.index)
    # 重新连续编号，并裁剪/补齐到期望数量
    for i, c in enumerate(chapters, start=1):
        c.index = i
    chapters = chapters[:expected_chapters]
    while len(chapters) < expected_chapters:
        n = len(chapters) + 1
        chapters.append(ChapterOutline(index=n, title=f"第{n}章", summary="（模型未生成本章大纲，请手动补充）"))
    return Outline(
        title=str(data.get("title") or ""),
        logline=str(data.get("logline") or ""),
        synopsis=str(data.get("synopsis") or ""),
        world_setting=str(data.get("world_setting") or ""),
        character_bible=str(data.get("character_bible") or ""),
        chapters=chapters,
    )


async def generate_outline(store: ProjectStore, llm: LLMProvider, project_id: str, ctx: Optional[JobContext] = None) -> Outline:
    project = store.load(project_id)
    sp = _resolved(project)
    if ctx:
        ctx.progress(0.1, f"正在用 {llm.name}/{llm.model} 生成大纲…")
    raw = await llm.complete(
        sp["outline_system"],
        P.outline_user(project.settings),
        json_mode=True,
        temperature=0.9,
        max_tokens=8000,
        tag="outline",
        hints={"chapter_count": project.settings.chapter_count},
    )
    outline = parse_outline(extract_json(raw), project.settings.chapter_count)
    if not outline.title:
        outline.title = project.settings.title or "未命名"
    async with store.edit(project_id) as p:
        p.outline = outline
        if not p.settings.title:
            p.settings.title = outline.title
        if p.name == "未命名项目" and outline.title:
            p.name = outline.title
        # 大纲变化后，章节占位同步（已写的章节保留）
        p.ensure_chapters()
        p.chapters = [c for c in p.chapters if c.index <= len(outline.chapters)]
        for c in p.chapters:
            for co in outline.chapters:
                if co.index == c.index and c.status == "empty":
                    c.title = co.title
    if ctx:
        ctx.progress(1.0, "大纲生成完成")
    return outline


# ---------------------------------------------------------------------------
# 章节
# ---------------------------------------------------------------------------


def _tail(text: str, n: int = 400) -> str:
    text = text.strip()
    return text[-n:] if len(text) > n else text


def _clean_chapter_text(text: str) -> str:
    text = text.strip()
    # 去掉模型可能加上的「第X章 标题」首行
    lines = text.split("\n")
    if lines and re.match(r"^\s*(第[一二三四五六七八九十百零\d]+章|Chapter\s*\d+)", lines[0]) and len(lines[0]) < 40:
        lines = lines[1:]
    text = "\n".join(lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


async def generate_chapter(store: ProjectStore, llm: LLMProvider, project_id: str, chapter_index: int, ctx: Optional[JobContext] = None, humanize: bool = False) -> Chapter:
    project = store.load(project_id)
    if not project.outline:
        raise ValueError("请先生成大纲")
    project.ensure_chapters()
    sp = _resolved(project)
    settings = project.settings
    previous = [c.summary for c in project.chapters if c.index < chapter_index]
    prev_chapter = project.get_chapter(chapter_index - 1)
    prev_tail = _tail(prev_chapter.text or prev_chapter.draft_text) if prev_chapter else ""
    if ctx:
        ctx.progress(0.1, f"正在撰写第 {chapter_index} 章初稿（{llm.name}）…")
    raw = await llm.complete(
        sp["chapter_system"],
        P.chapter_user(settings, project.outline, chapter_index, previous, prev_tail),
        temperature=0.85,
        max_tokens=8000,
        tag="chapter",
        hints={"words": settings.words_per_chapter, "chapter_index": chapter_index},
    )
    draft = _clean_chapter_text(raw)
    if ctx:
        ctx.progress(0.6, f"第 {chapter_index} 章初稿完成（{len(draft)} 字），正在生成前情摘要…")
    summary = await summarize_text(llm, chapter_index, draft)
    async with store.edit(project_id) as p:
        p.ensure_chapters()
        ch = p.get_chapter(chapter_index)
        if ch is None:
            ch = Chapter(index=chapter_index)
            p.chapters.append(ch)
            p.chapters.sort(key=lambda c: c.index)
        co = next((c for c in p.outline.chapters if c.index == chapter_index), None) if p.outline else None
        ch.title = (co.title if co else ch.title) or f"第{chapter_index}章"
        ch.draft_text = draft
        ch.text = draft
        ch.summary = summary
        ch.status = "drafted"
        result = ch
    if humanize:
        result = await humanize_chapter(store, llm, project_id, chapter_index, ctx)
    elif ctx:
        ctx.progress(1.0, f"第 {chapter_index} 章完成")
    return result


async def summarize_text(llm: LLMProvider, chapter_index: int, text: str) -> str:
    sp = P.defaults()
    raw = await llm.complete(sp["summary_system"], P.summary_user(chapter_index, text[:6000]), temperature=0.3, max_tokens=800, tag="summary")
    return raw.strip()


def split_for_rewrite(text: str, max_chars: int = MAX_HUMANIZE_CHUNK) -> List[str]:
    paras = [p for p in text.split("\n")]
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for p in paras:
        if cur and cur_len + len(p) + 1 > max_chars:
            chunks.append("\n".join(cur))
            cur, cur_len = [], 0
        cur.append(p)
        cur_len += len(p) + 1
    if cur:
        chunks.append("\n".join(cur))
    return [c for c in chunks if c.strip()] or [text]


async def humanize_chapter(store: ProjectStore, llm: LLMProvider, project_id: str, chapter_index: int, ctx: Optional[JobContext] = None, source: str = "current") -> Chapter:
    """去 AI 味改写。source=current 基于当前正文；source=draft 基于初稿重来。"""
    project = store.load(project_id)
    ch = project.get_chapter(chapter_index)
    if ch is None or not (ch.text or ch.draft_text):
        raise ValueError("本章还没有正文，请先生成初稿")
    sp = _resolved(project)
    base_text = ch.draft_text if source == "draft" and ch.draft_text else (ch.text or ch.draft_text)
    chunks = split_for_rewrite(base_text)
    out: List[str] = []
    for i, chunk in enumerate(chunks):
        if ctx:
            ctx.progress(0.6 + 0.35 * i / max(1, len(chunks)), f"第 {chapter_index} 章去 AI 味改写 {i + 1}/{len(chunks)}…")
        raw = await llm.complete(sp["humanize_system"], P.humanize_user(chunk, project.settings), temperature=0.9, max_tokens=8000, tag="humanize")
        out.append(_clean_chapter_text(raw))
    new_text = "\n\n".join(out)
    async with store.edit(project_id) as p:
        c = p.get_chapter(chapter_index)
        assert c is not None
        c.text = new_text
        c.status = "humanized"
        result = c
    if ctx:
        ctx.progress(1.0, f"第 {chapter_index} 章改写完成（{len(new_text)} 字）")
    return result


async def generate_all_chapters(store: ProjectStore, llm: LLMProvider, project_id: str, ctx: JobContext, humanize: bool = True, only_missing: bool = True) -> dict:
    project = store.load(project_id)
    if not project.outline:
        raise ValueError("请先生成大纲")
    project.ensure_chapters()
    store.save(project)
    indices = [c.index for c in project.chapters if not only_missing or c.status == "empty"]
    done = []
    for n, idx in enumerate(indices):
        ctx.progress(n / max(1, len(indices)), f"章节 {idx}/{len(project.chapters)} 开始…")
        await generate_chapter(store, llm, project_id, idx, ctx=None, humanize=humanize)
        done.append(idx)
        ctx.check_cancelled()
    ctx.progress(1.0, f"已完成 {len(done)} 章")
    return {"chapters": done}
