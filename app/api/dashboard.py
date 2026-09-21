"""Dashboard 路由：首页统计聚合。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.schemas.common import MessageResponse
from app.schemas.dashboard import DashboardStatsOut
from app.services.report_service import ReportService
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["Dashboard"])


@router.get(
    "/dashboard/stats", response_model=DashboardStatsOut, summary="首页统计（趋势/分布/概览）"
)
def dashboard_stats(
    db: DbSession,
    current_user: CurrentUser,
    days: int = Query(default=7, ge=1, le=90, description="统计窗口天数"),
) -> DashboardStatsOut:
    """获取首页所需的全部统计数据。

    Args:
        db: 数据库会话。
        current_user: 当前登录用户。
        days: 统计窗口天数。

    Returns:
        统计结果，包含概览卡片、通过率趋势、项目分布、失败用例 TOP N。
    """
    _ = current_user
    return ReportService(db).dashboard(days=days)


@router.get("/health", response_model=MessageResponse, summary="健康检查")
def health() -> MessageResponse:
    """健康检查接口（供 Docker / CI 探活使用，无需登录）。

    Returns:
        服务状态。
    """
    return MessageResponse(
        message="ok",
        data={
            "app": settings.app_name,
            "version": settings.app_version,
            "database": settings.db_type,
            "ai_available": settings.ai_available,
        },
    )
