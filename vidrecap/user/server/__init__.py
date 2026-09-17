"""服务化外壳：HTTP + SSE 常驻服务（零依赖），实现住在 server.py。"""

from vidrecap.user.server.server import RecapRequest, build_server, serve

__all__ = ["RecapRequest", "build_server", "serve"]
