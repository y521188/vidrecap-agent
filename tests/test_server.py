"""服务化外壳测试：真起服务、真发请求，验证事件流与错误路径。

请求固定连本机回环（主机字面量 127.0.0.1，端口取临时分配值，路径全为字面量），
不构造任何外部地址；用 http.client 直连是为了能逐行读事件流。
"""

import contextlib
import http.client
import json
import threading

from vidrecap.data.api import PipelineConfig
from vidrecap.user.api import RecapRequest, build_server


@contextlib.contextmanager
def _running_server():
    """起在本机回环的临时端口上，用完即关。"""
    server = build_server("127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def _connect(port: int) -> http.client.HTTPConnection:
    return http.client.HTTPConnection("127.0.0.1", port, timeout=30)


def _request(port: int, method: str, path: str, payload: dict | None = None):
    """发一个请求，返回 (状态码, 响应体文本)。"""
    connection = _connect(port)
    try:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        connection.request(
            method, path, body=body, headers={"Content-Type": "application/json"}
        )
        response = connection.getresponse()
        return response.status, response.read().decode("utf-8")
    finally:
        connection.close()


def _stream_events(port: int, payload: dict) -> list[tuple[str, dict]]:
    """逐行读事件流，边到边解（验证"边跑边推"的关键就在这里）。"""
    events: list[tuple[str, dict]] = []
    connection = _connect(port)
    try:
        connection.request(
            "POST",
            "/recap",
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        event = ""
        while True:
            raw = response.readline()
            if not raw:
                break
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                events.append((event, json.loads(line[len("data: ") :])))
        return events
    finally:
        connection.close()


def test_health_endpoint():
    with _running_server() as port:
        status, body = _request(port, "GET", "/health")
    assert status == 200
    assert json.loads(body)["status"] == "ok"


def test_recap_streams_progress_then_result():
    with _running_server() as port:
        events = _stream_events(port, {"hours": 0.2, "no_correct": True})

    kinds = [kind for kind, _ in events]
    assert kinds[-1] == "result"
    progress = [data for kind, data in events if kind == "progress"]
    assert progress, "进度必须边跑边推"
    assert progress[-1] == {"done": 2, "total": 2}
    result = events[-1][1]
    assert result["recap"]
    assert result["stats"]["shard_count"] == 2


def test_unknown_path_is_404():
    with _running_server() as port:
        status, _ = _request(port, "POST", "/nope", {})
        get_status, _ = _request(port, "GET", "/nope")
    assert status == 404
    assert get_status == 404


def test_invalid_request_is_400():
    with _running_server() as port:
        bad_value, _ = _request(port, "POST", "/recap", {"hours": -1})
        typo, _ = _request(port, "POST", "/recap", {"hourse": 3})  # 拼错字段名不许静默忽略
    assert bad_value == 400
    assert typo == 400


def test_request_defaults_defer_to_data_layer():
    """请求模型不重复声明数字：没给的字段用数据层配置的默认值。"""
    request = RecapRequest()
    assert request.hours == 3.0
    assert request.shard_seconds is None
    assert PipelineConfig().shard_seconds == 600.0
    assert PipelineConfig().summarize_instruction
