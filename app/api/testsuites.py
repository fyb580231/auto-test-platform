"""用例集路由：用例集 CRUD、定时配置同步、整套执行。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import CurrentUser, DbSession, get_project_or_404
from app.models import Environment, TestCase, TestSuite
from app.schemas.common import MessageResponse
from app.schemas.task import TaskOut
from app.schemas.testsuite import (
    RunSuiteRequest,
    TestSuiteCreateRequest,
    TestSuiteOut,
    TestSuiteUpdateRequest,
)
from app.services.report_service import serialize_task
from app.services.scheduler import scheduler_service
from app.services.test_runner import TestRunnerService
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["用例集"])


def serialize_suite(suite: TestSuite) -> TestSuiteOut:
    """把用例集 ORM 对象转换成响应模型。

    Args:
        suite: 用例集对象。

    Returns:
        用例集响应模型。
    """
    return TestSuiteOut(
        id=suite.id,
        project_id=suite.project_id,
        name=suite.name,
        description=suite.description,
        case_ids=suite.case_ids or [],
        case_count=len(suite.case_ids or []),
        environment_id=suite.environment_id,
        cron_expression=suite.cron_expression,
        retry_times=suite.retry_times,
        enabled=suite.enabled,
        last_run_at=suite.last_run_at,
        created_at=suite.created_at,
        updated_at=suite.updated_at,
    )


def _get_suite_or_404(db: Session, suite_id: int) -> TestSuite:
    """按 ID 获取用例集。

    Args:
        db: 数据库会话。
        suite_id: 用例集 ID。

    Returns:
        用例集对象。

    Raises:
        HTTPException: 用例集不存在。
    """
    suite = db.get(TestSuite, suite_id)
    if suite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"用例集 {suite_id} 不存在"
        )
    return suite


def _validate_relations(
    db: Session, project_id: int, case_ids: list[int], environment_id: int | None
) -> None:
    """校验用例集引用的用例与环境是否合法。

    Args:
        db: 数据库会话。
        project_id: 项目 ID。
        case_ids: 用例 ID 列表。
        environment_id: 环境 ID。

    Raises:
        HTTPException: 引用了不属于本项目的用例或环境。
    """
    if case_ids:
        found = db.query(TestCase.id).filter(TestCase.id.in_(case_ids)).all()
        found_ids = {row[0] for row in found}
        missing = [cid for cid in case_ids if cid not in found_ids]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"以下用例不存在: {missing}"
            )
        wrong_project = (
            db.query(TestCase)
            .filter(TestCase.id.in_(case_ids), TestCase.project_id != project_id)
            .count()
        )
        if wrong_project:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="用例集不能包含其他项目的用例"
            )
    if environment_id is not None:
        environment = db.get(Environment, environment_id)
        if environment is None or environment.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="环境不存在或不属于该项目"
            )


@router.get(
    "/projects/{project_id}/testsuites", response_model=list[TestSuiteOut], summary="用例集列表"
)
def list_suites(project_id: int, db: DbSession, current_user: CurrentUser) -> list[TestSuiteOut]:
    """获取项目下的用例集列表。

    Args:
        project_id: 项目 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        用例集列表。
    """
    _ = current_user
    get_project_or_404(db, project_id)
    suites = (
        db.query(TestSuite)
        .filter(TestSuite.project_id == project_id)
        .order_by(TestSuite.id.desc())
        .all()
    )
    return [serialize_suite(suite) for suite in suites]


@router.post(
    "/projects/{project_id}/testsuites",
    response_model=TestSuiteOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建用例集",
)
def create_suite(
    project_id: int, payload: TestSuiteCreateRequest, db: DbSession, current_user: CurrentUser
) -> TestSuiteOut:
    """创建用例集。

    Args:
        project_id: 项目 ID。
        payload: 创建请求。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        新建用例集。
    """
    _ = current_user
    get_project_or_404(db, project_id)
    _validate_relations(db, project_id, payload.case_ids, payload.environment_id)

    suite = TestSuite(
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        case_ids=payload.case_ids,
        environment_id=payload.environment_id,
        cron_expression=payload.cron_expression,
        retry_times=payload.retry_times,
        enabled=payload.enabled,
    )
    db.add(suite)
    db.commit()
    db.refresh(suite)
    scheduler_service.sync_suite(suite.id)
    logger.info("已创建用例集: {} (project={})", suite.name, project_id)
    return serialize_suite(suite)


@router.get("/testsuites/{suite_id}", response_model=TestSuiteOut, summary="用例集详情")
def get_suite(suite_id: int, db: DbSession, current_user: CurrentUser) -> TestSuiteOut:
    """获取用例集详情。

    Args:
        suite_id: 用例集 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        用例集详情。
    """
    _ = current_user
    return serialize_suite(_get_suite_or_404(db, suite_id))


@router.put("/testsuites/{suite_id}", response_model=TestSuiteOut, summary="更新用例集")
def update_suite(
    suite_id: int, payload: TestSuiteUpdateRequest, db: DbSession, current_user: CurrentUser
) -> TestSuiteOut:
    """更新用例集（含定时配置同步）。

    Args:
        suite_id: 用例集 ID。
        payload: 更新请求。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        更新后的用例集。
    """
    _ = current_user
    suite = _get_suite_or_404(db, suite_id)
    data = payload.model_dump(exclude_unset=True)
    if "case_ids" in data or "environment_id" in data:
        _validate_relations(
            db,
            suite.project_id,
            data.get("case_ids", suite.case_ids) or [],
            data.get("environment_id", suite.environment_id),
        )
    for field, value in data.items():
        setattr(suite, field, value)
    db.commit()
    db.refresh(suite)
    scheduler_service.sync_suite(suite.id)
    return serialize_suite(suite)


@router.delete("/testsuites/{suite_id}", response_model=MessageResponse, summary="删除用例集")
def delete_suite(suite_id: int, db: DbSession, current_user: CurrentUser) -> MessageResponse:
    """删除用例集。

    Args:
        suite_id: 用例集 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        操作结果。
    """
    _ = current_user
    suite = _get_suite_or_404(db, suite_id)
    name = suite.name
    db.delete(suite)
    db.commit()
    scheduler_service.sync_suite(suite_id)
    logger.info("已删除用例集: {} (id={})", name, suite_id)
    return MessageResponse(message=f"用例集「{name}」已删除")


@router.post("/testsuites/{suite_id}/run", response_model=TaskOut, summary="执行整个用例集（异步）")
def run_suite(
    suite_id: int, payload: RunSuiteRequest, db: DbSession, current_user: CurrentUser
) -> TaskOut:
    """执行用例集。

    Args:
        suite_id: 用例集 ID。
        payload: 执行请求。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        已创建的任务。

    Raises:
        HTTPException: 用例集为空。
    """
    _ = current_user
    suite = _get_suite_or_404(db, suite_id)
    if not suite.case_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用例集内没有任何用例")

    service = TestRunnerService(db)
    task = service.create_task(
        case_ids=list(suite.case_ids),
        project_id=suite.project_id,
        environment_id=payload.environment_id or suite.environment_id,
        retry_times=payload.retry_times if payload.retry_times is not None else suite.retry_times,
        suite_id=suite.id,
        name=f"用例集执行 · {suite.name}",
    )
    output = serialize_task(db, task)
    service.submit(task.id)
    return output


@router.get("/scheduler/jobs", summary="当前已注册的定时任务")
def list_scheduler_jobs(current_user: CurrentUser) -> dict[str, object]:
    """查看调度器中已注册的定时任务（排查「定时没跑」的第一个入口）。

    Args:
        current_user: 当前登录用户。

    Returns:
        调度器状态与任务列表。
    """
    _ = current_user
    return {
        "running": scheduler_service.running,
        "jobs": scheduler_service.list_jobs(),
    }
