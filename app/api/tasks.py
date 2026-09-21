"""执行任务路由：任务列表、详情（含失败明细）、日志、重跑、删除。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import CurrentUser, DbSession, Pagination
from app.models import Task, TaskStatus
from app.schemas.common import MessageResponse, PageResult
from app.schemas.task import TaskDetailOut, TaskLogOut, TaskOut
from app.services.report_service import serialize_task
from app.services.test_runner import TestRunnerService
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/tasks", tags=["执行任务"])

# 日志单次返回的最大字符数，避免浏览器卡死
_LOG_PREVIEW_CHARS = 200_000


def _get_task_or_404(db: Session, task_id: int) -> Task:
    """按 ID 获取任务。

    Args:
        db: 数据库会话。
        task_id: 任务 ID。

    Returns:
        任务对象。

    Raises:
        HTTPException: 任务不存在。
    """
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 不存在")
    return task


def _screenshot_to_url(raw_path: str) -> str:
    """把截图磁盘路径转换成前端可访问的 URL。

    Args:
        raw_path: 引擎写入的截图路径。

    Returns:
        可直接用于 ``<img src>`` 的 URL；无法转换时原样返回。
    """
    try:
        relative = (
            Path(raw_path).resolve().relative_to((settings.reports_dir / "screenshots").resolve())
        )
    except (ValueError, OSError):
        return raw_path
    return f"/static/screenshots/{relative.as_posix()}"


def _normalize_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把结果里的截图路径换成 URL。

    Args:
        results: 引擎产出的原始结果列表。

    Returns:
        处理后的结果列表。
    """
    normalized: list[dict[str, Any]] = []
    for item in results:
        clone = dict(item)
        clone["screenshots"] = [_screenshot_to_url(path) for path in item.get("screenshots") or []]
        normalized.append(clone)
    return normalized


@router.get("", response_model=PageResult[TaskOut], summary="任务列表（分页 + 过滤）")
def list_tasks(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Pagination,
    project_id: int | None = Query(default=None, description="按项目过滤"),
    status_filter: str | None = Query(default=None, alias="status", description="按状态过滤"),
    trigger_type: str | None = Query(default=None, description="按触发来源过滤"),
    keyword: str | None = Query(default=None, description="按任务名/编号搜索"),
) -> PageResult[TaskOut]:
    """分页查询执行任务。

    Args:
        db: 数据库会话。
        current_user: 当前登录用户。
        pagination: 分页参数。
        project_id: 项目过滤。
        status_filter: 状态过滤。
        trigger_type: 触发来源过滤。
        keyword: 关键字。

    Returns:
        分页结果。
    """
    _ = current_user
    page, size = pagination
    query = db.query(Task)
    if project_id is not None:
        query = query.filter(Task.project_id == project_id)
    if status_filter:
        query = query.filter(Task.status == status_filter)
    if trigger_type:
        query = query.filter(Task.trigger_type == trigger_type)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        query = query.filter(Task.name.ilike(pattern) | Task.task_no.ilike(pattern))

    total = query.count()
    tasks = query.order_by(Task.id.desc()).offset((page - 1) * size).limit(size).all()
    return PageResult[TaskOut](
        total=total, page=page, size=size, items=[serialize_task(db, task) for task in tasks]
    )


@router.get("/{task_id}", response_model=TaskDetailOut, summary="任务详情（含每条用例结果）")
def get_task(task_id: int, db: DbSession, current_user: CurrentUser) -> TaskDetailOut:
    """获取任务详情。

    Args:
        task_id: 任务 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        任务详情，含失败用例的请求/响应/断言/截图明细。
    """
    _ = current_user
    task = _get_task_or_404(db, task_id)
    base = serialize_task(db, task)
    detail = task.result_detail or {}
    allure_url = ""
    if task.allure_report_path and Path(task.allure_report_path).is_dir():
        allure_url = f"/static/allure/{task.task_no}/index.html"
    return TaskDetailOut(
        **base.model_dump(),
        results=_normalize_results(task.results()),
        log_path=task.log_path,
        allure_results_dir=task.allure_results_dir,
        allure_report_url=allure_url,
        ai_analysis=task.ai_analysis,
        stdout_tail=str(detail.get("stdout_tail") or "")[-8000:],
    )


@router.get("/{task_id}/log", response_model=TaskLogOut, summary="查看执行日志")
def get_task_log(task_id: int, db: DbSession, current_user: CurrentUser) -> TaskLogOut:
    """读取任务的控制台日志。

    Args:
        task_id: 任务 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        日志内容（超长时截断）。
    """
    _ = current_user
    task = _get_task_or_404(db, task_id)
    if not task.log_path or not Path(task.log_path).is_file():
        return TaskLogOut(task_no=task.task_no, content="暂无日志文件（任务可能还未开始执行）")

    content = Path(task.log_path).read_text(encoding="utf-8", errors="replace")
    truncated = len(content) > _LOG_PREVIEW_CHARS
    return TaskLogOut(
        task_no=task.task_no,
        content=content[-_LOG_PREVIEW_CHARS:] if truncated else content,
        truncated=truncated,
    )


@router.post("/{task_id}/retry", response_model=TaskOut, summary="用相同用例重跑一次")
def retry_task(task_id: int, db: DbSession, current_user: CurrentUser) -> TaskOut:
    """用相同配置重新执行一次任务。

    Args:
        task_id: 原任务 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        新建的任务。
    """
    _ = current_user
    origin = _get_task_or_404(db, task_id)
    if not origin.case_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="原任务没有记录用例，无法重跑"
        )

    service = TestRunnerService(db)
    task = service.create_task(
        case_ids=list(origin.case_ids),
        project_id=origin.project_id,
        environment_id=origin.environment_id,
        retry_times=origin.retry_times,
        trigger_type=origin.trigger_type,
        suite_id=origin.suite_id,
        name=f"重跑 · {origin.name}",
    )
    output = serialize_task(db, task)
    service.submit(task.id)
    return output


@router.delete("/{task_id}", response_model=MessageResponse, summary="删除任务记录")
def delete_task(task_id: int, db: DbSession, current_user: CurrentUser) -> MessageResponse:
    """删除任务记录。

    Args:
        task_id: 任务 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        操作结果。

    Raises:
        HTTPException: 任务正在执行中。
    """
    _ = current_user
    task = _get_task_or_404(db, task_id)
    if task.status == TaskStatus.RUNNING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="任务正在执行中，无法删除"
        )
    db.delete(task)
    db.commit()
    return MessageResponse(message="任务记录已删除")
