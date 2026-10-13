"""项目存储：每个项目一个文件夹，project.json + assets/。"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

from .models import Project, now_ts


class ProjectStore:
    def __init__(self, projects_dir: Path):
        self.root = Path(projects_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, asyncio.Lock] = {}

    # ---- 路径 ----
    def project_dir(self, project_id: str) -> Path:
        return self.root / project_id

    def project_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def asset_dir(self, project_id: str, sub: str) -> Path:
        p = self.project_dir(project_id) / "assets" / sub
        p.mkdir(parents=True, exist_ok=True)
        return p

    def resolve_asset(self, project_id: str, rel_path: str) -> Path:
        """解析项目内相对路径，防止目录穿越。"""
        base = self.project_dir(project_id).resolve()
        target = (base / rel_path).resolve()
        if base not in target.parents and target != base:
            raise ValueError("非法路径")
        return target

    # ---- CRUD ----
    def list_projects(self) -> List[Project]:
        projects: List[Project] = []
        for d in sorted(self.root.iterdir()):
            f = d / "project.json"
            if f.exists():
                try:
                    projects.append(self._read(f))
                except Exception:
                    continue
        projects.sort(key=lambda p: p.updated_at, reverse=True)
        return projects

    def exists(self, project_id: str) -> bool:
        return self.project_file(project_id).exists()

    def load(self, project_id: str) -> Project:
        f = self.project_file(project_id)
        if not f.exists():
            raise KeyError(f"项目不存在: {project_id}")
        return self._read(f)

    def save(self, project: Project) -> Project:
        project.updated_at = now_ts()
        d = self.project_dir(project.id)
        d.mkdir(parents=True, exist_ok=True)
        f = self.project_file(project.id)
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(project.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, f)
        return project

    def create(self, project: Project) -> Project:
        return self.save(project)

    def delete(self, project_id: str) -> None:
        d = self.project_dir(project_id)
        if d.exists():
            shutil.rmtree(d)

    # ---- 并发安全的「读-改-写」----
    def _lock(self, project_id: str) -> asyncio.Lock:
        lock = self._locks.get(project_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[project_id] = lock
        return lock

    @asynccontextmanager
    async def edit(self, project_id: str) -> AsyncIterator[Project]:
        """async with store.edit(pid) as project: ...  退出时自动保存。"""
        async with self._lock(project_id):
            project = self.load(project_id)
            yield project
            self.save(project)

    @staticmethod
    def _read(f: Path) -> Project:
        return Project.model_validate(json.loads(f.read_text(encoding="utf-8")))


_store: Optional[ProjectStore] = None


def get_store() -> ProjectStore:
    global _store
    if _store is None:
        from .config import get_settings

        _store = ProjectStore(get_settings().projects_path)
    return _store


def set_store(store: ProjectStore) -> None:
    global _store
    _store = store
