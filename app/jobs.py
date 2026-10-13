"""后台任务管理：生成类操作都以异步任务运行，前端轮询进度。"""
from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Awaitable, Callable, Dict, List, Optional

from .models import JobInfo, new_id, now_ts

logger = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


class JobContext:
    """传给任务函数，用于汇报进度 / 日志 / 检查取消。"""

    def __init__(self, info: JobInfo):
        self.info = info
        self._cancel = False

    def log(self, msg: str) -> None:
        logger.info("[job %s] %s", self.info.id, msg)
        self.info.logs.append(msg)
        if len(self.info.logs) > 300:
            del self.info.logs[: len(self.info.logs) - 300]
        self.info.message = msg

    def progress(self, value: float, msg: Optional[str] = None) -> None:
        self.info.progress = max(0.0, min(1.0, value))
        if msg:
            self.log(msg)
        self.check_cancelled()

    def request_cancel(self) -> None:
        self._cancel = True

    @property
    def cancelled(self) -> bool:
        return self._cancel

    def check_cancelled(self) -> None:
        if self._cancel:
            raise JobCancelled()


JobFunc = Callable[[JobContext], Awaitable[Optional[dict]]]


class JobManager:
    def __init__(self, max_keep: int = 200):
        self._jobs: Dict[str, JobInfo] = {}
        self._ctx: Dict[str, JobContext] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self.max_keep = max_keep

    def start(self, project_id: str, kind: str, fn: JobFunc) -> JobInfo:
        info = JobInfo(id=new_id("job_"), project_id=project_id, kind=kind)
        ctx = JobContext(info)
        self._jobs[info.id] = info
        self._ctx[info.id] = ctx
        self._tasks[info.id] = asyncio.create_task(self._run(ctx, fn))
        self._trim()
        return info

    async def _run(self, ctx: JobContext, fn: JobFunc) -> None:
        info = ctx.info
        info.status = "running"
        try:
            result = await fn(ctx)
            info.result = result or {}
            info.progress = 1.0
            info.status = "done"
            if not info.message or info.message == "":
                info.message = "完成"
            else:
                ctx.log("完成")
        except JobCancelled:
            info.status = "cancelled"
            ctx.log("已取消")
        except Exception as e:  # noqa: BLE001
            info.status = "failed"
            info.error = f"{type(e).__name__}: {e}"
            logger.error("job %s failed: %s\n%s", info.id, e, traceback.format_exc())
            ctx.log(f"失败：{info.error}")
        finally:
            info.finished_at = now_ts()

    def get(self, job_id: str) -> Optional[JobInfo]:
        return self._jobs.get(job_id)

    def list(self, project_id: Optional[str] = None) -> List[JobInfo]:
        jobs = [j for j in self._jobs.values() if project_id is None or j.project_id == project_id]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def cancel(self, job_id: str) -> bool:
        ctx = self._ctx.get(job_id)
        if not ctx:
            return False
        ctx.request_cancel()
        return True

    def running_for(self, project_id: str) -> List[JobInfo]:
        return [j for j in self._jobs.values() if j.project_id == project_id and j.status in ("pending", "running")]

    async def wait(self, job_id: str) -> JobInfo:
        """测试用：等待任务结束。"""
        task = self._tasks.get(job_id)
        if task:
            await task
        return self._jobs[job_id]

    def _trim(self) -> None:
        if len(self._jobs) <= self.max_keep:
            return
        finished = [j for j in self._jobs.values() if j.status in ("done", "failed", "cancelled")]
        finished.sort(key=lambda j: j.created_at)
        for j in finished[: len(self._jobs) - self.max_keep]:
            self._jobs.pop(j.id, None)
            self._ctx.pop(j.id, None)
            self._tasks.pop(j.id, None)


_manager: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
