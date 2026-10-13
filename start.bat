@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ==========================================================
echo   小说转短剧 novel-to-drama  一键启动
echo   项目目录: %CD%
echo ==========================================================

REM ---------- 1. 检查 Python ----------
set "PY="
where python >nul 2>nul && set "PY=python"
if "%PY%"=="" ( where py >nul 2>nul && set "PY=py -3" )
if "%PY%"=="" (
  echo [错误] 未找到 Python。请安装 Python 3.10 以上版本：https://www.python.org/downloads/windows/
  echo        安装时请勾选 "Add python.exe to PATH"。
  pause
  exit /b 1
)
for /f "tokens=2 delims= " %%v in ('%PY% --version 2^>^&1') do set "PYVER=%%v"
echo [信息] 使用 Python %PYVER%

REM ---------- 2. 虚拟环境（放在项目目录内，保证所有文件都在当前盘） ----------
if not exist ".venv\Scripts\python.exe" (
  echo [信息] 正在创建虚拟环境 .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [错误] 创建虚拟环境失败。
    pause
    exit /b 1
  )
)
set "VPY=.venv\Scripts\python.exe"

REM pip 缓存也放在项目目录内
set "PIP_CACHE_DIR=%CD%\.pip-cache"
REM 国内镜像（如需官方源请把下一行注释掉或设置环境变量 PIP_INDEX_URL）
if "%PIP_INDEX_URL%"=="" set "PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"

REM ---------- 3. 安装依赖（已安装时会很快跳过） ----------
echo [信息] 正在检查/安装依赖 ...
"%VPY%" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo [错误] 依赖安装失败，请检查网络后重试。
  pause
  exit /b 1
)

REM ---------- 4. 配置文件 ----------
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo [信息] 已根据 .env.example 生成 .env。默认是模拟模式，可直接体验；
  echo        填入 API 密钥后重新运行本脚本即可使用真实模型。
)

REM ---------- 5. ffmpeg ----------
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [提示] 未在 PATH 中找到 ffmpeg。视频拼接需要 ffmpeg：
  echo        下载 https://www.gyan.dev/ffmpeg/builds/  解压后把 bin\ffmpeg.exe 的完整路径填到 .env 的 FFMPEG_PATH，
  echo        或把 bin 目录加入系统 PATH。（若已在 .env 中设置 FFMPEG_PATH 可忽略本提示）
)

REM ---------- 6. 启动 ----------
set "PORT=8000"
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /i "APP_PORT=" .env 2^>nul`) do set "PORT=%%b"
echo [信息] 正在启动服务 http://127.0.0.1:%PORT%  （关闭本窗口即停止服务）
start "" /b cmd /c "timeout /t 3 >nul && start http://127.0.0.1:%PORT%"
"%VPY%" -m app.main
pause
