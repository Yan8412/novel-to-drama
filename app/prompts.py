"""默认提示词（简体中文）。项目设置中的 style_prompts 可覆盖这里的任意一条。"""
from __future__ import annotations

from typing import List

from .models import Character, NovelSettings, Outline, StylePrompts

# ---------------------------------------------------------------------------
# 系统提示词（可在界面中编辑）
# ---------------------------------------------------------------------------

OUTLINE_SYSTEM = """你是一位资深的网络小说与短剧编剧，擅长节奏紧凑、冲突强烈、每章有钩子的商业故事。
你的任务：根据用户给出的题材、人物与篇幅要求，产出完整的小说大纲。
要求：
1. 故事要有清晰的主线冲突、阶段性反转和高潮，结局要有收束。
2. 每一章都要有明确的事件推进和章末钩子，适合改编为一集短剧。
3. 人物行为必须符合其性格设定，关系要有张力。
4. 输出必须是合法 JSON，不要输出任何解释文字、不要用 markdown 代码块包裹。"""

CHAPTER_SYSTEM = """你是一位文笔老练的中文小说作者，正在逐章撰写一部长篇小说。
写作要求：
1. 严格依据给定的大纲、角色圣经和前情摘要写作，不得与已有设定冲突，不得擅自改动人物名字和关系。
2. 以场景和对话推进情节，多用动作、细节和对白，少用总结性叙述。
3. 对白要口语化、符合人物身份，带有情绪和潜台词。
4. 保持悬念，章末留下钩子，但不要写「预知后事如何」之类套话。
5. 只输出正文，不要输出章节标题、标注、总结或任何解释。
6. 字数尽量接近要求，不要大幅偏离。"""

HUMANIZE_SYSTEM = """你是一位文学编辑，任务是把一段 AI 生成的小说正文改写成「像真人作者写的」文字。保持剧情、人物、对白内容和顺序完全不变，只改表达。
改写原则：
1. 句长要有节奏：长短句交错，允许短促的一句话段落，避免每句都是整齐的中等长度复合句。
2. 用具体、可感知的细节代替抽象概括：声音、气味、温度、光线、触感、小动作。
3. 对白口语化：有省略、有打断、有停顿和语气词，不要每句话都说得完整漂亮；人物说话方式要有区分。
4. 删掉 AI 腔调：不要「仿佛在诉说着」「不禁」「心中五味杂陈」「空气仿佛凝固」「一丝不易察觉的」「深邃的眼眸」「宛如」「犹如」「不知为何」「与此同时」「值得一提的是」「总而言之」等套话；少用排比和「……的……」连环定语。
5. 段落结尾不要点题、不要总结、不要升华、不要写「她知道，一切都不一样了」这种概括式收尾；用动作或一句对白收尾。
6. 减少副词和形容词堆砌，优先用动词。少用感叹号与省略号。
7. 允许偶尔的不完美：口语、俏皮话、地方化表达、人物的小毛病。
8. 不要增加新情节，不要删减关键信息，不要改变人称和时态。
只输出改写后的正文，不要任何说明。"""

SUMMARY_SYSTEM = """你是一位小说编辑助理。请把给定章节压缩成 150~250 字的「前情摘要」，用于指导后续章节写作。
必须包含：发生了哪些关键事件、人物关系有什么变化、留下了哪些伏笔/悬念、人物当前所处的地点与状态。
只输出摘要正文，不要标题和解释。"""

VISUAL_SYSTEM = """你是一位短剧导演兼 AI 绘画/视频提示词工程师。任务：阅读一章小说，为其制作可直接用于 AI 图片生成和图生视频的拍摄方案。
通用要求：
1. 所有提示词用中文书写，具体、画面化、可执行，描述构图、人物、动作、表情、服装、环境、光线、镜头。
2. 角色外貌必须与给定的「角色设定」完全一致（发型、发色、服装、体型、标志性特征），每个涉及该角色的提示词都要复述其关键外貌特征，保证跨镜头一致。
3. 分镜（shots）按剧情顺序排列，每个镜头是一张首帧图 + 一段图生视频，时长固定为给定秒数；镜头要能连起来讲清楚本章故事，优先选择最有戏剧张力的时刻。
4. image_prompt 描述静止画面（首帧）；video_prompt 描述这几秒内的动作、镜头运动和情绪变化，开头可以写镜头运动方式（推、拉、摇、移、跟、固定）。
5. 不要在提示词里出现人名之外的抽象描述（如「他很伤心」），改为可见的表现（如「眼眶发红，攥紧拳头」）。
6. 输出必须是合法 JSON，不要用 markdown 代码块包裹，不要输出解释。"""

CHARACTER_SHEET_SYSTEM = """你是一位角色设定画师兼 AI 绘画提示词工程师。请为每个角色撰写一段用于生成「角色设定图」的中文提示词。
要求：
1. 每个角色一段，描述清楚：性别、年龄感、发型发色、脸型与五官特征、身材、常穿服装（含颜色与材质）、标志性配饰、气质。
2. 提示词应为「全身立绘、正面、中性表情、纯色背景、角色设定图」风格，便于后续作为参考。
3. 外貌描述要足够具体并且稳定，后续所有分镜都会复述这段描述来保证一致性。
4. 输出必须是合法 JSON：{"characters":[{"name":"角色名","appearance_key":"用于复述的 30~60 字关键外貌","image_prompt":"完整提示词"}]}，不要用 markdown 代码块包裹。"""

IMAGE_STYLE_SUFFIX = "电影感真人短剧画面，写实风格，高细节，自然光影，电影级调色，8k，构图干净"
VIDEO_STYLE_SUFFIX = "真人短剧质感，动作自然流畅，镜头稳定，画面无文字无水印"


def resolve(sp: StylePrompts) -> dict:
    """合并用户自定义与默认提示词。"""
    return {
        "outline_system": sp.outline_system or OUTLINE_SYSTEM,
        "chapter_system": sp.chapter_system or CHAPTER_SYSTEM,
        "humanize_system": sp.humanize_system or HUMANIZE_SYSTEM,
        "summary_system": sp.summary_system or SUMMARY_SYSTEM,
        "visual_system": sp.visual_system or VISUAL_SYSTEM,
        "image_style_suffix": sp.image_style_suffix or IMAGE_STYLE_SUFFIX,
        "video_style_suffix": sp.video_style_suffix or VIDEO_STYLE_SUFFIX,
    }


def defaults() -> dict:
    return resolve(StylePrompts())


# ---------------------------------------------------------------------------
# 用户提示词模板
# ---------------------------------------------------------------------------


def format_characters(chars: List[Character]) -> str:
    if not chars:
        return "（用户未指定人物，请你自行设计 3~5 个主要人物）"
    lines = []
    for c in chars:
        parts = [f"【{c.name}】"]
        if c.role:
            parts.append(f"定位：{c.role}")
        if c.gender:
            parts.append(f"性别：{c.gender}")
        if c.age:
            parts.append(f"年龄：{c.age}")
        if c.traits:
            parts.append(f"性格：{c.traits}")
        if c.appearance:
            parts.append(f"外貌：{c.appearance}")
        if c.relationships:
            parts.append(f"关系：{c.relationships}")
        if c.background:
            parts.append(f"背景：{c.background}")
        lines.append("；".join(parts))
    return "\n".join(lines)


def outline_user(settings: NovelSettings) -> str:
    return f"""请为下面这部小说生成大纲。

题材：{settings.genre}
书名（可为空，为空请你拟一个）：{settings.title or "（待定）"}
故事创意/梗概：{settings.premise or "（无，请你根据题材和人物自行构思）"}
基调：{settings.tone or "（不限）"}
总字数：约 {settings.target_word_count} 字
章节数：{settings.chapter_count} 章（每章约 {settings.words_per_chapter} 字）

人物设定：
{format_characters(settings.characters)}

请输出如下结构的 JSON（字段名必须完全一致）：
{{
  "title": "书名",
  "logline": "一句话故事",
  "synopsis": "300~500字的完整故事梗概，交代起承转合与结局",
  "world_setting": "时代、地点、社会背景、规则等设定，100~300字",
  "character_bible": "角色圣经：逐个人物写明姓名、身份、性格、外貌、口头禅/说话风格、核心欲望、与他人关系、在故事中的弧光。每人 80~150 字。",
  "chapters": [
    {{
      "index": 1,
      "title": "章节标题",
      "summary": "本章剧情 120~200 字，写清发生了什么、在哪里、谁参与",
      "key_events": ["事件1", "事件2", "事件3"],
      "characters": ["出场人物名"],
      "hook": "章末钩子一句话"
    }}
  ]
}}
chapters 数组必须恰好有 {settings.chapter_count} 项，index 从 1 开始连续编号。"""


def chapter_user(
    settings: NovelSettings,
    outline: Outline,
    chapter_index: int,
    previous_summaries: List[str],
    prev_tail: str,
) -> str:
    co = next((c for c in outline.chapters if c.index == chapter_index), None)
    total = len(outline.chapters)
    co_text = (
        f"标题：{co.title}\n剧情：{co.summary}\n关键事件：{'；'.join(co.key_events)}\n出场人物：{'、'.join(co.characters)}\n章末钩子：{co.hook}"
        if co
        else "（大纲中没有本章，请根据前文自然推进）"
    )
    prev = "\n".join(f"第{i + 1}章：{s}" for i, s in enumerate(previous_summaries) if s) or "（这是第一章，没有前情）"
    tail = f"\n\n上一章结尾的最后几段（用于衔接语气与场景）：\n{prev_tail}" if prev_tail else ""
    position = "这是全书第一章，需要迅速建立人物、处境与冲突。" if chapter_index == 1 else (
        "这是全书最后一章，需要完成高潮并收束所有主要线索。" if chapter_index == total else ""
    )
    return f"""书名：《{outline.title or settings.title}》
题材：{settings.genre}；基调：{settings.tone or "不限"}

【故事梗概】
{outline.synopsis}

【世界设定】
{outline.world_setting}

【角色圣经】
{outline.character_bible}

【前情摘要】
{prev}{tail}

【本章大纲】第 {chapter_index} 章 / 共 {total} 章
{co_text}
{position}

请撰写第 {chapter_index} 章正文，约 {settings.words_per_chapter} 字。只输出正文。"""


def humanize_user(text: str, settings: NovelSettings) -> str:
    return f"""题材：{settings.genre}；基调：{settings.tone or "不限"}

下面是需要改写的正文（保持字数大致不变，允许 ±15%）：

{text}"""


def summary_user(chapter_index: int, text: str) -> str:
    return f"第 {chapter_index} 章正文如下，请输出前情摘要：\n\n{text}"


def character_sheet_user(settings: NovelSettings, outline: Outline) -> str:
    return f"""题材：{settings.genre}
角色圣经：
{outline.character_bible}

用户给出的人物设定：
{format_characters(settings.characters)}

请为上述所有主要角色（至少包含用户给出的每一位）生成角色设定图提示词。"""


def visual_user(
    settings: NovelSettings,
    outline: Outline,
    chapter_index: int,
    chapter_title: str,
    chapter_text: str,
    character_keys: dict,
) -> str:
    keys = "\n".join(f"- {name}：{key}" for name, key in character_keys.items()) or "（暂无角色设定，请根据正文自行描述并保持一致）"
    return f"""书名：《{outline.title or settings.title}》 题材：{settings.genre}
画幅：{settings.aspect_ratio}；每个镜头时长：{settings.shot_duration_sec} 秒；镜头数量：约 {settings.shots_per_chapter} 个

【角色设定（必须在每个提示词中复述对应角色的外貌关键词）】
{keys}

【第 {chapter_index} 章《{chapter_title}》正文】
{chapter_text}

请输出如下 JSON（字段名必须完全一致）：
{{
  "scenes": [
    {{"name": "场景名", "description": "场景在剧情中的作用", "image_prompt": "空镜场景图提示词：地点、时间、天气、光线、陈设、氛围，不含人物"}}
  ],
  "props": [
    {{"name": "道具名", "description": "道具的剧情意义", "image_prompt": "道具特写图提示词：材质、颜色、细节、摆放环境、光线"}}
  ],
  "shots": [
    {{
      "index": 1,
      "scene": "所属场景名",
      "characters": ["出场角色名"],
      "action": "画面中发生的事（供人阅读）",
      "dialogue": "本镜头的台词（可为空）",
      "camera": "景别与运镜，如：中景，缓慢推镜",
      "duration_sec": {settings.shot_duration_sec},
      "image_prompt": "首帧图提示词：复述角色外貌关键词 + 动作表情 + 服装 + 环境 + 光线 + 景别",
      "video_prompt": "图生视频提示词：这{settings.shot_duration_sec}秒内的动作、表情变化、镜头运动"
    }}
  ]
}}
scenes 2~5 个，props 1~4 个，shots 约 {settings.shots_per_chapter} 个，index 从 1 连续编号。"""
