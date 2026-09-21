"""服务化外壳测试：真起服务、真发请求，验证受理制、任务查询与错误路径。

请求固定连本机回环（主机字面量 127.0.0.1，端口取临时分配值，路径全为字面量）。
任务的打开方式：POST /recap 受理回 202 + job_id 后**立刻断开连接**，
再轮询 GET /jobs/<id> 到收尾——每条用例都顺带验证"断连不影响任务"。
"""

import contextlib
import http.client
import json
import threading
import time
from pathlib import Path
from urllib.parse import quote

from vidrecap.data.api import HistoryStore, JobStore, PipelineConfig
from vidrecap.external.api import VISUAL_PREFIX
from vidrecap.user.api import RecapRequest, build_server
from vidrecap.user.assembly import build_llm


@contextlib.contextmanager
def _running_server(history: HistoryStore | None = None, transcribers=None, diarizer=None, jobs: JobStore | None = None):
    """起在本机回环的临时端口上，用完即关。各部件默认不装配，要测就显式传。"""
    server = build_server(
        "127.0.0.1", 0, history=history, transcribers=transcribers, diarizer=diarizer, jobs=jobs
    )
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


def _stream_events(port: int, payload: dict, timeout: float = 60.0) -> list[tuple[str, dict]]:
    """提交任务后**立刻断开连接**，再轮询到收尾（事件序列与旧 SSE 语义一致）。"""
    connection = _connect(port)
    try:
        connection.request(
            "POST",
            "/recap",
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        if response.status != 202:
            raise AssertionError(f"受理应回 202，实际 {response.status}")
        job_id = json.loads(response.read().decode("utf-8"))["job_id"]
    finally:
        connection.close()  # 刻意马上断开：任务必须在服务端照跑

    deadline = time.time() + timeout
    while time.time() < deadline:
        _, body = _request(port, "GET", f"/jobs/{job_id}")
        task = json.loads(body)
        events = [("progress", p) for p in task["progress_events"]]
        if task["status"] == "done":
            events.append(("result", task["result"]))
            return events
        if task["status"] == "failed":
            events.append(("error", {"message": task["error"]}))
            return events
        time.sleep(0.05)
    raise TimeoutError("任务没有在时限内收尾")


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


def test_root_serves_console_page():
    """GET / 发操作台页面——页面由服务自带，不用另搭前端。"""
    with _running_server() as port:
        status, body = _request(port, "GET", "/")
    assert status == 200
    assert "<html" in body.lower()
    assert "操作台" in body
    # 服务商预设是用户直接面对的配置面：四家云端 + 本地 Ollama 都得在
    for needle in ("api.deepseek.com", "open.bigmodel.cn", "dashscope.aliyuncs.com", "api.openai.com", "11434"):
        assert needle in body, f"预设缺失: {needle}"


_MINI_SRT = (
    "1\n"
    "00:00:00,000 --> 00:00:02,000\n"
    "张伟介绍了新产品的核心功能。\n"
    "\n"
    "2\n"
    "00:00:02,000 --> 00:00:04,000\n"
    "他演示了三个使用场景。\n"
)


def test_recap_from_inline_srt_text():
    """操作台路径：字幕文本随请求带来，不要求调用方先把文件放到服务机磁盘上。"""
    with _running_server() as port:
        events = _stream_events(port, {"srt_text": _MINI_SRT, "no_correct": True})
    assert events[-1][0] == "result"
    result = events[-1][1]
    assert result["recap"]
    assert result["stats"]["shard_count"] >= 1


def test_srt_path_and_inline_text_conflict_is_400():
    with _running_server() as port:
        status, body = _request(
            port, "POST", "/recap", {"srt": "a.srt", "srt_text": _MINI_SRT}
        )
        video_too, _ = _request(port, "POST", "/recap", {"srt": "a.srt", "video": "b.mp4"})
    assert status == 400
    assert "三选一" in body
    assert video_too == 400


def test_undecodable_inline_srt_reports_error_event():
    with _running_server() as port:
        events = _stream_events(port, {"srt_text": "没有时间轴的纯文本"})
    assert events[-1][0] == "error"


def test_history_records_successful_runs(tmp_path):
    """成功任务自动归档；列表不带正文，详情才取；查无此记录回 404。"""
    with _running_server(history=HistoryStore(tmp_path / "history.jsonl")) as port:
        events = _stream_events(
            port,
            {"srt_text": _MINI_SRT, "srt_name": "demo.srt", "no_correct": True},
        )
        assert events[-1][0] == "result"

        status, body = _request(port, "GET", "/history")
        records = json.loads(body)["records"]
        assert status == 200
        assert len(records) == 1
        assert "recap" not in records[0]  # 列表轻量：正文点详情再取
        assert records[0]["source_name"] == "demo.srt"

        detail_status, detail_body = _request(
            port, "GET", "/history/" + records[0]["id"]
        )
        detail = json.loads(detail_body)
        assert detail_status == 200
        assert detail["recap"] == events[-1][1]["recap"]

        missing_status, _ = _request(port, "GET", "/history/no-such-id")
        assert missing_status == 404


def test_failed_run_is_archived_with_error(tmp_path):
    """失败也入档（留遗书）：历史区不再"查无此人"。"""
    with _running_server(history=HistoryStore(tmp_path / "history.jsonl")) as port:
        events = _stream_events(port, {"srt_text": "没有时间轴的纯文本"})
        assert events[-1][0] == "error"
        _, body = _request(port, "GET", "/history")
    record = json.loads(body)["records"][0]
    assert record["status"] == "failed"
    assert "时间轴" in record["error"]


def test_job_survives_client_disconnect():
    """受理制的命脉：客户端拿了号就走，任务照跑，回头凭号取结果。"""
    with _running_server() as port:
        connection = _connect(port)
        try:
            connection.request(
                "POST",
                "/recap",
                body=json.dumps({"hours": 0.2, "no_correct": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            assert response.status == 202
            job_id = json.loads(response.read().decode("utf-8"))["job_id"]
        finally:
            connection.close()  # 马上断开，不做任何轮询

        deadline = time.time() + 30
        task = None
        while time.time() < deadline:
            _, body = _request(port, "GET", f"/jobs/{job_id}")
            task = json.loads(body)
            if task["status"] in ("done", "failed"):
                break
            time.sleep(0.05)
    assert task is not None and task["status"] == "done"
    assert task["result"]["recap"]


def test_unknown_job_is_404():
    with _running_server() as port:
        status, _ = _request(port, "GET", "/jobs/no-such-id")
    assert status == 404


def test_job_result_survives_server_restart(tmp_path):
    """重启自愈（已完成）：同一个任务簿重新起服务，凭号仍能取到结果。"""
    jobs = JobStore(tmp_path / "jobs")

    def _submit_and_wait(port):
        connection = _connect(port)
        try:
            connection.request(
                "POST",
                "/recap",
                body=json.dumps({"srt_text": _MINI_SRT, "no_correct": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            assert response.status == 202
            job_id = json.loads(response.read().decode("utf-8"))["job_id"]
        finally:
            connection.close()
        deadline = time.time() + 30
        while time.time() < deadline:
            _, body = _request(port, "GET", f"/jobs/{job_id}")
            task = json.loads(body)
            if task["status"] in ("done", "failed"):
                return job_id, task
            time.sleep(0.05)
        raise TimeoutError("任务没有在时限内收尾")

    with _running_server(jobs=jobs) as port:
        job_id, task = _submit_and_wait(port)
    assert task["status"] == "done"

    # "重启"：同一个任务簿目录重新起一个服务实例
    with _running_server(jobs=jobs) as port:
        status, body = _request(port, "GET", f"/jobs/{job_id}")
    restarted = json.loads(body)
    assert status == 200
    assert restarted["status"] == "done"
    assert restarted["result"]["recap"] == task["result"]["recap"]


def test_running_jobs_marked_interrupted_on_restart(tmp_path):
    """重启自愈（未完成）：上个进程留下的 running 任务标成 interrupted 并指路。"""
    jobs = JobStore(tmp_path / "jobs")
    jobs.save("a" * 12, {"status": "running", "progress": {"done": 5, "total": 10}})
    with _running_server(jobs=jobs) as port:
        status, body = _request(port, "GET", "/jobs/" + "a" * 12)
    snapshot = json.loads(body)
    assert status == 200
    assert snapshot["status"] == "interrupted"
    assert "重新提交" in snapshot["error"]


def test_malformed_job_id_is_404(tmp_path):
    """任务号是文件名的一部分：不像号的一律 404，不给路径穿越留门。"""
    jobs = JobStore(tmp_path / "jobs")
    with _running_server(jobs=jobs) as port:
        status, _ = _request(port, "GET", "/jobs/../../secrets")
        ok_status, _ = _request(port, "GET", "/jobs/" + "a" * 12)
    assert status == 404
    assert ok_status == 404  # 合法形状但不存在：同样 404


def test_transcription_cache_skips_second_transcribe(tmp_path):
    """同一视频重跑：第二次直接吃转写缓存，不再调转写器。"""
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake-video-bytes")
    transcriber = _FakeTranscriber()
    with _running_server(transcribers={"whisper": transcriber}) as port:
        payload = {"video": str(media), "no_correct": True}
        first = _stream_events(port, payload)
        second = _stream_events(port, payload)
    assert [c[0] for c in transcriber.calls] == [str(media)]
    assert not any(p.get("cached") for kind, p in first if kind == "progress")
    assert any(p.get("cached") for kind, p in second if kind == "progress")


def test_history_disabled_returns_empty_list():
    """不启用档案（build_server 不传 history）时接口仍在，恒回空列表。"""
    with _running_server() as port:
        status, body = _request(port, "GET", "/history")
        detail_status, _ = _request(port, "GET", "/history/anything")
    assert status == 200
    assert json.loads(body)["records"] == []
    assert detail_status == 404


class _FakeTranscriber:
    """测试替身：不跑真模型，回固定字幕条目并推一次转写进度。"""

    def __init__(self, entries=None):
        self.calls = []
        self._entries = entries if entries is not None else [
            (0.0, 2.0, "张伟介绍了新产品的核心功能。"),
            (2.0, 4.0, "他演示了三个使用场景。"),
        ]

    def transcribe(self, path, language=None, on_progress=None):
        self.calls.append((path, language))
        if on_progress is not None and self._entries:
            done, total = self._entries[-1][1], self._entries[-1][1] + 10
            on_progress(done, total)
        return self._entries


def _upload(port: int, filename: str, payload: bytes):
    """POST /upload：原始字节 + URL 编码文件名，返回 (状态码, 响应 JSON)。"""
    connection = _connect(port)
    try:
        connection.request(
            "POST",
            "/upload",
            body=payload,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Filename": quote(filename),
            },
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode())
    finally:
        connection.close()


def test_upload_sanitizes_filename_and_stores_bytes(tmp_path):
    with _running_server() as port:
        status, data = _upload(port, "../../会议 纪要.mp4", b"fake-bytes")
    assert status == 200
    assert ".." not in data["name"]
    assert " " not in data["name"]
    stored = Path(data["path"])
    assert stored.parent.name == "uploads"
    assert stored.read_bytes() == b"fake-bytes"
    stored.unlink()  # 测试落盘的临时上传物顺手清掉


def test_recap_from_uploaded_video_uses_transcriber(tmp_path):
    """视频路径：先转写（进度带"转写"阶段标记）再进流水线，语言原样传给适配器。"""
    transcriber = _FakeTranscriber()
    with _running_server(
        history=HistoryStore(tmp_path / "history.jsonl"), transcribers={"whisper": transcriber}
    ) as port:
        events = _stream_events(
            port, {"video": "D:/tmp/fake.mp4", "language": "zh", "srt_name": "会议.mp4"}
        )
        _, history_body = _request(port, "GET", "/history")

    kinds = [kind for kind, _ in events]
    assert kinds[-1] == "result"
    assert events[-1][1]["recap"]
    stages = [data.get("stage") for kind, data in events if kind == "progress"]
    assert "转写" in stages
    assert transcriber.calls == [("D:/tmp/fake.mp4", "zh")]
    record = json.loads(history_body)["records"][0]
    assert record["source_name"] == "会议.mp4"


def test_video_without_transcriber_reports_error_event():
    """没装配语音识别时视频入口要明确报错指路，不许悄悄降级。"""
    with _running_server() as port:
        events = _stream_events(port, {"video": "whatever.mp4"})
    assert events[-1][0] == "error"
    assert "语音识别" in events[-1][1]["message"]


def test_video_with_no_speech_reports_error_event():
    silent = _FakeTranscriber(entries=[])
    with _running_server(transcribers={"whisper": silent}) as port:
        events = _stream_events(port, {"video": "silence.mp4"})
    assert events[-1][0] == "error"
    assert "识别到任何语音" in events[-1][1]["message"]


def test_visual_without_video_is_400():
    with _running_server() as port:
        status, body = _request(port, "POST", "/recap", {"visual": True})
        diarize_status, diarize_body = _request(port, "POST", "/recap", {"diarize": True})
    assert status == 400
    assert "视频" in body
    assert diarize_status == 400
    assert "视频" in diarize_body


class _FakeDiarizer:
    """测试替身：两句字幕正好换一次说话人，并记下传进来的语音段。"""

    def __init__(self):
        self.calls = []
        self.spans = None

    def diarize(self, path, on_progress=None, speech_spans=None):
        self.calls.append(path)
        self.spans = speech_spans
        if on_progress is not None:
            on_progress(1, 1)
        return [(0.0, 2.0, "说话人1"), (2.0, 4.0, "说话人2")]


def test_diarize_labels_recap_and_archives(tmp_path):
    diarizer = _FakeDiarizer()
    with _running_server(
        history=HistoryStore(tmp_path / "history.jsonl"),
        transcribers={"whisper": _FakeTranscriber()},
        diarizer=diarizer,
    ) as port:
        events = _stream_events(port, {"video": "demo.mp4", "diarize": True, "no_correct": True})
        _, history_body = _request(port, "GET", "/history")

    kinds = [kind for kind, _ in events]
    assert kinds[-1] == "result"
    recap = events[-1][1]["recap"]
    assert "说话人1：张伟介绍了新产品的核心功能。" in recap
    assert "说话人2：他演示了三个使用场景。" in recap
    stages = [data.get("stage") for kind, data in events if kind == "progress"]
    assert "分人" in stages
    assert diarizer.calls == ["demo.mp4"]
    assert diarizer.spans == [(0.0, 2.0), (2.0, 4.0)]  # 转写句段原样传给分离器
    record = json.loads(history_body)["records"][0]
    assert record["diarize"] is True


def test_diarize_without_diarizer_reports_error_event():
    with _running_server(transcribers={"whisper": _FakeTranscriber()}) as port:  # 只装转写，不装分人
        events = _stream_events(port, {"video": "demo.mp4", "diarize": True})
    assert events[-1][0] == "error"
    assert "说话人分离" in events[-1][1]["message"]


def test_visual_track_merges_into_recap(tmp_path, monkeypatch):
    """画面轨：抽帧（打桩免 ffmpeg）→ 演示描述 → 并入字幕，进度带"画面"阶段。"""

    def _fake_extract(video, out_dir, interval, max_frames):
        out = tmp_path / "frames"
        out.mkdir(exist_ok=True)
        paths = []
        for name in ("f0.jpg", "f1.jpg"):
            path = out / name
            path.write_bytes(b"fake-jpeg")
            paths.append(path)
        return [(0.0, paths[0]), (3.0, paths[1])]

    monkeypatch.setattr(
        "vidrecap.user.server.server.extract_frames", _fake_extract
    )
    with _running_server(
        history=HistoryStore(tmp_path / "history.jsonl"), transcribers={"whisper": _FakeTranscriber()}
    ) as port:
        events = _stream_events(
            port, {"video": "demo.mp4", "visual": True, "no_correct": True}
        )
        _, history_body = _request(port, "GET", "/history")

    kinds = [kind for kind, _ in events]
    assert kinds[-1] == "result"
    assert VISUAL_PREFIX in events[-1][1]["recap"]  # 画面行已并入时间线
    stages = [data.get("stage") for kind, data in events if kind == "progress"]
    assert "转写" in stages and "画面" in stages
    record = json.loads(history_body)["records"][0]
    assert record["visual"] is True


def test_build_llm_passes_connection_through():
    """页面上填的连接信息原样落到客户端；不填时仍由适配器回落环境变量。"""
    client = build_llm(
        "openai", "m1", base_url="http://127.0.0.1:9/v1", api_key="k-test"
    )
    assert client._model == "m1"
    assert client._base_url == "http://127.0.0.1:9/v1"
    assert client._api_key == "k-test"
