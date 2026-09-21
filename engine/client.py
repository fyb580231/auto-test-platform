"""HTTP 客户端封装：超时 / 重试 / 日志 / 变量渲染。

为什么自己封装一层而不直接暴露 httpx？
1. 统一超时与重试策略，用例里不需要关心网络抖动；
2. 自动渲染 ``{{变量}}`` 占位符，实现环境隔离；
3. 输出「可被报告与 AI 消费」的结构化请求/响应对象。
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

DEFAULT_TIMEOUT: float = 15.0
DEFAULT_RETRIES: int = 2
RETRY_BACKOFF: float = 0.4
RETRY_STATUS_CODES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})

_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([\w.\-]+)\s*\}\}")
_SENSITIVE_HEADERS: frozenset[str] = frozenset({"authorization", "cookie", "x-api-key", "token"})


def render_template(value: Any, variables: Mapping[str, Any] | None = None) -> Any:
    """递归渲染 ``{{变量名}}`` 占位符。

    Args:
        value: 任意结构（字符串 / 字典 / 列表 / 其他）。
        variables: 变量字典；为空时原样返回字符串。

    Returns:
        渲染后的同构结构。未匹配到的占位符保持原样，方便定位配置缺失。
    """
    variables = variables or {}
    if isinstance(value, str):

        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key in variables:
                return str(variables[key])
            logger.debug("变量 {} 未定义，占位符保持原样", key)
            return match.group(0)

        return _PLACEHOLDER_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {key: render_template(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [render_template(item, variables) for item in value]
    return value


@dataclass(slots=True)
class ApiResponse:
    """引擎层统一的响应对象。

    Attributes:
        status_code: HTTP 状态码。
        headers: 响应头（小写键）。
        text: 原始响应文本。
        body: 反序列化后的响应体；非 JSON 时等于原始文本。
        elapsed_ms: 请求耗时（毫秒）。
        request: 可序列化的请求快照，便于报告展示。
    """

    status_code: int
    headers: dict[str, str]
    text: str
    body: Any
    elapsed_ms: float
    request: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """状态码是否落在 2xx / 3xx 区间。"""
        return 200 <= self.status_code < 400

    @property
    def is_json(self) -> bool:
        """响应体是否为合法 JSON。"""
        return isinstance(self.body, dict | list)

    def to_dict(self, max_text_length: int = 4000) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。

        Args:
            max_text_length: 原始文本截断长度，避免日志/报告体积失控。

        Returns:
            字典结构。
        """
        return {
            "status_code": self.status_code,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "headers": self.headers,
            "body": self.body,
            "text": self.text[:max_text_length],
        }


class ApiClient:
    """httpx 封装客户端。

    Attributes:
        base_url: 默认前缀，用例中写相对路径时会自动拼接。
        default_headers: 全局请求头（通常来自环境配置）。
        timeout: 单次请求超时秒数。
        retries: 网络异常重试次数。
        verify: 是否校验 HTTPS 证书。
    """

    def __init__(
        self,
        base_url: str = "",
        default_headers: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        verify: bool = True,
    ) -> None:
        """初始化客户端。

        Args:
            base_url: 基础地址，例如 ``https://httpbin.org``。
            default_headers: 默认请求头。
            timeout: 超时秒数。
            retries: 重试次数（仅针对网络异常与 ``retry_on_status`` 命中的状态码）。
            verify: 是否校验 TLS 证书。
        """
        self.base_url = (base_url or "").rstrip("/")
        self.default_headers: dict[str, str] = dict(default_headers or {})
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.verify = verify

    # ------------------------------------------------------------------ #
    # 对外方法
    # ------------------------------------------------------------------ #
    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
        data: Mapping[str, Any] | None = None,
        variables: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        retry_on_status: bool = False,
        follow_redirects: bool = True,
    ) -> ApiResponse:
        """发送一次 HTTP 请求（带重试与日志）。

        Args:
            method: HTTP 方法，大小写不敏感。
            url: 完整 URL 或相对路径。
            params: Query 参数。
            headers: 本次请求头，会覆盖同名默认头。
            json_body: JSON 请求体。
            data: 表单请求体。
            variables: 渲染 ``{{占位符}}`` 用的变量。
            timeout: 本次请求超时，默认取实例配置。
            retry_on_status: 是否对 5xx/429 也重试（默认关闭，避免掩盖真实缺陷）。
            follow_redirects: 是否自动跟随重定向。

        Returns:
            统一响应对象。

        Raises:
            httpx.HTTPError: 重试耗尽后仍然失败。
        """
        variables = variables or {}
        target_url = self._build_url(render_template(url, variables))
        merged_headers = {**self.default_headers, **(headers or {})}
        merged_headers = render_template(merged_headers, variables)  # type: ignore[assignment]
        rendered_params = render_template(dict(params or {}), variables)
        rendered_json = render_template(json_body, variables) if json_body is not None else None
        rendered_data = render_template(dict(data or {}), variables) if data else None

        request_snapshot: dict[str, Any] = {
            "method": method.upper(),
            "url": target_url,
            "params": rendered_params,
            "headers": _mask_headers(merged_headers),  # type: ignore[arg-type]
            "json": rendered_json,
            "data": rendered_data,
        }

        last_error: Exception | None = None
        attempts = self.retries + 1
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                with httpx.Client(
                    timeout=timeout or self.timeout,
                    verify=self.verify,
                    follow_redirects=follow_redirects,
                ) as client:
                    raw = client.request(
                        method=method.upper(),
                        url=target_url,
                        params=rendered_params or None,
                        headers=merged_headers,  # type: ignore[arg-type]
                        json=rendered_json,
                        data=rendered_data,  # type: ignore[arg-type]
                    )
                elapsed_ms = (time.perf_counter() - started) * 1000
                response = self._to_response(raw, elapsed_ms, request_snapshot)
                logger.info(
                    "[API] {} {} -> {} ({} ms)",
                    method.upper(),
                    target_url,
                    response.status_code,
                    round(elapsed_ms, 1),
                )
                if (
                    retry_on_status
                    and response.status_code in RETRY_STATUS_CODES
                    and attempt < attempts
                ):
                    logger.warning(
                        "命中可重试状态码 {}，第 {} 次重试", response.status_code, attempt
                    )
                    time.sleep(RETRY_BACKOFF * attempt)
                    continue
                return response
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = exc
                logger.warning(
                    "[API] {} {} 第 {}/{} 次请求失败: {}",
                    method.upper(),
                    target_url,
                    attempt,
                    attempts,
                    exc,
                )
                if attempt < attempts:
                    time.sleep(RETRY_BACKOFF * attempt)

        assert last_error is not None  # 循环必然赋值，仅为类型收窄
        raise last_error

    def get(self, url: str, **kwargs: Any) -> ApiResponse:
        """发送 GET 请求。"""
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> ApiResponse:
        """发送 POST 请求。"""
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> ApiResponse:
        """发送 PUT 请求。"""
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> ApiResponse:
        """发送 PATCH 请求。"""
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> ApiResponse:
        """发送 DELETE 请求。"""
        return self.request("DELETE", url, **kwargs)

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #
    def _build_url(self, url: str) -> str:
        """拼接完整 URL。

        Args:
            url: 相对或绝对地址。

        Returns:
            完整 URL。
        """
        if not url:
            return self.base_url
        if url.startswith(("http://", "https://")):
            return url
        if not self.base_url:
            return url
        return f"{self.base_url}/{url.lstrip('/')}"

    @staticmethod
    def _to_response(
        raw: httpx.Response, elapsed_ms: float, request_snapshot: dict[str, Any]
    ) -> ApiResponse:
        """把 httpx 响应转换成引擎层统一响应。

        Args:
            raw: httpx 原始响应。
            elapsed_ms: 耗时毫秒。
            request_snapshot: 请求快照。

        Returns:
            统一响应对象。
        """
        text = raw.text
        body: Any = text
        content_type = raw.headers.get("content-type", "")
        if "json" in content_type.lower() or text.strip().startswith(("{", "[")):
            try:
                body = json.loads(text) if text.strip() else None
            except json.JSONDecodeError:
                body = text
        return ApiResponse(
            status_code=raw.status_code,
            headers={k.lower(): v for k, v in raw.headers.items()},
            text=text,
            body=body,
            elapsed_ms=elapsed_ms,
            request=request_snapshot,
        )


def _mask_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """对敏感请求头做脱敏，避免 Token 泄漏到报告与日志。

    Args:
        headers: 原始请求头。

    Returns:
        脱敏后的请求头字典。
    """
    masked: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in _SENSITIVE_HEADERS:
            masked[key] = f"{value[:6]}***" if len(value) > 6 else "***"
        else:
            masked[key] = value
    return masked
