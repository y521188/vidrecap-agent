"""OpenAI 兼容大模型适配器：把任意 OpenAI 风格的 chat 端点接进 LLMClient 插座。

HTTP 用标准库 urllib 发请求、asyncio.to_thread 包成异步，不加任何新依赖。
base_url / api_key / model 支持参数与环境变量两个来源（参数优先）：
``OPENAI_BASE_URL`` / ``OPENAI_API_KEY`` / ``OPENAI_MODEL``。

提示词只透传不内置：调用方给什么 instruction 就原样发什么（作为 system 消息），
本模块不夹带任何"调优过的提示词"——那属于闭源资产（见 AGENTS.md 第 10 节）。

关于请求目标的安全口径：base_url 由使用者自己配置（配置文件/环境变量），
本模块不接收任何外部不可信输入来构造 URL，因此不做私网地址封禁——
连本地 ollama、内网 vLLM 网关恰恰是核心用途。作为兜底约束：
只允许 http/https 协议，且不跟随重定向（3xx 直接报错，防止被借道跳走）。
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_ERROR_BODY_SNIPPET = 200

# 不跟随重定向：HTTPRedirectHandler 返回 None 时，3xx 会以 HTTPError 抛出
_NO_REDIRECT_OPENER = urllib.request.build_opener(
    type("_NoRedirect", (urllib.request.HTTPRedirectHandler,), {"redirect_request": None})
)


class OpenAICompatibleLLM:
    """OpenAI 兼容客户端：实现 external.protocols.LLMClient（形状对上即可）。"""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = (
            base_url or os.environ.get("OPENAI_BASE_URL") or _DEFAULT_BASE_URL
        ).rstrip("/")
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY") or ""
        # api_key 允许为空（本地端点不设鉴权），模型名没有默认值——猜一个只会误导
        self._model = model or os.environ.get("OPENAI_MODEL") or ""
        if not self._model:
            raise ValueError("缺少模型名：用 model 参数或环境变量 OPENAI_MODEL 指定")
        self._timeout = timeout

    @property
    def model(self) -> str:
        """实际生效的模型名（参数与环境变量合并后的结果）。"""
        return self._model

    async def summarize(self, text: str, instruction: str = "", system: str = "") -> str:
        return await asyncio.to_thread(
            self._post, self._build_messages(text, instruction, system)
        )

    @staticmethod
    def _build_messages(
        text: str, instruction: str, system: str
    ) -> list[dict[str, str]]:
        """双级约束分别成消息：system=角色与规则，user=本次要求，最后是正文。"""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if instruction:
            messages.append({"role": "user", "content": instruction})
        messages.append({"role": "user", "content": text})
        return messages

    def _post(self, messages: list[dict[str, str]]) -> str:
        url = f"{self._base_url}/chat/completions"
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError(f"仅支持 http(s) 端点，收到: {self._base_url!r}")
        request = urllib.request.Request(
            url,
            data=json.dumps(
                {"model": self._model, "messages": messages, "temperature": 0}
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with _NO_REDIRECT_OPENER.open(request, timeout=self._timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:_ERROR_BODY_SNIPPET]
            raise RuntimeError(f"模型服务返回 {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"模型请求失败: {exc}") from exc
        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"模型响应格式不符合预期: {body}") from exc
