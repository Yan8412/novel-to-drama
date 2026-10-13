#!/usr/bin/env bash
# macOS / Linux 一键启动（Windows 请用 start.bat）
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[信息] 创建虚拟环境 .venv ..."
  python3 -m venv .venv
fi
export PIP_CACHE_DIR="$PWD/.pip-cache"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
echo "[信息] 检查/安装依赖 ..."
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "[信息] 已生成 .env（默认模拟模式）。填入密钥后重新运行即可使用真实模型。"
fi

command -v ffmpeg >/dev/null 2>&1 || echo "[提示] 未找到 ffmpeg，视频拼接需要它：macOS 可 brew install ffmpeg，Ubuntu 可 sudo apt install ffmpeg"

PORT=$(grep -E '^APP_PORT=' .env | cut -d= -f2)
echo "[信息] 启动服务 http://127.0.0.1:${PORT:-8000}"
exec .venv/bin/python -m app.main
