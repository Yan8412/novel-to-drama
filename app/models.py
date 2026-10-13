"""项目数据模型。整个项目状态保存为一个 project.json（每个项目一个文件夹）。"""
from __future__ import annotations

import time
import uuid
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def now_ts() -> float:
    return time.time()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ---------------- 设定 ----------------


class Character(BaseModel):
    name: str
    role: str = ""  # 主角 / 反派 / 配角 ...
    gender: str = ""
    age: str = ""
    traits: str = ""  # 性格
    appearance: str = ""  # 外貌
    relationships: str = ""  # 与其他角色的关系
    background: str = ""


class StylePrompts(BaseModel):
    """可编辑的风格/系统提示词。空字符串表示使用默认值。"""

    outline_system: str = ""
    chapter_system: str = ""
    humanize_system: str = ""  # 去 AI 味
    summary_system: str = ""
    visual_system: str = ""
    image_style_suffix: str = ""  # 拼接到所有图片提示词末尾的统一画风
    video_style_suffix: str = ""


class NovelSettings(BaseModel):
    title: str = ""
    genre: str = "都市情感"
    premise: str = ""  # 一句话故事梗概 / 创意
    tone: str = ""  # 基调：爽、虐、悬疑...
    characters: List[Character] = Field(default_factory=list)
    target_word_count: int = 20000
    chapter_count: int = 10
    chapters_per_episode: int = 1
    shots_per_chapter: int = 8
    shot_duration_sec: int = 5  # 5 或 10
    aspect_ratio: str = "16:9"  # 16:9 横屏 / 9:16 竖屏
    style_prompts: StylePrompts = Field(default_factory=StylePrompts)

    @property
    def words_per_chapter(self) -> int:
        return max(300, self.target_word_count // max(1, self.chapter_count))


# ---------------- 大纲 / 章节 ----------------


class ChapterOutline(BaseModel):
    index: int
    title: str
    summary: str = ""
    key_events: List[str] = Field(default_factory=list)
    characters: List[str] = Field(default_factory=list)
    hook: str = ""  # 章末钩子


class Outline(BaseModel):
    title: str = ""
    logline: str = ""
    synopsis: str = ""
    world_setting: str = ""
    character_bible: str = ""  # 角色圣经（供后续章节保持一致）
    chapters: List[ChapterOutline] = Field(default_factory=list)


ChapterStatus = Literal["empty", "drafted", "humanized"]


class Chapter(BaseModel):
    index: int
    title: str = ""
    draft_text: str = ""  # 初稿
    text: str = ""  # 当前（去 AI 味后的）正文
    summary: str = ""  # 本章摘要（用于后续章节的滚动摘要）
    status: ChapterStatus = "empty"

    @property
    def word_count(self) -> int:
        return len((self.text or self.draft_text or "").replace("\n", "").replace(" ", ""))


# ---------------- 视觉 / 分镜 ----------------


class Asset(BaseModel):
    id: str = Field(default_factory=lambda: new_id("as_"))
    kind: Literal["image", "video"] = "image"
    path: str  # 相对于项目目录的路径，例如 assets/images/xxx.png
    provider: str = ""
    model: str = ""
    prompt: str = ""
    created_at: float = Field(default_factory=now_ts)
    meta: Dict = Field(default_factory=dict)


class VisualItem(BaseModel):
    """角色设定图 / 场景图 / 道具图 的统一结构。"""

    id: str = Field(default_factory=lambda: new_id("vi_"))
    name: str
    description: str = ""
    image_prompt: str = ""
    asset: Optional[Asset] = None


class Shot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sh_"))
    index: int
    scene: str = ""  # 场景名
    characters: List[str] = Field(default_factory=list)
    action: str = ""  # 画面内容 / 表演
    dialogue: str = ""
    camera: str = ""  # 景别、运镜
    duration_sec: int = 5
    image_prompt: str = ""  # 分镜首帧图提示词
    video_prompt: str = ""  # 图生视频提示词
    image: Optional[Asset] = None
    video: Optional[Asset] = None


class ChapterVisuals(BaseModel):
    chapter_index: int
    scenes: List[VisualItem] = Field(default_factory=list)
    props: List[VisualItem] = Field(default_factory=list)
    shots: List[Shot] = Field(default_factory=list)
    notes: str = ""


# ---------------- 剧集 ----------------

EpisodeStatus = Literal["pending", "videos_partial", "videos_done", "rendered"]


class Episode(BaseModel):
    index: int
    title: str = ""
    chapter_indices: List[int] = Field(default_factory=list)
    video: Optional[Asset] = None
    status: EpisodeStatus = "pending"


# ---------------- 项目 ----------------


class Project(BaseModel):
    id: str = Field(default_factory=lambda: new_id("pj_"))
    name: str = "未命名项目"
    created_at: float = Field(default_factory=now_ts)
    updated_at: float = Field(default_factory=now_ts)
    settings: NovelSettings = Field(default_factory=NovelSettings)
    outline: Optional[Outline] = None
    chapters: List[Chapter] = Field(default_factory=list)
    character_sheets: List[VisualItem] = Field(default_factory=list)  # 全局角色设定图（跨章节复用）
    visuals: Dict[int, ChapterVisuals] = Field(default_factory=dict)  # 按章节
    episodes: List[Episode] = Field(default_factory=list)

    def get_chapter(self, index: int) -> Optional[Chapter]:
        for c in self.chapters:
            if c.index == index:
                return c
        return None

    def ensure_chapters(self) -> None:
        """根据大纲补齐章节占位。"""
        if not self.outline:
            return
        existing = {c.index for c in self.chapters}
        for co in self.outline.chapters:
            if co.index not in existing:
                self.chapters.append(Chapter(index=co.index, title=co.title))
        self.chapters.sort(key=lambda c: c.index)
        for c in self.chapters:
            if not c.title:
                for co in self.outline.chapters:
                    if co.index == c.index:
                        c.title = co.title

    def get_visuals(self, chapter_index: int) -> Optional[ChapterVisuals]:
        return self.visuals.get(chapter_index) or self.visuals.get(str(chapter_index))  # type: ignore[arg-type]

    def set_visuals(self, v: ChapterVisuals) -> None:
        self.visuals.pop(str(v.chapter_index), None)  # type: ignore[arg-type]
        self.visuals[v.chapter_index] = v

    def get_episode(self, index: int) -> Optional[Episode]:
        for e in self.episodes:
            if e.index == index:
                return e
        return None

    def summary_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "genre": self.settings.genre,
            "chapter_count": self.settings.chapter_count,
            "has_outline": self.outline is not None,
            "chapters_done": sum(1 for c in self.chapters if c.status != "empty"),
            "episodes_rendered": sum(1 for e in self.episodes if e.status == "rendered"),
        }


# ---------------- 任务 ----------------


class JobInfo(BaseModel):
    id: str
    project_id: str
    kind: str
    status: Literal["pending", "running", "done", "failed", "cancelled"] = "pending"
    progress: float = 0.0
    message: str = ""
    logs: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    result: Optional[dict] = None
    created_at: float = Field(default_factory=now_ts)
    finished_at: Optional[float] = None
