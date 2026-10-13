"""视觉方案：角色设定图提示词（全局复用）、每章场景/道具/分镜/视频提示词。"""
from __future__ import annotations

from typing import Dict, List, Optional

from .. import prompts as P
from ..jobs import JobContext
from ..models import ChapterVisuals, Project, Shot, VisualItem
from ..providers.base import LLMProvider
from ..storage import ProjectStore
from .llm_json import as_str_list, extract_json


def _style(project: Project) -> dict:
    return P.resolve(project.settings.style_prompts)


def with_suffix(prompt: str, suffix: str) -> str:
    prompt = (prompt or "").strip().rstrip("，,。")
    if not suffix or suffix in prompt:
        return prompt
    # 去掉提示词里已经出现过的后缀片段，避免重复
    parts = [p.strip() for p in suffix.replace(",", "，").split("，") if p.strip() and p.strip() not in prompt]
    if not parts:
        return prompt
    return f"{prompt}，{'，'.join(parts)}"


# ---------------------------------------------------------------------------
# 角色设定图
# ---------------------------------------------------------------------------


def character_keys(project: Project) -> Dict[str, str]:
    """角色名 -> 外貌关键词（用于分镜提示词复述）。"""
    keys: Dict[str, str] = {}
    for item in project.character_sheets:
        keys[item.name] = item.description or item.image_prompt
    for c in project.settings.characters:
        keys.setdefault(c.name, c.appearance or c.traits)
    return keys


async def generate_character_sheets(store: ProjectStore, llm: LLMProvider, project_id: str, ctx: Optional[JobContext] = None) -> List[VisualItem]:
    project = store.load(project_id)
    if not project.outline:
        raise ValueError("请先生成大纲")
    sp = _style(project)
    if ctx:
        ctx.progress(0.1, "正在生成角色设定图提示词…")
    raw = await llm.complete(P.CHARACTER_SHEET_SYSTEM, P.character_sheet_user(project.settings, project.outline), json_mode=True, temperature=0.7, max_tokens=4000, tag="character_sheet")
    data = extract_json(raw)
    chars = data.get("characters") if isinstance(data, dict) else data
    items: List[VisualItem] = []
    for c in chars or []:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        items.append(
            VisualItem(
                name=str(c["name"]).strip(),
                description=str(c.get("appearance_key") or "").strip(),
                image_prompt=with_suffix(str(c.get("image_prompt") or ""), sp["image_style_suffix"]),
            )
        )
    async with store.edit(project_id) as p:
        # 保留已生成的图片（按角色名匹配）
        old = {i.name: i for i in p.character_sheets}
        for it in items:
            if it.name in old and old[it.name].asset:
                it.asset = old[it.name].asset
        p.character_sheets = items
    if ctx:
        ctx.progress(1.0, f"已生成 {len(items)} 个角色的设定图提示词")
    return items


# ---------------------------------------------------------------------------
# 每章视觉方案
# ---------------------------------------------------------------------------


def parse_visual_plan(data: dict, chapter_index: int, default_duration: int, image_suffix: str, video_suffix: str, keys: Dict[str, str]) -> ChapterVisuals:
    def items(key: str) -> List[VisualItem]:
        out: List[VisualItem] = []
        for it in data.get(key) or []:
            if isinstance(it, dict) and it.get("name"):
                out.append(VisualItem(name=str(it["name"]), description=str(it.get("description") or ""), image_prompt=with_suffix(str(it.get("image_prompt") or ""), image_suffix)))
        return out

    shots: List[Shot] = []
    for i, s in enumerate(data.get("shots") or [], start=1):
        if not isinstance(s, dict):
            continue
        try:
            dur = int(s.get("duration_sec") or default_duration)
        except Exception:
            dur = default_duration
        dur = 10 if dur >= 8 else 5
        chars = as_str_list(s.get("characters"))
        image_prompt = str(s.get("image_prompt") or s.get("action") or "")
        # 确保角色外貌关键词出现在提示词中（一致性兜底）
        for name in chars:
            key = keys.get(name)
            if key and key[:12] not in image_prompt:
                image_prompt = f"{name}（{key}），{image_prompt}"
        shots.append(
            Shot(
                index=i,
                scene=str(s.get("scene") or ""),
                characters=chars,
                action=str(s.get("action") or ""),
                dialogue=str(s.get("dialogue") or ""),
                camera=str(s.get("camera") or ""),
                duration_sec=dur,
                image_prompt=with_suffix(image_prompt, image_suffix),
                video_prompt=with_suffix(str(s.get("video_prompt") or s.get("action") or ""), video_suffix),
            )
        )
    return ChapterVisuals(chapter_index=chapter_index, scenes=items("scenes"), props=items("props"), shots=shots, notes=str(data.get("notes") or ""))


async def generate_visual_plan(store: ProjectStore, llm: LLMProvider, project_id: str, chapter_index: int, ctx: Optional[JobContext] = None) -> ChapterVisuals:
    project = store.load(project_id)
    ch = project.get_chapter(chapter_index)
    if not project.outline or ch is None or not (ch.text or ch.draft_text):
        raise ValueError("本章还没有正文，请先生成章节")
    sp = _style(project)
    keys = character_keys(project)
    if ctx:
        ctx.progress(0.1, f"正在为第 {chapter_index} 章生成分镜与提示词（{llm.name}）…")
    raw = await llm.complete(
        sp["visual_system"],
        P.visual_user(project.settings, project.outline, chapter_index, ch.title, (ch.text or ch.draft_text)[:12000], keys),
        json_mode=True,
        temperature=0.7,
        max_tokens=8000,
        tag="visual",
        hints={"shots": project.settings.shots_per_chapter, "chapter_index": chapter_index},
    )
    plan = parse_visual_plan(extract_json(raw), chapter_index, project.settings.shot_duration_sec, sp["image_style_suffix"], sp["video_style_suffix"], keys)
    if not plan.shots:
        raise ValueError("模型没有返回任何分镜，请重试或调整提示词")
    async with store.edit(project_id) as p:
        p.set_visuals(plan)
    if ctx:
        ctx.progress(1.0, f"第 {chapter_index} 章：{len(plan.scenes)} 个场景、{len(plan.props)} 个道具、{len(plan.shots)} 个镜头")
    return plan


async def generate_all_visual_plans(store: ProjectStore, llm: LLMProvider, project_id: str, ctx: JobContext, only_missing: bool = True) -> dict:
    project = store.load(project_id)
    targets = [c.index for c in project.chapters if c.status != "empty" and (not only_missing or project.get_visuals(c.index) is None)]
    for n, idx in enumerate(targets):
        ctx.progress(n / max(1, len(targets)), f"分镜 {idx}…")
        await generate_visual_plan(store, llm, project_id, idx, ctx=None)
        ctx.check_cancelled()
    ctx.progress(1.0, f"已完成 {len(targets)} 章分镜")
    return {"chapters": targets}
