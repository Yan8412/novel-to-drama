"""真实厂商适配器的单元测试：签名、JWT、请求体与轮询（用 httpx MockTransport 模拟服务端）。"""
import base64
import datetime as dt
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest

from app.providers import dashscope_wanx, kling, volc_jimeng
from app.providers.base import ProviderError, ProviderNotConfigured, aspect_to_size
from app.providers.openai_compat import make_deepseek, make_qwen
from app.services.llm_json import extract_json


def _mock_client_factory(handler):
    def factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def test_aspect_to_size():
    assert aspect_to_size("16:9", 1280) == (1280, 720)
    assert aspect_to_size("9:16", 1280) == (720, 1280)
    assert aspect_to_size("1:1", 1024) == (1024, 1024)
    assert aspect_to_size("乱写", 1280) == (1280, 720)


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": [1,2,]}\n```') == {"a": [1, 2]}
    assert extract_json('前面有废话 {"a": "中文"} 后面也有') == {"a": "中文"}
    with pytest.raises(ProviderError):
        extract_json("完全不是 json")


# ---------------------------------------------------------------------------
# OpenAI 兼容（DeepSeek / Qwen）
# ---------------------------------------------------------------------------


def test_openai_compat_requires_key():
    with pytest.raises(ProviderNotConfigured):
        make_deepseek(None, "https://api.deepseek.com", "deepseek-chat")


def test_qwen_url():
    q = make_qwen("sk-test", "https://dashscope.aliyuncs.com", "qwen-plus")
    assert q.chat_url == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    d = make_deepseek("sk-test", "https://api.deepseek.com", "deepseek-chat")
    assert d.chat_url == "https://api.deepseek.com/v1/chat/completions"


async def test_openai_compat_request_shape(monkeypatch):
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}]})

    from app.providers import openai_compat

    monkeypatch.setattr(openai_compat, "make_client", _mock_client_factory(handler))
    llm = make_deepseek("sk-secret", "https://api.deepseek.com", "deepseek-chat")
    out = await llm.complete("系统", "用户", json_mode=True, max_tokens=100)
    assert out == '{"ok": true}'
    assert seen["url"].endswith("/v1/chat/completions")
    assert seen["auth"] == "Bearer sk-secret"
    assert seen["body"]["model"] == "deepseek-chat"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["messages"][0] == {"role": "system", "content": "系统"}


async def test_openai_compat_http_error_is_provider_error(monkeypatch):
    from app.providers import openai_compat

    monkeypatch.setattr(openai_compat, "make_client", _mock_client_factory(lambda r: httpx.Response(401, json={"error": "bad key"})))
    llm = make_deepseek("sk-bad", "https://api.deepseek.com", "deepseek-chat")
    with pytest.raises(ProviderError, match="401"):
        await llm.complete("s", "u")


# ---------------------------------------------------------------------------
# 通义万相
# ---------------------------------------------------------------------------


def test_wanx_extract_image_url_both_formats():
    legacy = {"output": {"results": [{"url": "https://x/a.png"}]}}
    new = {"output": {"choices": [{"message": {"content": [{"image": "https://x/b.png"}]}}]}}
    assert dashscope_wanx.WanxImageProvider.extract_image_url(legacy) == "https://x/a.png"
    assert dashscope_wanx.WanxImageProvider.extract_image_url(new) == "https://x/b.png"


async def test_wanx_submit_poll_download(monkeypatch):
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/image-synthesis"):
            assert request.headers["X-DashScope-Async"] == "enable"
            body = json.loads(request.content)
            assert body["model"] == "wan2.2-t2i-flash"
            assert body["input"]["prompt"] == "测试提示词"
            assert body["parameters"]["size"] == "1280*720"
            return httpx.Response(200, json={"output": {"task_id": "t1", "task_status": "PENDING"}, "request_id": "r"})
        if request.url.path == "/api/v1/tasks/t1":
            if len([c for c in calls if c[1] == "/api/v1/tasks/t1"]) == 1:
                return httpx.Response(200, json={"output": {"task_id": "t1", "task_status": "RUNNING"}})
            return httpx.Response(200, json={"output": {"task_id": "t1", "task_status": "SUCCEEDED", "results": [{"url": "https://cdn.test/img.png"}]}, "usage": {"image_count": 1}})
        if request.url.host == "cdn.test":
            return httpx.Response(200, content=b"PNGDATA")
        return httpx.Response(404)

    monkeypatch.setattr(dashscope_wanx, "make_client", _mock_client_factory(handler))
    p = dashscope_wanx.WanxImageProvider(api_key="sk", model="wan2.2-t2i-flash", poll_interval=0, poll_timeout=5)
    res = await p.generate("测试提示词", aspect_ratio="16:9")
    assert res.data == b"PNGDATA" and res.ext == "png" and res.meta["task_id"] == "t1"
    assert calls[0] == ("POST", "/api/v1/services/aigc/text2image/image-synthesis")


def test_wanx_v26_uses_messages_format():
    p = dashscope_wanx.WanxImageProvider(api_key="sk", model="wan2.6-t2i")
    url, body = p._build_request("提示", "", "16:9")
    assert url.endswith("/image-generation/generation")
    assert body["input"]["messages"][0]["content"][0]["text"] == "提示"
    w, h = [int(x) for x in body["parameters"]["size"].split("*")]
    assert w * h >= 1280 * 1280


async def test_wanx_failed_task(monkeypatch):
    def handler(request: httpx.Request):
        if request.method == "POST":
            return httpx.Response(200, json={"output": {"task_id": "t2"}})
        return httpx.Response(200, json={"output": {"task_status": "FAILED", "code": "InvalidParameter", "message": "bad prompt"}})

    monkeypatch.setattr(dashscope_wanx, "make_client", _mock_client_factory(handler))
    p = dashscope_wanx.WanxImageProvider(api_key="sk", poll_interval=0, poll_timeout=5)
    with pytest.raises(ProviderError, match="InvalidParameter"):
        await p.generate("x")


# ---------------------------------------------------------------------------
# 火山引擎 即梦
# ---------------------------------------------------------------------------


def test_volc_signature_structure_and_determinism():
    body = json.dumps({"req_key": "jimeng_t2i_v40", "prompt": "猫"}, ensure_ascii=False).encode()
    now = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc)
    kwargs = dict(access_key="AKTEST", secret_key="SKTEST", region="cn-north-1", service="cv", method="POST", host="visual.volcengineapi.com", path="/", query={"Action": "CVSync2AsyncSubmitTask", "Version": "2022-08-31"}, body=body, now=now)
    h1 = volc_jimeng.sign_volc_request(**kwargs)
    h2 = volc_jimeng.sign_volc_request(**kwargs)
    assert h1 == h2
    assert h1["X-Date"] == "20260102T030405Z"
    assert h1["X-Content-Sha256"] == hashlib.sha256(body).hexdigest()
    assert h1["Authorization"].startswith("HMAC-SHA256 Credential=AKTEST/20260102/cn-north-1/cv/request, SignedHeaders=content-type;host;x-content-sha256;x-date, Signature=")
    sig = h1["Authorization"].rsplit("Signature=", 1)[1]
    assert len(sig) == 64 and all(c in "0123456789abcdef" for c in sig)

    # 独立实现一遍签名算法，交叉验证
    canonical = "\n".join(
        [
            "POST",
            "/",
            "Action=CVSync2AsyncSubmitTask&Version=2022-08-31",
            "content-type:application/json\nhost:visual.volcengineapi.com\nx-content-sha256:%s\nx-date:20260102T030405Z\n" % h1["X-Content-Sha256"],
            "content-type;host;x-content-sha256;x-date",
            h1["X-Content-Sha256"],
        ]
    )
    sts = "\n".join(["HMAC-SHA256", "20260102T030405Z", "20260102/cn-north-1/cv/request", hashlib.sha256(canonical.encode()).hexdigest()])
    k = hmac.new(b"SKTEST", b"20260102", hashlib.sha256).digest()
    for part in ("cn-north-1", "cv", "request"):
        k = hmac.new(k, part.encode(), hashlib.sha256).digest()
    assert sig == hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()

    # 不同密钥 -> 不同签名
    assert volc_jimeng.sign_volc_request(**{**kwargs, "secret_key": "OTHER"})["Authorization"] != h1["Authorization"]


async def test_jimeng_image_flow(monkeypatch):
    calls = []

    def handler(request: httpx.Request):
        if request.url.host == "cdn.test":
            return httpx.Response(200, content=b"JPG")
        action = request.url.params["Action"]
        assert request.url.params["Version"] == "2022-08-31"
        assert request.headers["Authorization"].startswith("HMAC-SHA256 Credential=AK/")
        body = json.loads(request.content)
        calls.append(action)
        if action == "CVSync2AsyncSubmitTask":
            assert body["req_key"] == "jimeng_t2i_v40" and body["width"] == 1280 and body["height"] == 720
            return httpx.Response(200, json={"code": 10000, "data": {"task_id": "T"}, "message": "Success"})
        if action == "CVSync2AsyncGetResult":
            assert body["task_id"] == "T" and json.loads(body["req_json"])["return_url"] is True
            if calls.count("CVSync2AsyncGetResult") == 1:
                return httpx.Response(200, json={"code": 10000, "data": {"status": "generating"}})
            return httpx.Response(200, json={"code": 10000, "data": {"status": "done", "image_urls": ["https://cdn.test/a.jpeg"]}})
        return httpx.Response(404)

    monkeypatch.setattr(volc_jimeng, "make_client", _mock_client_factory(handler))
    p = volc_jimeng.JimengImageProvider(access_key="AK", secret_key="SK", poll_interval=0, poll_timeout=5)
    res = await p.generate("猫", aspect_ratio="16:9")
    assert res.data == b"JPG" and res.ext == "jpg" and res.provider == "jimeng"


async def test_jimeng_video_flow_uses_base64_frame(monkeypatch, tmp_path):
    frame = tmp_path / "f.png"
    frame.write_bytes(b"\x89PNGfake")
    seen = {}

    def handler(request: httpx.Request):
        if request.url.host == "cdn.test":
            return httpx.Response(200, content=b"MP4")
        action = request.url.params["Action"]
        body = json.loads(request.content)
        if action == "CVSync2AsyncSubmitTask":
            seen["submit"] = body
            return httpx.Response(200, json={"code": 10000, "data": {"task_id": "V"}})
        if action == "CVSync2AsyncGetResult":
            return httpx.Response(200, json={"code": 10000, "data": {"status": "done", "video_url": "https://cdn.test/v.mp4"}})
        return httpx.Response(200, content=b"MP4")

    monkeypatch.setattr(volc_jimeng, "make_client", _mock_client_factory(handler))
    p = volc_jimeng.JimengVideoProvider(access_key="AK", secret_key="SK", poll_interval=0, poll_timeout=5)
    res = await p.image_to_video(frame, "动起来", duration_sec=10)
    assert res.data == b"MP4" and res.ext == "mp4"
    assert seen["submit"]["req_key"] == "jimeng_ti2v_v30_pro"
    assert seen["submit"]["frames"] == 241
    assert base64.b64decode(seen["submit"]["binary_data_base64"][0]) == b"\x89PNGfake"


async def test_jimeng_error_code(monkeypatch):
    monkeypatch.setattr(volc_jimeng, "make_client", _mock_client_factory(lambda r: httpx.Response(200, json={"code": 50411, "message": "Input image sensitive", "request_id": "x"})))
    p = volc_jimeng.JimengImageProvider(access_key="AK", secret_key="SK", poll_interval=0, poll_timeout=5)
    with pytest.raises(ProviderError, match="50411"):
        await p.generate("x")


# ---------------------------------------------------------------------------
# 可灵
# ---------------------------------------------------------------------------


def test_kling_jwt():
    token = kling.make_kling_jwt("AK123", "SK456", ttl=1800, now=1_700_000_000)
    header_b64, payload_b64, sig_b64 = token.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
    header = json.loads(base64.urlsafe_b64decode(pad(header_b64)))
    payload = json.loads(base64.urlsafe_b64decode(pad(payload_b64)))
    assert header == {"alg": "HS256", "typ": "JWT"}
    assert payload == {"iss": "AK123", "exp": 1_700_001_800, "nbf": 1_699_999_995}
    expected = hmac.new(b"SK456", f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    assert base64.urlsafe_b64decode(pad(sig_b64)) == expected


async def test_kling_image2video_flow(monkeypatch, tmp_path):
    frame = tmp_path / "f.png"
    frame.write_bytes(b"PNG!")
    calls = []

    def handler(request: httpx.Request):
        if request.url.host == "cdn.test":
            return httpx.Response(200, content=b"KLINGMP4")
        calls.append((request.method, request.url.path))
        assert request.headers["Authorization"].startswith("Bearer ")
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["model_name"] == "kling-v2-6" and body["duration"] == "5" and body["mode"] == "std"
            assert body["image"] == base64.b64encode(b"PNG!").decode()
            assert "cfg_scale" not in body
            return httpx.Response(200, json={"code": 0, "message": "ok", "data": {"task_id": "K1", "task_status": "submitted"}})
        if request.url.path == "/v1/videos/image2video/K1":
            n = sum(1 for c in calls if c[1] == "/v1/videos/image2video/K1")
            if n == 1:
                return httpx.Response(200, json={"code": 0, "data": {"task_id": "K1", "task_status": "processing"}})
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "K1", "task_status": "succeed", "task_result": {"videos": [{"id": "v", "url": "https://cdn.test/k.mp4", "duration": "5.1"}]}}})
        return httpx.Response(200, content=b"KLINGMP4")

    monkeypatch.setattr(kling, "make_client", _mock_client_factory(handler))
    p = kling.KlingVideoProvider(access_key="AK", secret_key="SK", poll_interval=0, poll_timeout=5)
    res = await p.image_to_video(frame, "镜头缓慢推进", duration_sec=5)
    assert res.data == b"KLINGMP4" and res.meta["task_id"] == "K1"
    assert calls[0] == ("POST", "/v1/videos/image2video")


async def test_kling_api_error(monkeypatch, tmp_path):
    frame = tmp_path / "f.png"
    frame.write_bytes(b"PNG!")
    monkeypatch.setattr(kling, "make_client", _mock_client_factory(lambda r: httpx.Response(200, json={"code": 1002, "message": "auth failed", "request_id": "x"})))
    p = kling.KlingVideoProvider(access_key="AK", secret_key="SK", poll_interval=0, poll_timeout=5)
    with pytest.raises(ProviderError, match="1002"):
        await p.image_to_video(frame, "x")


def test_build_real_providers_need_keys(settings):
    from app.providers import build_image, build_llm, build_video

    for kind, builder, names in (("llm", build_llm, ("deepseek", "qwen")), ("image", build_image, ("wanx", "jimeng")), ("video", build_video, ("kling", "jimeng"))):
        for n in names:
            with pytest.raises(ProviderNotConfigured):
                builder(n, settings)
    assert build_llm("mock", settings).name == "mock"
