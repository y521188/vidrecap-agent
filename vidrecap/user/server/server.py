"""HTTP 服务化外壳：把引擎包成一个常驻服务，进度边跑边推。

零依赖：标准库 http.server + JSON + SSE（就是"服务器持续往下推消息"的
文本协议）。一个请求跑一个任务，事件流长这样：

    event: progress   data: {"done": 3, "total": 18}
    event: result     data: {"recap": "...", "stats": {...}}
    event: error      data: {"message": "..."}

GET / 直接发一份单文件操作台页面（page.html）：浏览器里选字幕、填钥匙、
点开始看进度——不用另搭前端，页面与钥匙只在本机流转。

成功的任务自动进历史档案（HistoryStore，数据层）：GET /history 回看列表
（不带概括正文），GET /history/<id> 取单条详情。历史由常驻入口决定是否
启用（命令行 --history / --no-history），测试默认不落盘。

视频/音频直传：POST /upload 收原始字节存进 .vidrecap/uploads/，
/recap 带 video 路径时先用语音识别（外部层 whisper 适配器，可选装配）
转成字幕再进流水线——转写进度也走同一个 progress 事件（带 stage 标记）。

为什么先不上 gRPC：服务化的价值在"常驻、被调用、推进度"这个形态，不在协议。
等有了明确的 gRPC 生态对接方，再按"加依赖先问"换实现——接口契约到那时已稳定，
换实现是局部改动。

三条边界，都是有意为之：

- **默认只监听 127.0.0.1**：本外壳不含鉴权，对外暴露请自己加反向代理与鉴权；
- **同时跑的任务数有上限**（超了回 429，不排队），防止一次涌进来的请求把机器打满；
- **每请求一个线程、各自一个事件循环**：流水线本身是异步的，用
  ``asyncio.run`` 在请求线程里跑完即可，不需要全局事件循环那套机器。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from pydantic import BaseModel, ConfigDict, Field

from vidrecap.data.api import (
    HistoryStore,
    PipelineConfig,
    RecapResult,
    RunRecord,
    SpeakerPolicyConfig,
    TaskStore,
)
from vidrecap.external.api import (
    DemoCatalog,
    Diarizer,
    Transcriber,
    apply_speakers,
    extract_frames,
    merge_tracks,
    to_srt_text,
)
from vidrecap.service.api import run_recap
from vidrecap.user.assembly import (
    build_config,
    build_diarizer,
    build_llm,
    build_quality,
    build_source,
    build_vision,
)
from vidrecap.user.skills import load_skill

_MAX_JOBS = 2
_JOBS = threading.BoundedSemaphore(_MAX_JOBS)
_MAX_UPLOAD_BYTES = 2 * 1024**3  # 2GB：本地工具的上限，防的是失误不是恶意

# 与外挂脚本 video2recap 同一句提示词：口径只写一处做不到（脚本不进包），
# 但两边都从需求出发措辞一致，改时记得同步
_VISION_PROMPT = "用一句话描述这张视频画面：谁在做什么、画面上有什么关键文字。不超过 40 字。"

# 操作台页面：每次请求现读现发，改了 HTML 不用重启服务
_PAGE_PATH = Path(__file__).with_name("page.html")


class RecapRequest(BaseModel):
    """一次摘要请求：字段与命令行开关一一对应，给 None 的沿用数据层默认值。

    四个字段是操作台专有、命令行没有的：base_url / api_key（页面上当场填
    连接信息，优先于服务进程的环境变量）、srt_text（字幕文本随请求体直接
    带来，免得要求调用方先把文件放到服务所在机器的磁盘上）与 srt_name
    （选中的字幕文件名，只进历史档案当标签，不参与计算）。
    另有两个视频专有字段：video（POST /upload 返回的服务端路径，先语音
    转写字幕再进流水线）与 language（视频语音语言，空=自动检测）。
    画面轨四件套：visual（开画面分析，只对视频生效）、frame_interval /
    max_frames（抽帧密度与成本上限，默认与外挂脚本一致 120 秒 / 200 帧）、
    vision_model（视觉模型名，留空=同摘要模型；demo 引擎用离线演示描述）。
    diarize（说话人分离）：声纹聚类分出说话人并给字幕贴标签，只对视频生效。
    这是服务的信任边界，逐字段校验：坏参数回 400，不进流水线。
    """

    model_config = ConfigDict(extra="forbid")  # 拼错字段直接回 400，别静默忽略

    srt: str | None = None
    srt_text: str | None = None
    srt_name: str | None = None
    video: str | None = None
    language: str | None = None
    visual: bool = False
    diarize: bool = False
    frame_interval: float = Field(default=120.0, gt=0)
    max_frames: int = Field(default=200, gt=0)
    vision_model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    hours: float = Field(default=3.0, gt=0)
    llm: Literal["demo", "openai"] = "demo"
    model: str | None = None
    instruction: str | None = None
    skill: str | None = None
    catalog: bool = False
    store: str | None = None
    no_correct: bool = False
    threshold: float | None = Field(default=None, ge=0, le=1)
    weights: list[float] | None = Field(default=None, min_length=3, max_length=3)
    shard_seconds: float | None = Field(default=None, gt=0)
    overlap_seconds: float | None = Field(default=None, ge=0)
    context_limit: int | None = Field(default=None, gt=0)
    max_concurrency: int | None = Field(default=None, gt=0)


def _quality_from(request: RecapRequest, skill) -> tuple:
    threshold = request.threshold if request.threshold is not None else (skill.threshold if skill else None)
    weights = request.weights if request.weights is not None else (skill.weights if skill else None)
    return build_quality(
        disabled=request.no_correct, threshold=threshold, weights=weights
    )


async def _run_job(
    request: RecapRequest,
    send,
    transcriber: Transcriber | None,
    diarizer: Diarizer | None,
) -> RecapResult:
    """装配后交给服务层；进度回调转成 SSE 事件推给调用方。

    带视频时三步走：转写 →（可选）说话人分离贴标签 →（可选）画面轨，
    转出的字幕当内联文本走同一个入口——后面的流水线对"字幕哪来的"一无所知。
    """
    srt_text = request.srt_text
    if request.video is not None:
        if transcriber is None:
            raise ValueError(
                "服务端未装配语音识别：装 faster-whisper 后重启，或用 --no-whisper 明确关闭"
            )

        def _transcribing(done: float, total: float) -> None:
            send(
                "progress",
                {"stage": "转写", "done": round(done, 1), "total": round(total, 1)},
            )

        entries = await asyncio.to_thread(
            transcriber.transcribe, request.video, request.language, _transcribing
        )
        if not entries:
            raise ValueError("没从文件里识别到任何语音（静音片段或不是音视频文件？）")
        if request.diarize:
            if diarizer is None:
                raise ValueError(
                    "服务端未装配说话人分离：装 sherpa-onnx 后重启服务"
                )

            def _separating(done: int, total: int) -> None:
                send(
                    "progress",
                    {"stage": "分人", "done": done, "total": max(total, 1)},
                )

            turns = await asyncio.to_thread(diarizer.diarize, request.video, _separating)
            entries = apply_speakers(entries, turns)
        if request.visual:
            visual_events = await _visual_events(request, send)
            if visual_events:
                entries = merge_tracks(entries, visual_events)
        srt_text = to_srt_text(entries)
    skill = load_skill(request.skill) if request.skill else None
    config: PipelineConfig = build_config(
        shard_seconds=request.shard_seconds,
        overlap_seconds=request.overlap_seconds,
        max_concurrency=request.max_concurrency,
        context_limit=request.context_limit,
        instruction=request.instruction or (skill.summarize_instruction if skill else None),
        system_prompt=skill.system_prompt if skill else None,
    )
    scorer, corrector, quality_config = _quality_from(request, skill)
    store = (
        TaskStore(request.store, namespace=f"{request.llm}:{request.model or ''}")
        if request.store
        else None
    )
    try:
        return await run_recap(
            build_source(request.srt, request.hours, srt_text=srt_text),
            build_llm(
                request.llm,
                request.model,
                base_url=request.base_url,
                api_key=request.api_key,
            ),
            config,
            on_progress=lambda done, total: send(
                "progress", {"done": done, "total": total}
            ),
            scorer=scorer,
            corrector=corrector,
            quality_config=quality_config,
            store=store,
            catalog=DemoCatalog(hours=request.hours) if request.catalog else None,
            speaker_config=(
                SpeakerPolicyConfig(min_share=skill.min_share)
                if skill and skill.min_share is not None
                else None
            ),
        )
    finally:
        if store is not None:
            store.close()


async def _visual_events(request: "RecapRequest", send) -> list[tuple[float, str]]:
    """抽帧并逐帧请视觉模型描述；进度按帧推（stage=画面）。

    抽帧是 ffmpeg 的阻塞活放线程池；帧图留在 .vidrecap/frames/ 便于事后核对。
    """
    frames_dir = Path(".vidrecap") / "frames" / uuid.uuid4().hex[:8]
    frames = await asyncio.to_thread(
        extract_frames, request.video, frames_dir,
        request.frame_interval, request.max_frames,
    )
    if not frames:
        return []
    vision = build_vision(
        request.llm,
        request.vision_model or request.model,
        base_url=request.base_url,
        api_key=request.api_key,
    )
    events: list[tuple[float, str]] = []
    for index, (timestamp, path) in enumerate(frames, start=1):
        text = " ".join(
            (await vision.describe_image(path.read_bytes(), _VISION_PROMPT)).split()
        )
        if text:  # 空结果丢弃，不让空行污染时间线
            events.append((timestamp, text))
        send("progress", {"stage": "画面", "done": index, "total": len(frames)})
    return events


class _Handler(BaseHTTPRequestHandler):
    # HTTP/1.0 + Connection: close：事件流以连接关闭收尾，不需要 Content-Length
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:  # noqa: N802（标准库要求的命名）
        if self.path == "/":
            self._send_page()
        elif self.path == "/health":
            self._send_json({"status": "ok"})
        elif self.path == "/history":
            self._send_history_list()
        elif self.path.startswith("/history/"):
            self._send_history_detail(self.path[len("/history/") :])
        else:
            self._send_json({"message": "未知路径"}, status=404)

    def _send_history_list(self) -> None:
        history: HistoryStore | None = self.server.history
        records = history.latest() if history is not None else []
        # 列表不带概括正文：历史会越攒越长，正文等点开详情再取
        self._send_json(
            {"records": [record.model_dump(exclude={"recap"}) for record in records]}
        )

    def _send_history_detail(self, record_id: str) -> None:
        history: HistoryStore | None = self.server.history
        record = history.get(record_id) if history is not None else None
        if record is None:
            self._send_json({"message": "查无此记录"}, status=404)
            return
        self._send_json(record.model_dump())

    def _send_page(self) -> None:
        body = _PAGE_PATH.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/upload":
            self._receive_upload()
            return
        if self.path != "/recap":
            self._send_json({"message": "未知路径"}, status=404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) or b"{}"
        try:
            request = RecapRequest.model_validate_json(body)
        except Exception as exc:  # pydantic 的报文很长，只回要点
            self._send_json({"message": f"请求不合法: {exc}"}, status=400)
            return
        sources = sum(bool(item) for item in (request.srt, request.srt_text, request.video))
        if sources > 1:
            self._send_json(
                {"message": "srt 路径、srt_text 内联文本与 video 视频文件只能三选一"},
                status=400,
            )
            return
        if request.visual and request.video is None:
            self._send_json(
                {"message": "画面分析（visual）只对视频文件生效，请上传视频"}, status=400
            )
            return
        if request.diarize and request.video is None:
            self._send_json(
                {"message": "说话人分离（diarize）只对视频/音频文件生效，请上传文件"},
                status=400,
            )
            return
        if not _JOBS.acquire(blocking=False):
            self._send_json({"message": f"服务忙（同时最多 {_MAX_JOBS} 个任务），稍后再试"}, status=429)
            return
        try:
            self._stream(request)
        finally:
            _JOBS.release()

    def _receive_upload(self) -> None:
        """原始字节 + X-Filename 头 → 存进 .vidrecap/uploads/，回服务端路径。

        特意不解析 multipart（标准库的 cgi 已废弃、3.13 移除）：页面把文件
        读成字节流整个 POST 上来，头里带 URL 编码的文件名，零依赖够用。
        文件名只留安全字符——路径穿越在这里就掐死。
        """
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self._send_json({"message": "上传内容为空"}, status=400)
            return
        if length > _MAX_UPLOAD_BYTES:
            self._send_json({"message": f"文件超过 {_MAX_UPLOAD_BYTES // 1024**3}GB 上限"}, status=413)
            return
        raw_name = unquote(self.headers.get("X-Filename", "upload.bin"))
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(raw_name).name) or "upload.bin"
        dest_dir = Path(".vidrecap") / "uploads"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{uuid.uuid4().hex[:8]}_{safe_name}"
        remaining = length
        with dest.open("wb") as fh:
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                fh.write(chunk)
                remaining -= len(chunk)
        if remaining > 0:
            dest.unlink(missing_ok=True)
            self._send_json({"message": "上传中断，字节数与声明不符"}, status=400)
            return
        self._send_json({"path": str(dest.resolve()), "name": safe_name})

    def _stream(self, request: RecapRequest) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            result = asyncio.run(
                _run_job(request, self._event, self.server.transcriber, self.server.diarizer)
            )
        except Exception as exc:
            self._event("error", {"message": str(exc)})
            return
        self._event("result", {"recap": result.recap, "stats": result.stats.model_dump()})
        self._archive(request, result)

    def _archive(self, request: RecapRequest, result: RecapResult) -> None:
        """成功任务进历史档案。落盘失败不影响已经推完的结果，只往控制台打日志。"""
        history: HistoryStore | None = self.server.history
        if history is None:
            return
        record = RunRecord(
            id=uuid.uuid4().hex[:12],
            created_at=time.time(),
            llm=request.llm,
            model=request.model or "",
            source_name=request.srt_name
            or (Path(request.srt).name if request.srt else "")
            or (Path(request.video).name if request.video else ""),
            hours=request.hours,
            instruction=request.instruction or "",
            catalog=request.catalog,
            no_correct=request.no_correct,
            visual=request.visual,
            diarize=request.diarize,
            recap=result.recap,
            stats=result.stats,
        )
        try:
            history.append(record)
        except OSError as exc:
            print(f"历史落盘失败（结果不受影响）: {exc}", file=sys.stderr, flush=True)

    def _event(self, event: str, data: dict) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        self.wfile.write(payload.encode("utf-8"))
        self.wfile.flush()

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass  # 静音：默认的每请求一行日志对服务化场景是噪音


def build_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    history: HistoryStore | None = None,
    transcriber: Transcriber | None = None,
    diarizer: Diarizer | None = None,
) -> ThreadingHTTPServer:
    """造好服务实例但不起线程——测试用它拿随机端口。

    history 为 None 时查询接口仍在、恒回空列表；transcriber / diarizer 为
    None 时对应入口直接报错指路（测试默认全部不装配，不落盘、不装模型）。
    是否启用由调用方（常驻入口 / 命令行）决定。
    """
    server = ThreadingHTTPServer((host, port), _Handler)
    server.daemon_threads = True
    server.history = history
    server.transcriber = transcriber
    server.diarizer = diarizer
    return server


def serve(
    host: str = "127.0.0.1",
    port: int = 8080,
    history: HistoryStore | None = None,
    transcriber: Transcriber | None = None,
    diarizer: Diarizer | None = None,
) -> None:
    """常驻监听；Ctrl+C 结束。默认只绑本机（不含鉴权，对外请加反代）。"""
    server = build_server(
        host, port, history=history, transcriber=transcriber, diarizer=diarizer
    )
    # flush：日志重定向到文件时是块缓冲，启动提示不能憋在缓冲区里
    print(f"vidrecap 服务已启动: http://{host}:{port}", flush=True)
    print(
        "  GET  /       浏览器操作台：选字幕、填钥匙、点开始看进度\n"
        "  POST /recap  跑一次摘要，SSE 推 progress / result / error\n"
        "  POST /upload 上传视频/音频（装配了语音识别时 /recap 可带 video 直转）\n"
        "  GET  /health 探活\n"
        "  GET  /history 历史记录列表；/history/<id> 单条详情",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
