"""HTTP API 测试：项目 CRUD、任务启动与轮询、配置切换、文件访问。"""
import asyncio

import httpx
import pytest

from app.jobs import get_job_manager
from app.main import app


@pytest.fixture
async def client(settings, store):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def wait_job(client, job_id, timeout=60):
    await get_job_manager().wait(job_id)
    r = await client.get(f"/api/jobs/{job_id}")
    return r.json()


async def test_config_endpoints(client):
    r = await client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["selection"]["llm_provider"] == "mock"
    assert data["key_status"] == {"deepseek": False, "dashscope": False, "volc": False, "kling": False}
    assert "default_prompts" in data and "humanize_system" in data["default_prompts"]
    # 没有密钥时不允许切到真实厂商
    r = await client.put("/api/config", json={"llm_provider": "deepseek"})
    assert r.status_code == 400
    r = await client.put("/api/config", json={"llm_provider": "mock", "video_provider": "mock"})
    assert r.status_code == 200


async def test_project_crud_and_outline_job(client):
    r = await client.post("/api/projects", json={"name": "测试", "settings": {"genre": "甜宠", "chapter_count": 2, "target_word_count": 1000}})
    assert r.status_code == 200
    pid = r.json()["id"]

    r = await client.get("/api/projects")
    assert any(p["id"] == pid for p in r.json())

    r = await client.put(f"/api/projects/{pid}", json={"name": "改名", "settings": {"genre": "甜宠", "chapter_count": 2, "target_word_count": 1000, "characters": [{"name": "小满"}]}})
    assert r.json()["name"] == "改名"

    r = await client.post(f"/api/projects/{pid}/outline/generate")
    assert r.status_code == 200
    job = await wait_job(client, r.json()["id"])
    assert job["status"] == "done", job

    r = await client.get(f"/api/projects/{pid}")
    p = r.json()
    assert p["outline"] and len(p["outline"]["chapters"]) == 2
    assert len(p["chapters"]) == 2

    # 编辑大纲
    outline = p["outline"]
    outline["chapters"][0]["title"] = "新标题"
    r = await client.put(f"/api/projects/{pid}/outline", json=outline)
    assert r.json()["outline"]["chapters"][0]["title"] == "新标题"
    assert r.json()["chapters"][0]["title"] == "新标题"

    r = await client.delete(f"/api/projects/{pid}")
    assert r.json()["ok"]
    r = await client.get(f"/api/projects/{pid}")
    assert r.status_code == 404


async def test_full_flow_via_api(client, settings):
    import shutil

    if not shutil.which(settings.ffmpeg_path):
        pytest.skip("需要 ffmpeg")
    r = await client.post("/api/projects", json={"name": "流程", "settings": {"genre": "悬疑", "chapter_count": 1, "target_word_count": 600, "shots_per_chapter": 2, "characters": [{"name": "阿宁", "appearance": "短发"}]}})
    pid = r.json()["id"]

    async def run(path, body=None):
        r = await client.post(path, json=body) if body is not None else await client.post(path)
        assert r.status_code == 200, r.text
        job = await wait_job(client, r.json()["id"])
        assert job["status"] == "done", job
        return job

    await run(f"/api/projects/{pid}/outline/generate")
    await run(f"/api/projects/{pid}/chapters/generate-all", {"humanize": True, "only_missing": True})
    await run(f"/api/projects/{pid}/characters/generate")
    await run(f"/api/projects/{pid}/visual/generate-all", {"only_missing": True})

    # 编辑章节正文
    r = await client.put(f"/api/projects/{pid}/chapters/1", json={"text": "手动改写的正文。"})
    assert r.json()["text"] == "手动改写的正文。"

    # 预估图片
    r = await client.post(f"/api/projects/{pid}/images/estimate", json={"kinds": ["characters", "storyboard"], "only_missing": True})
    est = r.json()
    assert est["count"] == est["by_kind"]["characters"] + est["by_kind"]["storyboard"] >= 3
    await run(f"/api/projects/{pid}/images/generate", {"kinds": ["characters", "scenes", "props", "storyboard"], "only_missing": True})

    r = await client.post(f"/api/projects/{pid}/episodes/define", json={})
    eps = r.json()
    assert len(eps) == 1 and eps[0]["chapter_indices"] == [1]

    r = await client.get(f"/api/projects/{pid}/episodes/1/estimate")
    est = r.json()
    assert est["pending_video_count"] == 2 and est["shots_missing_image"] == 0

    await run(f"/api/projects/{pid}/episodes/1/videos/generate", {"only_missing": True})
    r = await client.get(f"/api/projects/{pid}/episodes/1/estimate")
    assert r.json()["ready_to_render"]

    await run(f"/api/projects/{pid}/episodes/1/render")
    r = await client.get(f"/api/projects/{pid}")
    ep = r.json()["episodes"][0]
    assert ep["status"] == "rendered" and ep["video"]["path"].endswith("episode_01.mp4")

    # 文件访问 + 目录穿越防护
    r = await client.get(f"/files/{pid}/{ep['video']['path']}")
    assert r.status_code == 200 and len(r.content) > 1000
    r = await client.get(f"/files/{pid}/../../etc/passwd")
    assert r.status_code in (400, 404)


async def test_guard_running_job(client):
    r = await client.post("/api/projects", json={"name": "并发", "settings": {"chapter_count": 1, "target_word_count": 500}})
    pid = r.json()["id"]
    r1 = await client.post(f"/api/projects/{pid}/outline/generate")
    r2 = await client.post(f"/api/projects/{pid}/outline/generate")
    assert r1.status_code == 200
    assert r2.status_code == 409
    await wait_job(client, r1.json()["id"])
