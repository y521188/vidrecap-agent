"""OpenAI 兼容适配器测试：本地假服务验证请求组装与错误路径，不打真网络。"""

import contextlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from vidrecap.external.api import LLMClient, OpenAICompatibleLLM
from vidrecap.user.api import main


@contextlib.contextmanager
def _fake_endpoint(*, status: int = 200, payload: dict | None = None, sleep: float = 0.0):
    """起一个记录请求、按剧本回复的假 chat/completions 端点，用完即关。"""
    reply = payload if payload is not None else {
        "choices": [{"message": {"content": "假摘要。"}}]
    }
    recorded: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            recorded.update(
                path=self.path,
                auth=self.headers.get("Authorization"),
                body=json.loads(self.rfile.read(length)),
            )
            time.sleep(sleep)
            body = json.dumps(reply).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield recorded, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _client(base_url: str, **kwargs) -> OpenAICompatibleLLM:
    return OpenAICompatibleLLM(
        base_url=base_url, api_key="sk-test", model="test-model", **kwargs
    )


async def test_satisfies_llm_client_socket():
    with _fake_endpoint() as (_, url):
        assert isinstance(_client(url), LLMClient)


async def test_request_assembly_and_response_parsing():
    with _fake_endpoint() as (recorded, url):
        result = await _client(url).summarize("这是正文。", instruction="概括它")
    assert result == "假摘要。"
    assert recorded["path"] == "/chat/completions"
    assert recorded["auth"] == "Bearer sk-test"
    assert recorded["body"]["model"] == "test-model"
    assert recorded["body"]["messages"] == [
        {"role": "user", "content": "概括它"},
        {"role": "user", "content": "这是正文。"},
    ]


async def test_empty_instruction_sends_no_system_message():
    with _fake_endpoint() as (recorded, url):
        await _client(url).summarize("只有正文。")
    assert recorded["body"]["messages"] == [{"role": "user", "content": "只有正文。"}]


async def test_dual_prompts_become_separate_messages():
    """双重约束：System Prompt 与用户指令各成一条消息，正文最后。"""
    with _fake_endpoint() as (recorded, url):
        await _client(url).summarize("正文", instruction="本次要求", system="你是资深编辑。")
    assert recorded["body"]["messages"] == [
        {"role": "system", "content": "你是资深编辑。"},
        {"role": "user", "content": "本次要求"},
        {"role": "user", "content": "正文"},
    ]


async def test_describe_image_inlines_jpeg_as_data_uri():
    payload = {"choices": [{"message": {"content": "主讲人翻到第二页。"}}]}
    with _fake_endpoint(payload=payload) as (recorded, url):
        text = await _client(url).describe_image(
            b"\xff\xd8fake-jpeg", prompt="描述画面", system="你是编辑"
        )
    assert text == "主讲人翻到第二页。"
    messages = recorded["body"]["messages"]
    assert messages[0] == {"role": "system", "content": "你是编辑"}
    parts = messages[1]["content"]
    assert parts[0] == {"type": "text", "text": "描述画面"}
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


async def test_http_error_is_surfaced_with_status():
    with _fake_endpoint(status=500, payload={"error": "boom"}) as (_, url):
        with pytest.raises(RuntimeError, match="500"):
            await _client(url).summarize("正文")


async def test_timeout_is_surfaced():
    with _fake_endpoint(sleep=1.0) as (_, url):
        with pytest.raises(RuntimeError, match="模型请求失败"):
            await _client(url, timeout=0.2).summarize("正文")


async def test_malformed_response_is_surfaced():
    with _fake_endpoint(payload={"oops": 1}) as (_, url):
        with pytest.raises(RuntimeError, match="格式"):
            await _client(url).summarize("正文")


def test_model_name_is_required(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(ValueError, match="模型名"):
        OpenAICompatibleLLM()


async def test_env_vars_fill_missing_params(monkeypatch):
    with _fake_endpoint() as (recorded, url):
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        monkeypatch.setenv("OPENAI_MODEL", "env-model")
        result = await OpenAICompatibleLLM().summarize("正文")
    assert result == "假摘要。"
    assert recorded["body"]["model"] == "env-model"


def test_cli_demo_with_openai_llm_end_to_end(monkeypatch, capsys):
    with _fake_endpoint() as (_, url):
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        monkeypatch.setenv("OPENAI_MODEL", "fake-model")
        main(["demo", "--llm", "openai", "--hours", "0.1", "--no-correct"])
        out = capsys.readouterr().out
    assert "假摘要" in out
    assert "模型 fake-model" in out


def test_cli_openai_without_model_exits_with_hint(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(SystemExit, match="模型名"):
        main(["demo", "--llm", "openai"])
