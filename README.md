# 小说转短剧 · novel-to-drama

把一个「题材 + 人物 + 篇幅」的想法，一步步变成**小说 → 分镜 → 图片 → 视频 → 每集成片**的本地工具。所有数据保存在本机，每一步都可以预览、修改、重新生成，再进入下一步。

```
① 小说设定 ─▶ ② 大纲 ─▶ ③ 逐章正文（含「去 AI 味」改写）
      ─▶ ④ 角色设定图 / 场景 / 道具 / 分镜 / 视频提示词（第二个模型）
      ─▶ ⑤ 图片生成 ─▶ ⑥ 按集手动生成视频 ─▶ ffmpeg 拼接成片
```

- 后端：Python 3.10+ / FastAPI；前端：零依赖的网页，浏览器打开即用；界面与生成内容均为简体中文。
- 厂商可插拔：文本 **DeepSeek**（默认）/ **通义千问**；图片 **通义万相** / **即梦**；视频 **可灵** / **即梦**。
- **模拟模式**：不需要任何密钥即可完整跑通「小说 → 剧集视频」流程，先熟悉再花钱。
- 费用可控：视频按集**手动触发**，执行前显示镜头数量、时长与预估费用；图片生成前同样有预估。

---

## 目录

1. [环境准备（Windows）](#1-环境准备windows)
2. [安装与启动](#2-安装与启动)
3. [申请 API 密钥](#3-申请-api-密钥)
4. [配置 .env](#4-配置-env)
5. [使用流程](#5-使用流程)
6. [数据存放位置 / 全部放在 D 盘](#6-数据存放位置--全部放在-d-盘)
7. [费用说明与省钱建议](#7-费用说明与省钱建议)
8. [常见问题](#8-常见问题)
9. [开发者说明（结构 / 测试 / 扩展厂商）](#9-开发者说明)

---

## 1. 环境准备（Windows）

| 软件 | 说明 |
| --- | --- |
| **Python 3.10 ~ 3.13** | 到 <https://www.python.org/downloads/windows/> 下载安装。安装第一步**务必勾选 "Add python.exe to PATH"**。 |
| **ffmpeg** | 用于把镜头视频拼成每集成片（模拟模式也需要）。到 <https://www.gyan.dev/ffmpeg/builds/> 下载 `ffmpeg-release-essentials.zip`，解压到例如 `D:\tools\ffmpeg\`，然后二选一：① 把 `D:\tools\ffmpeg\bin` 加到系统 PATH；② 在 `.env` 里写 `FFMPEG_PATH=D:\tools\ffmpeg\bin\ffmpeg.exe`。 |
| **Git**（可选） | 用来下载/更新本项目；也可以直接下载 zip。 |

> macOS / Linux：`brew install ffmpeg` 或 `sudo apt install ffmpeg`，然后用 `./start.sh` 启动。

## 2. 安装与启动

1. 把项目放到 D 盘，例如 `D:\novel-to-drama\`（下载 zip 解压，或 `git clone`）。
2. **双击 `start.bat`**。脚本会自动：
   - 在项目目录内创建虚拟环境 `.venv\`（pip 缓存也在项目内的 `.pip-cache\`，不会写到 C 盘）；
   - 安装依赖（默认使用清华镜像，速度快）；
   - 第一次运行时根据 `.env.example` 生成 `.env`；
   - 启动服务并自动打开浏览器 <http://127.0.0.1:8000>。
3. 关闭命令行窗口即停止服务。下次直接再双击 `start.bat`。

首次启动是**模拟模式**（界面右上角四个标签都显示「模拟」），可以立刻新建项目把整个流程跑一遍：几十秒内就能得到一部「假小说」和一段拼好的 mp4，用于熟悉操作。

## 3. 申请 API 密钥

| 用途 | 厂商 | 在哪申请 | 填到 .env 的变量 |
| --- | --- | --- | --- |
| 文本（默认） | DeepSeek | <https://platform.deepseek.com/api_keys> 注册 → 充值 → 创建 API key | `DEEPSEEK_API_KEY` |
| 文本（可选） + 图片（通义万相） | 阿里云百炼 DashScope | <https://bailian.console.aliyun.com/> → 开通「模型服务」→ 右上角「API-KEY」创建。**一个 key 同时用于千问和万相**。 | `DASHSCOPE_API_KEY` |
| 图片 + 视频 | 火山引擎 · 即梦 AI | <https://console.volcengine.com/> → 产品「视觉智能 / 即梦 AI」→ 开通「图片生成 4.0」「视频生成 3.0 Pro」等服务 → 「访问控制 → 密钥管理」创建 Access Key / Secret Key。 | `VOLC_ACCESS_KEY`、`VOLC_SECRET_KEY` |
| 视频 | 可灵 Kling 开放平台 | <https://app.klingai.com/cn/dev/document-api> → 开放平台 → 密钥管理，创建 Access Key / Secret Key，并购买资源包。 | `KLING_ACCESS_KEY`、`KLING_SECRET_KEY` |

不需要全部申请：最常见的组合是 **DeepSeek（文本）+ 通义万相（图片）+ 可灵（视频）**，或者全部用火山即梦（图片 + 视频）。

## 4. 配置 .env

打开项目根目录的 `.env`（记事本即可；没有的话把 `.env.example` 复制一份改名）。所有变量名与说明见 `.env.example`，关键项：

```ini
# 每个阶段用哪个厂商：mock=模拟
LLM_PROVIDER=deepseek          # mock | deepseek | qwen
VISUAL_LLM_PROVIDER=           # 分镜模型（第二个模型），留空 = 与 LLM_PROVIDER 相同
IMAGE_PROVIDER=wanx            # mock | wanx | jimeng
VIDEO_PROVIDER=kling           # mock | kling | jimeng

DEEPSEEK_API_KEY=sk-xxxxxxxx
DASHSCOPE_API_KEY=sk-xxxxxxxx
VOLC_ACCESS_KEY=AKLTxxxxxxxx
VOLC_SECRET_KEY=xxxxxxxx
KLING_ACCESS_KEY=xxxxxxxx
KLING_SECRET_KEY=xxxxxxxx

DATA_DIR=./data                # 数据目录，默认项目内 data\；也可写 D:\n2d-data
FFMPEG_PATH=ffmpeg             # 或 D:\tools\ffmpeg\bin\ffmpeg.exe
```

完整变量清单（也就是程序读取的环境变量名）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | 监听地址与端口 |
| `DATA_DIR` | `./data` | 数据目录（相对路径相对于项目目录） |
| `FFMPEG_PATH` | `ffmpeg` | ffmpeg 可执行文件 |
| `LLM_PROVIDER` / `VISUAL_LLM_PROVIDER` / `IMAGE_PROVIDER` / `VIDEO_PROVIDER` | `mock` | 各阶段厂商（界面「⚙ 厂商设置」里也能切换，优先级高于 .env） |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | — / `https://api.deepseek.com` / `deepseek-chat` | DeepSeek |
| `DASHSCOPE_API_KEY` / `DASHSCOPE_BASE_URL` / `QWEN_MODEL` | — / `https://dashscope.aliyuncs.com` / `qwen-plus` | 阿里云百炼（千问） |
| `WANX_MODEL` / `WANX_IMAGE_SIZE` | `wan2.2-t2i-flash` / `1280*720` | 通义万相文生图模型与尺寸（留空尺寸则按画幅自动计算） |
| `VOLC_ACCESS_KEY` / `VOLC_SECRET_KEY` / `VOLC_REGION` | — / — / `cn-north-1` | 火山引擎 |
| `JIMENG_T2I_REQ_KEY` | `jimeng_t2i_v40` | 即梦文生图模型（4.0） |
| `JIMENG_I2V_REQ_KEY` | `jimeng_ti2v_v30_pro` | 即梦图生视频模型（3.0 Pro，1080P）；可改 `jimeng_i2v_first_v30`（720P） |
| `JIMENG_IMAGE_WIDTH` / `JIMENG_IMAGE_HEIGHT` | `1280` / `720` | 即梦出图尺寸 |
| `KLING_ACCESS_KEY` / `KLING_SECRET_KEY` | — | 可灵 |
| `KLING_BASE_URL` | `https://api-beijing.klingai.com` | 国内节点；海外改 `https://api-singapore.klingai.com` |
| `KLING_MODEL` / `KLING_MODE` | `kling-v2-6` / `std` | 可灵模型与档位（`pro` 更贵更清晰） |
| `COST_PER_IMAGE_CNY` / `COST_PER_VIDEO_CLIP_CNY` | `0.2` / `3.0` | 界面费用预估用的单价（元），不影响实际调用 |
| `TASK_POLL_INTERVAL` / `TASK_POLL_TIMEOUT` | `5` / `900` | 异步任务轮询间隔与最长等待（秒） |

修改 `.env` 后**重启 `start.bat`** 生效。密钥只保存在本机 `.env`，该文件已被 `.gitignore` 忽略，不会被提交；界面只显示「已配置 / 未配置」，不会显示内容。

验证密钥是否可用（只做最小调用：一段短文本 + 一张图；加 `--video` 才会生成一段 5 秒视频）：

```bat
.venv\Scripts\python scripts\smoke_real.py
.venv\Scripts\python scripts\smoke_real.py --video
```

## 5. 使用流程

界面顶部是 6 个步骤。每一步都有「生成 / 重新生成 / 保存」，所有文本框都可直接修改；长任务会在上方显示进度条与日志。

### ① 小说设定
- 填写题材、基调、总字数、章节数、每集章节数（默认 1 章 = 1 集）、每章镜头数、镜头时长（5 / 10 秒）、画幅（16:9 横屏或 9:16 竖屏）。
- 添加人物：姓名、定位、性格、**外貌**（越具体越好，直接影响画面一致性）、关系。
- 「风格提示词」折叠区可编辑所有系统提示词：大纲、正文、**去 AI 味改写**、摘要、分镜，以及图片 / 视频统一画风后缀。留空即用默认值，随时可「恢复默认」。
- 点「保存并生成大纲」。

### ② 大纲
- 包含书名、一句话故事、梗概、世界设定、**角色圣经**（后续所有章节一致性的依据）和逐章纲要（标题 / 剧情 / 关键事件 / 章末钩子）。
- 可增删章节、修改任意字段后「保存修改」。

### ③ 章节正文
- 「一键生成剩余 N 章」或逐章生成。每章写作时会带上：大纲 + 角色圣经 + **前几章的滚动摘要** + 上一章结尾，保证前后一致。
- 勾选「生成后自动去 AI 味」：初稿完成后自动做一次人味改写（长短句交错、具体感官细节、口语化对白、删掉套话、不写总结式结尾……规则在设定页的提示词中可改）。
- 也可对任何一章单独「去 AI 味改写」，或「基于初稿重新改写」；「查看初稿」可对比改写前后。
- 正文、标题、前情摘要都可手改后保存。

### ④ 角色与分镜
- 先「生成角色设定」：第二个模型为每个角色写出**外貌关键词**和设定图提示词；这些关键词会被复述进每一个出现该角色的分镜提示词里，这是跨章节保持人物一致的核心手段。
- 再按章生成分镜方案：场景图 / 道具图提示词，以及镜头列表——每个镜头包含场景、出场角色、画面内容、台词、景别运镜、时长、**首帧图提示词**、**图生视频提示词**。可增删镜头、修改后保存。

### ⑤ 图片生成
- 选择范围（全部 / 某一章）与类型（角色 / 场景 / 道具 / 分镜首帧），默认只生成缺失的；界面先显示**数量与预估费用**，确认后再调用。
- 每张图都可单独「重新生成」；点击图片可放大查看提示词。重新生成分镜首帧后，对应镜头的视频需要重做。

### ⑥ 视频与剧集
- 「划分剧集」：按设定里的每集章节数把章节分组（可改数字后重新划分；也可以改每集标题）。
- 每一集单独点「生成本集视频」，弹窗显示待生成段数、总时长、预估费用，确认后才会调用视频厂商（图生视频，以分镜首帧为起始帧）。
- 镜头视频齐全后点「拼接成片」，ffmpeg 会统一分辨率/帧率并拼接为 `episode_XX.mp4`，页面内可直接播放、下载。单个镜头的视频也可以重新生成。

### 切换厂商
右上角「⚙ 厂商设置」可以随时切换各阶段用模拟还是真实厂商（未配置密钥的会被禁用）。例如：用真实模型写小说，但先用模拟模式把分镜和视频流程跑一遍，确认满意后再切回真实的图片 / 视频厂商。

## 6. 数据存放位置 / 全部放在 D 盘

- 程序、虚拟环境（`.venv\`）、pip 缓存（`.pip-cache\`）都在项目目录内。
- 所有项目数据在 `DATA_DIR`（默认 `项目目录\data\`）：

```
data\
  app_settings.json              # 界面里选择的厂商
  projects\
    pj_xxxxxxxx\
      project.json               # 本项目全部文本状态：设定、大纲、章节、分镜、剧集
      assets\
        images\characters\       # 角色设定图
        images\scenes\  props\   # 场景 / 道具
        images\storyboard\       # 分镜首帧
        videos\shots\            # 每个镜头的视频
        episodes\episode_01.mp4  # 每集成片
```

想换位置就改 `.env` 的 `DATA_DIR`（例如 `D:\n2d-data`）。备份只需复制 `data\` 文件夹。`project.json` 是普通的 UTF-8 JSON，可以用任何编辑器查看。

## 7. 费用说明与省钱建议

大致量级（以各厂商官网价格为准，会变动）：文本模型每章初稿 + 摘要 + 改写约几分到一角钱；图片每张约 0.1~0.3 元；**视频是大头**，5 秒一段通常 1~5 元，一集 8 个镜头就是 10~40 元。

- 先用模拟模式把流程跑通、把提示词改满意，再切真实厂商。
- 文本可以全部真实；图片只对关键镜头重新生成；视频按集手动触发，看完预估再确认。
- 把 `COST_PER_IMAGE_CNY` / `COST_PER_VIDEO_CLIP_CNY` 改成你实际的单价，预估会更准。
- 镜头时长用 5 秒；可灵用 `std` 档；即梦视频可改 `jimeng_i2v_first_v30`（720P 更便宜）。

## 8. 常见问题

**双击 start.bat 一闪而过 / 提示找不到 Python**：安装 Python 时没勾选 "Add to PATH"。重新安装并勾选，或手动把 Python 目录加入 PATH。

**pip 安装很慢或失败**：脚本默认用清华镜像；若公司网络有限制，可设置环境变量 `PIP_INDEX_URL` 改成其他源，或先关闭代理。

**界面提示「未检测到 ffmpeg」**：按第 1 节安装 ffmpeg，并把 `bin\ffmpeg.exe` 的完整路径写入 `.env` 的 `FFMPEG_PATH`，重启。

**切换厂商时提示「尚未配置密钥」**：检查 `.env` 中对应变量是否填写、是否有多余空格，然后重启 `start.bat`。

**模型返回「无法解析 JSON」**：偶发，点「重新生成」即可；长期出现可换更强的模型（如 `qwen-max`）或缩短提示词。

**即梦返回 code 不等于 10000**：常见原因是未在火山引擎控制台开通对应服务（图片 4.0 / 视频 3.0 Pro），或 AK/SK 没有「视觉智能」权限。

**可灵返回 1002 / 1004**：Access Key / Secret Key 错误或已过期；1102/1103 通常是余额或资源包不足。

**端口被占用**：改 `.env` 的 `APP_PORT`。

**想从别的电脑访问**：`APP_HOST=0.0.0.0`，但注意本程序没有登录鉴权，只建议在可信局域网使用。

## 9. 开发者说明

```
app/
  main.py            FastAPI 入口、静态文件
  api.py             HTTP 接口（/api/...），耗时操作返回 job
  config.py          .env 读取、密钥状态、界面厂商选择
  models.py          项目数据模型（pydantic）
  storage.py         每项目一个文件夹 + project.json
  jobs.py            后台任务与进度
  prompts.py         默认中文提示词（可被项目设置覆盖）
  providers/         厂商适配层
    base.py          统一接口：LLMProvider / ImageProvider / VideoProvider + 轮询、重试
    mock.py          模拟厂商（Pillow 占位图 + ffmpeg 生成视频）
    openai_compat.py DeepSeek / 千问（OpenAI 兼容 chat/completions）
    dashscope_wanx.py 通义万相 文生图（异步任务 + /api/v1/tasks 轮询）
    volc_jimeng.py   火山引擎 即梦 文生图 / 图生视频（HMAC-SHA256 V4 签名，CVSync2Async*）
    kling.py         可灵 图生视频（HS256 JWT，/v1/videos/image2video）
  services/
    novel.py         大纲、逐章正文、滚动摘要、去 AI 味
    visual.py        角色设定、场景/道具/分镜/视频提示词
    media.py         图片 / 视频生成与资产保存
    episodes.py      剧集划分、预估、ffmpeg 拼接
frontend/            index.html + app.js + style.css（无构建）
scripts/smoke_real.py 真实厂商冒烟测试
tests/               pytest（全部基于模拟厂商与 httpx MockTransport，不需要密钥）
```

运行测试：

```bash
python -m pytest -q
```

接入新厂商：在 `app/providers/` 里实现对应接口的类，在 `providers/__init__.py` 的 `build_*` 中注册名字，并把名字加入 `config.py` 的 `*_PROVIDERS` 元组即可；界面会自动出现该选项。

> 真实厂商接口按各家 2025–2026 年公开文档实现（DeepSeek / DashScope OpenAI 兼容接口；万相 `text2image/image-synthesis` 与 `/api/v1/tasks/{id}`；即梦 `CVSync2AsyncSubmitTask` / `CVSync2AsyncGetResult`，`req_key` 为 `jimeng_t2i_v40`、`jimeng_ti2v_v30_pro`；可灵 `/v1/videos/image2video`）。模型名、`req_key` 等都可通过 `.env` 调整，以便厂商升级时无需改代码。
