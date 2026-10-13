"""FastAPI 入口。运行：python -m app.main 或 uvicorn app.main:app"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import files_router, router
from .config import PROJECT_ROOT, get_settings
from .providers.base import ProviderError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("novel2drama")

FRONTEND_DIR = PROJECT_ROOT / "frontend"

app = FastAPI(title="小说转短剧 novel-to-drama", version=__version__)
app.include_router(router, prefix="/api")
app.include_router(files_router)


@app.exception_handler(ProviderError)
async def provider_error_handler(_: Request, exc: ProviderError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(KeyError)
async def key_error_handler(_: Request, exc: KeyError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True, "version": __version__}


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.on_event("startup")
async def _startup():
    s = get_settings()
    logger.info("数据目录：%s", s.data_path)
    ks = s.key_status()
    logger.info("密钥配置状态：%s", ", ".join(f"{k}={'已配置' if v else '未配置'}" for k, v in ks.items()))


def run() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.app_host, port=s.app_port, reload=False)


if __name__ == "__main__":
    run()
