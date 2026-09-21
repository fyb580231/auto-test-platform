"""FastAPI 应用入口。

职责边界：
1. 装配中间件（CORS、请求日志）与全局异常处理器；
2. 生命周期管理（建表、初始化演示数据、启停定时调度器）；
3. 挂载静态资源（失败截图、Allure HTML 报告）；
4. 注册 ``/api`` 路由。

业务逻辑一律不写在这里——``main.py`` 保持「只做装配」。
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import api_router
from app.config import settings
from app.database import init_db
from app.services.scheduler import scheduler_service
from app.services.seed import bootstrap
from app.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动时初始化，关闭时清理。

    Args:
        _app: FastAPI 实例（未使用）。

    Yields:
        None
    """
    setup_logging()
    logger.info("{} v{} 启动中...", settings.app_name, settings.app_version)
    init_db()
    try:
        bootstrap()
    except Exception as exc:
        logger.exception("演示数据初始化失败（不影响服务启动）: {}", exc)
    try:
        scheduler_service.start()
    except Exception as exc:
        logger.exception("定时调度器启动失败（不影响手工执行）: {}", exc)

    logger.info("服务已就绪: http://{}:{}  |  接口文档: /docs", settings.host, settings.port)
    yield

    scheduler_service.shutdown(wait=False)
    logger.info("{} 已关闭", settings.app_name)


app = FastAPI(
    title="auto-test-platform",
    description=(
        "接口测试 + UI 测试 + AI 辅助一体化的 Web 测试管理平台。\n\n"
        "- 引擎层（engine/）可脱离 Web 独立使用：`python run_engine.py --help`\n"
        "- 服务层（app/）把引擎能力封装为 HTTP 接口\n"
        "- 前端层（web/）提供可视化用例管理与报告查看"
    ),
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def access_log_middleware(request: Request, call_next: Any) -> Any:
    """记录每个请求的耗时与状态码。

    Args:
        request: 请求对象。
        call_next: 下游处理链。

    Returns:
        响应对象。
    """
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    # 静态资源与文档请求不记录，避免日志噪音
    if not request.url.path.startswith(("/static", "/docs", "/redoc", "/openapi.json")):
        logger.info(
            "{} {} -> {} ({:.1f}ms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """统一 HTTP 异常响应格式。

    Args:
        _request: 请求对象。
        exc: 异常对象。

    Returns:
        统一格式的 JSON 响应。
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "code": exc.status_code,
            "message": str(exc.detail),
            "data": None,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """统一参数校验失败响应，把 Pydantic 报错整理成可读文案。

    Args:
        _request: 请求对象。
        exc: 校验异常。

    Returns:
        统一格式的 JSON 响应。
    """
    errors = []
    for item in exc.errors():
        location = ".".join(str(part) for part in item.get("loc", ()))
        errors.append(f"{location}: {item.get('msg')}")
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "code": 422,
            "message": "请求参数校验失败",
            "data": {"errors": errors},
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理：记录完整堆栈，对外只返回必要信息。

    Args:
        _request: 请求对象。
        exc: 异常对象。

    Returns:
        统一格式的 JSON 响应。
    """
    logger.exception("未处理异常: {}", exc)
    detail = str(exc) if settings.debug else "服务器内部错误，请查看服务端日志"
    return JSONResponse(
        status_code=500,
        content={"success": False, "code": 500, "message": detail, "data": None},
    )


# 静态资源：失败截图与 Allure HTML 报告（仅暴露必要的两个子目录）
settings.reports_dir.mkdir(parents=True, exist_ok=True)
(settings.reports_dir / "screenshots").mkdir(parents=True, exist_ok=True)
(settings.reports_dir / "allure-report").mkdir(parents=True, exist_ok=True)
app.mount(
    "/static/screenshots",
    StaticFiles(directory=str(settings.reports_dir / "screenshots")),
    name="screenshots",
)
app.mount(
    "/static/allure",
    StaticFiles(directory=str(settings.reports_dir / "allure-report"), html=True),
    name="allure",
)

app.include_router(api_router, prefix="/api")


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    """根路径：给出常用入口，避免访问根路径时看到 404 而困惑。

    Returns:
        入口地址字典。
    """
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/api/health",
    }
