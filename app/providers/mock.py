"""模拟厂商：不需要任何密钥，可完整跑通「小说 -> 剧集视频」流程。
- MockLLM：根据任务标签返回结构正确的中文内容。
- MockImage：用 Pillow 画一张带文字的占位图。
- MockVideo：用 ffmpeg 把首帧图做成几秒钟的视频（与真实流程使用相同的拼接链路）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from .base import ImageProvider, LLMProvider, MediaResult, ProgressCb, ProviderError, VideoProvider, aspect_to_size

# ---------------------------------------------------------------------------
# 文本
# ---------------------------------------------------------------------------

_PLACES = ["老城区的巷口", "医院走廊尽头", "江边的旧仓库", "公司顶楼天台", "深夜的便利店", "雨后的学校操场", "出租屋的厨房", "高铁站候车厅"]
_OBJECTS = ["一枚褪色的铜钥匙", "半杯凉透的茶", "贴着便签的旧手机", "被雨淋湿的信封", "缺了一角的相框", "一张皱巴巴的车票"]
_WEATHER = ["天阴着", "雨刚停", "太阳很毒", "起风了", "雾还没散", "夜色压下来"]


def _seed_from(*parts: str) -> random.Random:
    h = hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()
    return random.Random(int(h[:8], 16))


def _extract_names(user_prompt: str) -> List[str]:
    names = re.findall(r"【([^】]{1,8})】", user_prompt)
    seen: List[str] = []
    for n in names:
        if n not in seen and n not in ("故事梗概", "世界设定", "角色圣经", "前情摘要", "本章大纲", "角色设定（必须在每个提示词中复述对应角色的外貌关键词）"):
            seen.append(n)
    return seen


def _default_names(user_prompt: str) -> List[str]:
    names = _extract_names(user_prompt)
    if not names:
        # 尝试从「角色设定」行中提取 "- 名字："
        names = re.findall(r"^- ([^：:\n]{1,8})[：:]", user_prompt, flags=re.M)
    if not names:
        names = ["林晚", "顾言", "周叔"]
    return names[:6]


def _int_hint(hints: Optional[dict], key: str, default: int) -> int:
    try:
        return int((hints or {}).get(key, default))
    except Exception:
        return default


def _mock_outline(user: str, hints: Optional[dict]) -> str:
    rng = _seed_from("outline", user[:200])
    n = _int_hint(hints, "chapter_count", 0)
    if not n:
        m = re.search(r"恰好有 (\d+) 项", user)
        n = int(m.group(1)) if m else 6
    names = _default_names(user)
    hero, other = names[0], (names[1] if len(names) > 1 else "陌生人")
    m = re.search(r"题材：(.+)", user)
    genre = m.group(1).strip() if m else "都市"
    m = re.search(r"书名（可为空，为空请你拟一个）：(.+)", user)
    title = m.group(1).strip() if m and "待定" not in m.group(1) else f"{hero}的第七个夜晚"
    chapters = []
    for i in range(1, n + 1):
        place = _PLACES[(i + rng.randint(0, 3)) % len(_PLACES)]
        obj = _OBJECTS[(i * 3) % len(_OBJECTS)]
        chapters.append(
            {
                "index": i,
                "title": f"第{i}章 {place}的{['相遇', '秘密', '对峙', '裂痕', '回声', '抉择', '代价', '黎明'][(i - 1) % 8]}",
                "summary": f"{hero}在{place}遇到{other}，因为{obj}卷入一桩旧事。两人从互相试探到不得不合作，{hero}发现对方隐瞒了关键信息，矛盾在章末爆发。",
                "key_events": [f"{hero}找到{obj}", f"{other}说出一半真相", f"{place}发生意外"],
                "characters": names[: min(len(names), 2 + (i % 2))],
                "hook": f"{other}留下一句话转身离开：‘明天之前，别回{place}。’",
            }
        )
    bible = "\n".join(
        f"{nm}：{['三十岁上下，外冷内热，说话短促', '二十五六岁，笑起来有酒窝，习惯用反问句', '五十多岁，烟嗓，说话慢，爱讲道理'][idx % 3]}；核心欲望是{['弄清父亲失踪的真相', '保住自己的秘密', '让街坊安稳过日子'][idx % 3]}；与{names[(idx + 1) % len(names)]}关系紧张。"
        for idx, nm in enumerate(names)
    )
    data = {
        "title": title,
        "logline": f"一个关于{genre}的故事：{hero}为了弄清一件旧事，与{other}在{_PLACES[rng.randint(0, len(_PLACES) - 1)]}纠缠了七天。",
        "synopsis": f"{hero}原本过着按部就班的生活，直到{obj}出现在家门口。为了查清来历，{hero}找到了唯一知情的{other}。两人从互不信任到被迫合作，一路揭开多年前被掩盖的真相。中段{other}的秘密暴露，两人决裂；{hero}独自面对危险，最终在{other}的回头相助下化解危机。结局{hero}放下执念，{other}补偿了自己的过错，两人在清晨的街口各自走向新的生活。",
        "world_setting": f"当代中国南方小城，{genre}背景。老城区正在拆迁，新旧交替，人情复杂。故事大部分发生在一周之内。",
        "character_bible": bible,
        "chapters": chapters,
    }
    return json.dumps(data, ensure_ascii=False)


def _mock_chapter(user: str, hints: Optional[dict]) -> str:
    m = re.search(r"约 (\d+) 字", user)
    words = _int_hint(hints, "words", int(m.group(1)) if m else 800)
    m = re.search(r"第 (\d+) 章 / 共", user)
    idx = int(m.group(1)) if m else 1
    rng = _seed_from("chapter", str(idx), user[:120])
    names = _default_names(user)
    hero, other = names[0], (names[1] if len(names) > 1 else "那个人")
    place = _PLACES[idx % len(_PLACES)]
    obj = _OBJECTS[idx % len(_OBJECTS)]
    weather = _WEATHER[idx % len(_WEATHER)]
    paras = [
        f"{weather}。{hero}站在{place}，手里攥着{obj}，指节发白。",
        f"“你来晚了。”{other}靠在墙边，没有看{hero}，声音像是从很远的地方传过来的。",
        f"{hero}没有接话。巷子里传来谁家炒菜的声音，油烟味混着潮气，闷得人喘不过气。",
        f"“这东西是我爸的。”{hero}把{obj}举起来，“你认识它。”",
        f"{other}终于转过头来，眼神在那上面停了两秒，然后笑了一下。那笑容让{hero}心里一沉。",
        f"“认识又怎么样？”{other}说，“有些事，知道了反而麻烦。”",
        f"远处有车灯扫过来，又扫过去。{hero}往前走了一步，鞋底踩到一块松动的砖，咔哒一声。",
        f"“我不怕麻烦。”{hero}说，“我怕的是什么都不知道。”",
        f"{other}沉默了很久。久到{hero}以为对方不会再开口了。",
        f"“行。”{other}终于说，“明天早上六点，{_PLACES[(idx + 2) % len(_PLACES)]}。你一个人来。”",
        f"{hero}想问为什么，但{other}已经转身走进了巷子深处，背影很快被夜色吞掉。",
        f"{hero}低头看了看手里的{obj}。它在路灯下反着一点微弱的光，像是在提醒什么。",
    ]
    out: List[str] = []
    total = 0
    i = 0
    while total < words:
        p = paras[i % len(paras)]
        if i >= len(paras):
            p = p.replace("。", "。" if rng.random() < 0.7 else "……", 1)
        out.append(p)
        total += len(p)
        i += 1
    return "\n\n".join(out)


def _mock_humanize(user: str) -> str:
    # 取出「下面是需要改写的正文」之后的内容，做轻微改写以示区别
    body = user.split("：\n\n", 1)[-1] if "：\n\n" in user else user
    body = body.replace("仿佛", "像").replace("不禁", "").replace("与此同时", "这时候").replace("深邃", "黑沉沉")
    body = body.replace("，指节发白。", "。指节发白。")
    return body.strip()


def _mock_summary(user: str) -> str:
    names = _default_names(user)
    hero = names[0]
    m = re.search(r"第 (\d+) 章正文", user)
    idx = m.group(1) if m else "本"
    return (
        f"第{idx}章：{hero}带着线索物件与知情人正面接触，对方承认认识该物件但拒绝说明来历，"
        f"双方约定次日清晨在另一地点单独见面。悬念：知情人为何要求独自前来；{hero}手中的物件究竟指向什么。"
        f"人物状态：{hero}焦躁但下定决心；知情人态度暧昧、似有隐情。"
    )


def _mock_character_sheet(user: str) -> str:
    names = _default_names(user)
    given = {m.group(1): m.group(2).strip() for m in re.finditer(r"【([^】]{1,8})】[^\n]*?外貌：([^；\n]+)", user)}
    chars = []
    for i, nm in enumerate(names):
        key = given.get(nm) or ["三十岁左右男性，寸头，眉骨处有一道浅疤，深灰色夹克配黑色长裤，身材精瘦", "二十五岁左右女性，齐肩黑色直发，左耳一枚银色小耳钉，米白色针织衫配深蓝牛仔裤", "五十多岁男性，花白短发，下巴有胡茬，旧式藏青中山装，微驼背"][i % 3]
        chars.append(
            {
                "name": nm,
                "appearance_key": key,
                "image_prompt": f"角色设定图，{nm}，{key}，全身立绘，正面站立，中性表情，纯浅灰色背景，写实风格，柔和均匀光线，高细节",
            }
        )
    return json.dumps({"characters": chars}, ensure_ascii=False)


def _mock_visual(user: str, hints: Optional[dict]) -> str:
    m = re.search(r"镜头数量：约 (\d+) 个", user)
    shots_n = _int_hint(hints, "shots", int(m.group(1)) if m else 6)
    m = re.search(r"每个镜头时长：(\d+) 秒", user)
    dur = int(m.group(1)) if m else 5
    m = re.search(r"第 (\d+) 章", user)
    idx = int(m.group(1)) if m else 1
    names = _default_names(user)
    keys = dict(re.findall(r"^- ([^：\n]{1,8})：(.+)$", user, flags=re.M))
    hero, other = names[0], (names[1] if len(names) > 1 else "陌生人")
    hk = keys.get(hero, "三十岁左右男性，寸头，深灰色夹克")
    ok = keys.get(other, "二十五岁左右女性，齐肩黑发，米白色针织衫")
    place = _PLACES[idx % len(_PLACES)]
    obj = _OBJECTS[idx % len(_OBJECTS)]
    scenes = [
        {"name": place, "description": "本章主要对峙场景", "image_prompt": f"{place}，夜晚，刚下过雨的湿漉漉地面反射着昏黄路灯，墙皮斑驳，远处有霓虹灯，空镜，电影感，无人物"},
        {"name": "巷子深处", "description": "角色离开的方向，象征未知", "image_prompt": "狭窄老巷深处，昏暗，几扇紧闭的木门，一盏快要坏掉的灯泡忽明忽暗，空镜，压抑氛围"},
    ]
    props = [{"name": obj, "description": "贯穿全书的关键线索", "image_prompt": f"{obj}特写，放在粗糙的水泥台面上，侧面打来一束暖光，表面有使用痕迹，浅景深，微距摄影"}]
    actions = [
        (f"{hero}站在{place}，攥着{obj}，抬头看向镜头外", "中景，固定镜头", f"{hero}缓缓抬头，手指收紧，远处一辆车的灯光从他脸上扫过"),
        (f"{other}靠在斑驳的墙边，侧脸对着镜头，目光低垂", "近景，缓慢推镜", f"镜头缓慢推进，{other}的嘴角动了一下，像是要说什么又忍住"),
        (f"{hero}举起{obj}，对面的{other}眼神闪烁", "双人中景，过肩", f"{hero}把{obj}举到两人之间，{other}的视线落在上面停了两秒，笑了一下"),
        (f"{other}转身走进巷子深处，背影被夜色吞没", "全景，固定", f"{other}转身，脚步不快，身影一点点融进黑暗，路灯闪了一下"),
        (f"{hero}低头看着手中的{obj}，路灯在上面反着光", "特写，微微下摇", f"镜头从{hero}的脸缓慢下摇到手中的{obj}，光点在上面晃动"),
        (f"{place}空镜，一只猫从墙头跳下", "大全景，固定", "画面静止两秒，一只猫从墙头跳下，穿过积水，涟漪扩散"),
    ]
    shots = []
    for i in range(1, shots_n + 1):
        act, cam, vid = actions[(i - 1) % len(actions)]
        chars = [hero] if hero in act else []
        if other in act:
            chars.append(other)
        desc_parts = []
        if hero in chars:
            desc_parts.append(f"{hero}（{hk}）")
        if other in chars:
            desc_parts.append(f"{other}（{ok}）")
        shots.append(
            {
                "index": i,
                "scene": place if i != 4 else "巷子深处",
                "characters": chars,
                "action": act,
                "dialogue": ["", "你来晚了。", "这东西是我爸的。你认识它。", "明天早上六点。你一个人来。", "", ""][(i - 1) % 6],
                "camera": cam,
                "duration_sec": dur,
                "image_prompt": f"{'，'.join(desc_parts) + '，' if desc_parts else ''}{act}，{place}，夜晚雨后，昏黄路灯，{cam}，电影感真人短剧画面",
                "video_prompt": vid,
            }
        )
    return json.dumps({"scenes": scenes, "props": props, "shots": shots, "notes": "模拟模式生成的分镜，仅供走通流程"}, ensure_ascii=False)


class MockLLM(LLMProvider):
    name = "mock"
    model = "mock-llm"

    def __init__(self, delay: float = 0.05):
        self.delay = delay

    async def complete(self, system, user, *, json_mode=False, temperature=0.8, max_tokens=None, tag="", hints=None) -> str:
        await asyncio.sleep(self.delay)
        if tag == "outline":
            return _mock_outline(user, hints)
        if tag == "chapter":
            return _mock_chapter(user, hints)
        if tag == "humanize":
            return _mock_humanize(user)
        if tag == "summary":
            return _mock_summary(user)
        if tag == "character_sheet":
            return _mock_character_sheet(user)
        if tag == "visual":
            return _mock_visual(user, hints)
        if json_mode:
            return "{}"
        return "（模拟模式）" + user[:200]


# ---------------------------------------------------------------------------
# 图片
# ---------------------------------------------------------------------------

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/System/Library/Fonts/PingFang.ttc",
]


def _load_font(size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render_placeholder_image(text: str, width: int, height: int, label: str = "MOCK") -> bytes:
    """生成一张带文字的占位图（PNG）。"""
    import io

    from PIL import Image, ImageDraw

    rng = _seed_from(text)
    bg = (rng.randint(30, 90), rng.randint(40, 110), rng.randint(60, 140))
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)
    # 渐变条
    for y in range(height):
        shade = int(40 * y / height)
        draw.line([(0, y), (width, y)], fill=(min(255, bg[0] + shade), min(255, bg[1] + shade), min(255, bg[2] + shade)))
    font_big = _load_font(max(18, width // 24))
    font_small = _load_font(max(14, width // 48))
    draw.text((width * 0.04, height * 0.06), label, fill=(255, 255, 255), font=font_big)
    # 简单换行
    chars_per_line = max(10, int(width / (font_small.size * 1.05))) if hasattr(font_small, "size") else 30
    lines: List[str] = []
    for raw in text.split("\n"):
        while raw:
            lines.append(raw[:chars_per_line])
            raw = raw[chars_per_line:]
    y = height * 0.25
    line_h = (getattr(font_small, "size", 16) + 8)
    for line in lines[: int((height * 0.7) // line_h)]:
        draw.text((width * 0.04, y), line, fill=(235, 235, 235), font=font_small)
        y += line_h
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class MockImage(ImageProvider):
    name = "mock"
    model = "mock-image"

    def __init__(self, delay: float = 0.05):
        self.delay = delay

    async def generate(self, prompt, *, negative_prompt="", aspect_ratio="16:9", progress: ProgressCb = None) -> MediaResult:
        await asyncio.sleep(self.delay)
        w, h = aspect_to_size(aspect_ratio, 1280)
        data = await asyncio.to_thread(render_placeholder_image, prompt, w, h, "模拟图片 MOCK IMAGE")
        return MediaResult(data=data, ext="png", provider=self.name, model=self.model, meta={"mock": True})


# ---------------------------------------------------------------------------
# 视频
# ---------------------------------------------------------------------------


class MockVideo(VideoProvider):
    name = "mock"
    model = "mock-video"

    def __init__(self, ffmpeg_path: str = "ffmpeg", delay: float = 0.05):
        self.ffmpeg = ffmpeg_path
        self.delay = delay

    async def image_to_video(self, image_path: Path, prompt, *, duration_sec=5, aspect_ratio="16:9", negative_prompt="", progress: ProgressCb = None) -> MediaResult:
        await asyncio.sleep(self.delay)
        ffmpeg = shutil.which(self.ffmpeg) or self.ffmpeg
        if not Path(ffmpeg).exists() and not shutil.which(self.ffmpeg):
            raise ProviderError("未找到 ffmpeg，模拟视频无法生成。请安装 ffmpeg 并在 .env 中设置 FFMPEG_PATH。")
        w, h = aspect_to_size(aspect_ratio, 1280)
        # 模拟模式缩短时长以加快速度（最少 1 秒）
        dur = max(1, min(duration_sec, 2))
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.mp4"
            cmd = [
                ffmpeg, "-y", "-loglevel", "error",
                "-loop", "1", "-i", str(image_path),
                "-t", str(dur), "-r", "24",
                "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                str(out),
            ]
            proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise ProviderError(f"ffmpeg 生成模拟视频失败：{proc.stderr[-400:]}")
            data = out.read_bytes()
        return MediaResult(data=data, ext="mp4", provider=self.name, model=self.model, meta={"mock": True, "duration": dur})
