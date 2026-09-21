"""API 路由聚合：把各业务模块的路由挂到统一的 ``/api`` 前缀下。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import ai, auth, dashboard, environments, projects, tasks, testcases, testsuites

api_router = APIRouter()
api_router.include_router(dashboard.router)
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(environments.router)
api_router.include_router(testcases.router)
api_router.include_router(testsuites.router)
api_router.include_router(tasks.router)
api_router.include_router(ai.router)

__all__ = ["api_router"]
