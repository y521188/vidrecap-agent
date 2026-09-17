"""HTTP 服务化外壳：把引擎包成一个常驻服务，进度边跑边推。

零依赖：标准库 http.server + JSON + SSE（就是"服务器持续往下推消息"的
文本协议）。一个请求跑一个任务，事件流长这样：

    event: progress   data: {"done": 3, "total": 18}
    event: result     data: {"recap": "...", "stats": {...}}
    event: error      data: {"message": "..."}

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
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from vidrecap.data.api import PipelineConfig, RecapResult, SpeakerPolicyConfig, TaskStore
from vidrecap.external.api import DemoCatalog
from vidrecap.service.api import run_recap
from vidrecap.user.assembly import build_config, build_llm, build_quality, build_source
from vidrecap.user.skills import load_skill

_MAX_JOBS = 2
_JOBS = threading.BoundedSemaphore(_MAX_JOBS)


class RecapRequest(BaseModel):
    """一次摘要请求：字段与命令行开关一一对应，给 None 的沿用数据层默认值。

    这是服务的信任边界，逐字段校验：坏参数回 400，不进流水线。
    """

    model_config = ConfigDict(extra="forbid")  # 拼错字段直接回 400，别静默忽略

    srt: str | None = None
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


async def _run_job(request: RecapRequest, send) -> RecapResult:
    """装配后交给服务层；进度回调转成 SSE 事件推给调用方。"""
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
            build_source(request.srt, request.hours),
            build_llm(request.llm, request.model),
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


class _Handler(BaseHTTPRequestHandler):
    # HTTP/1.0 + Connection: close：事件流以连接关闭收尾，不需要 Content-Length
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:  # noqa: N802（标准库要求的命名）
        if self.path == "/health":
            self._send_json({"status": "ok"})
        else:
            self._send_json({"message": "未知路径"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
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
        if not _JOBS.acquire(blocking=False):
            self._send_json({"message": f"服务忙（同时最多 {_MAX_JOBS} 个任务），稍后再试"}, status=429)
            return
        try:
            self._stream(request)
        finally:
            _JOBS.release()

    def _stream(self, request: RecapRequest) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            result = asyncio.run(_run_job(request, self._event))
        except Exception as exc:
            self._event("error", {"message": str(exc)})
            return
        self._event("result", {"recap": result.recap, "stats": result.stats.model_dump()})

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


def build_server(host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    """造好服务实例但不起线程——测试用它拿随机端口。"""
    server = ThreadingHTTPServer((host, port), _Handler)
    server.daemon_threads = True
    return server


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    """常驻监听；Ctrl+C 结束。默认只绑本机（不含鉴权，对外请加反代）。"""
    server = build_server(host, port)
    # flush：日志重定向到文件时是块缓冲，启动提示不能憋在缓冲区里
    print(f"vidrecap 服务已启动: http://{host}:{port}", flush=True)
    print(
        "  POST /recap  跑一次摘要，SSE 推 progress / result / error\n"
        "  GET  /health 探活",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
