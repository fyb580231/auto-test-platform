"""用例路由：接口/UI 用例的 CRUD、导入、单条执行与批量执行。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app.deps import CurrentUser, DbSession, Pagination, get_project_or_404
from app.models import TestCase
from app.schemas.common import MessageResponse, PageResult
from app.schemas.task import TaskOut
from app.schemas.testcase import (
    ImportCasesRequest,
    RunCasesRequest,
    TestCaseCreateRequest,
    TestCaseOut,
    TestCaseUpdateRequest,
)
from app.services.report_service import serialize_task
from app.services.test_runner import TestRunnerService
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["测试用例"])

# 可被直接写入数据库的字段（白名单，避免请求体里塞入未知字段）
_WRITABLE_FIELDS = (
    "name",
    "case_type",
    "description",
    "tags",
    "method",
    "url",
    "headers",
    "params",
    "body",
    "form",
    "setup_case_id",
    "extract",
    "steps",
    "assertions",
    "enabled",
)


def serialize_case(db: Session, case: TestCase) -> TestCaseOut:
    """把用例 ORM 对象转换成响应模型。

    Args:
        db: 数据库会话（用于补齐前置用例名称）。
        case: 用例对象。

    Returns:
        用例响应模型。
    """
    setup_case_name = None
    if case.setup_case_id:
        setup_case = db.get(TestCase, case.setup_case_id)
        setup_case_name = setup_case.name if setup_case else None
    return TestCaseOut(
        id=case.id,
        project_id=case.project_id,
        name=case.name,
        case_type=case.case_type,  # type: ignore[arg-type]
        description=case.description,
        tags=case.tags or [],
        method=case.method,
        url=case.url,
        headers=case.headers or {},
        params=case.params or {},
        body=case.body,
        form=case.form or {},
        setup_case_id=case.setup_case_id,
        setup_case_name=setup_case_name,
        extract=case.extract or [],
        steps=case.steps or [],
        assertions=case.assertions or [],
        enabled=case.enabled,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _get_case_or_404(db: Session, case_id: int) -> TestCase:
    """按 ID 获取用例。

    Args:
        db: 数据库会话。
        case_id: 用例 ID。

    Returns:
        用例对象。

    Raises:
        HTTPException: 用例不存在。
    """
    case = db.get(TestCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"用例 {case_id} 不存在")
    return case


def _apply_payload(case: TestCase, payload: dict[str, Any]) -> None:
    """把请求体字段写入 ORM 对象（仅白名单字段）。

    Args:
        case: 用例对象。
        payload: 已排除未设置字段的字典。
    """
    for field in _WRITABLE_FIELDS:
        if field in payload:
            setattr(case, field, payload[field])


# ---------------------------------------------------------------------------- #
# 用例列表 / 创建
# ---------------------------------------------------------------------------- #
@router.get(
    "/projects/{project_id}/testcases",
    response_model=PageResult[TestCaseOut],
    summary="用例列表（分页 + 过滤）",
)
def list_cases(
    project_id: int,
    db: DbSession,
    current_user: CurrentUser,
    pagination: Pagination,
    case_type: str | None = Query(default=None, description="api / ui"),
    tag: str | None = Query(default=None, description="按标签过滤"),
    keyword: str | None = Query(default=None, description="按名称/URL/描述模糊搜索"),
    enabled: bool | None = Query(default=None, description="按启用状态过滤"),
) -> PageResult[TestCaseOut]:
    """分页查询项目下的用例。

    Args:
        project_id: 项目 ID。
        db: 数据库会话。
        current_user: 当前登录用户。
        pagination: 分页参数。
        case_type: 用例类型过滤。
        tag: 标签过滤。
        keyword: 关键字。
        enabled: 启用状态过滤。

    Returns:
        分页结果。
    """
    _ = current_user
    get_project_or_404(db, project_id)
    page, size = pagination

    query = db.query(TestCase).filter(TestCase.project_id == project_id)
    if case_type:
        query = query.filter(TestCase.case_type == case_type)
    if enabled is not None:
        query = query.filter(TestCase.enabled.is_(enabled))
    if tag:
        # JSON 数组字段的跨数据库兼容过滤：转成字符串后做 LIKE 匹配
        query = query.filter(cast(TestCase.tags, String).like(f'%"{tag.strip()}"%'))
    if keyword:
        pattern = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                TestCase.name.ilike(pattern),
                TestCase.url.ilike(pattern),
                TestCase.description.ilike(pattern),
            )
        )

    total = query.count()
    cases = query.order_by(TestCase.id.desc()).offset((page - 1) * size).limit(size).all()
    return PageResult[TestCaseOut](
        total=total, page=page, size=size, items=[serialize_case(db, case) for case in cases]
    )


@router.post(
    "/projects/{project_id}/testcases",
    response_model=TestCaseOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建用例",
)
def create_case(
    project_id: int, payload: TestCaseCreateRequest, db: DbSession, current_user: CurrentUser
) -> TestCaseOut:
    """创建一条用例。

    Args:
        project_id: 项目 ID。
        payload: 创建请求。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        新建用例。
    """
    get_project_or_404(db, project_id)
    case = TestCase(project_id=project_id, created_by=current_user.id)
    _apply_payload(case, payload.model_dump())
    db.add(case)
    db.commit()
    db.refresh(case)
    logger.info("已创建用例: {} (project={})", case.name, project_id)
    return serialize_case(db, case)


@router.post(
    "/projects/{project_id}/testcases/import",
    response_model=MessageResponse,
    summary="批量导入用例（AI 生成结果 / YAML 导入）",
)
def import_cases(
    project_id: int, payload: ImportCasesRequest, db: DbSession, current_user: CurrentUser
) -> MessageResponse:
    """批量导入用例。

    Args:
        project_id: 项目 ID。
        payload: 导入请求。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        导入结果统计。
    """
    get_project_or_404(db, project_id)
    created, updated, skipped = 0, 0, 0
    for item in payload.cases:
        existing = (
            db.query(TestCase)
            .filter(TestCase.project_id == project_id, TestCase.name == item.name)
            .one_or_none()
        )
        if existing is not None and not payload.overwrite:
            skipped += 1
            continue
        if existing is not None:
            _apply_payload(existing, item.model_dump())
            updated += 1
            continue
        case = TestCase(project_id=project_id, created_by=current_user.id)
        _apply_payload(case, item.model_dump())
        db.add(case)
        created += 1
    db.commit()
    logger.info("批量导入完成: 新增 {} / 覆盖 {} / 跳过 {}", created, updated, skipped)
    return MessageResponse(
        message=f"导入完成：新增 {created} 条，覆盖 {updated} 条，跳过同名 {skipped} 条",
        data={"created": created, "updated": updated, "skipped": skipped},
    )


# ---------------------------------------------------------------------------- #
# 单条用例操作
# ---------------------------------------------------------------------------- #
@router.get("/testcases/{case_id}", response_model=TestCaseOut, summary="用例详情")
def get_case(case_id: int, db: DbSession, current_user: CurrentUser) -> TestCaseOut:
    """获取用例详情。

    Args:
        case_id: 用例 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        用例详情。
    """
    _ = current_user
    return serialize_case(db, _get_case_or_404(db, case_id))


@router.put("/testcases/{case_id}", response_model=TestCaseOut, summary="更新用例")
def update_case(
    case_id: int, payload: TestCaseUpdateRequest, db: DbSession, current_user: CurrentUser
) -> TestCaseOut:
    """更新用例。

    Args:
        case_id: 用例 ID。
        payload: 更新请求。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        更新后的用例。

    Raises:
        HTTPException: 前置用例指向自身或不存在。
    """
    _ = current_user
    case = _get_case_or_404(db, case_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("setup_case_id"):
        if int(data["setup_case_id"]) == case_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="前置用例不能是自己"
            )
        if db.get(TestCase, int(data["setup_case_id"])) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="前置用例不存在")
        case.extract = data.get("extract", case.extract)
    _apply_payload(case, data)
    db.commit()
    db.refresh(case)
    return serialize_case(db, case)


@router.delete("/testcases/{case_id}", response_model=MessageResponse, summary="删除用例")
def delete_case(case_id: int, db: DbSession, current_user: CurrentUser) -> MessageResponse:
    """删除用例。

    Args:
        case_id: 用例 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        操作结果。
    """
    _ = current_user
    case = _get_case_or_404(db, case_id)
    name = case.name
    db.delete(case)
    db.commit()
    logger.info("已删除用例: {} (id={})", name, case_id)
    return MessageResponse(message=f"用例「{name}」已删除")


# ---------------------------------------------------------------------------- #
# 执行
# ---------------------------------------------------------------------------- #
@router.post("/testcases/batch-run", response_model=TaskOut, summary="批量执行用例（异步）")
def batch_run_cases(payload: RunCasesRequest, db: DbSession, current_user: CurrentUser) -> TaskOut:
    """批量执行用例，立即返回任务，由后台线程池异步执行。

    注意：本路由必须声明在 ``/testcases/{case_id}`` **之前**，
    否则 ``batch-run`` 会被当成路径参数解析成 int 而报 422。

    Args:
        payload: 执行请求。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        已创建的任务。

    Raises:
        HTTPException: 用例不存在。
    """
    _ = current_user
    cases = db.query(TestCase).filter(TestCase.id.in_(payload.case_ids)).all()
    if not cases:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有找到可执行的用例")

    service = TestRunnerService(db)
    task = service.create_task(
        case_ids=[case.id for case in cases],
        project_id=cases[0].project_id,
        environment_id=payload.environment_id,
        retry_times=payload.retry_times,
        name=payload.name,
    )
    output = serialize_task(db, task)
    task_id = task.id
    service.submit(task_id)
    return output


@router.post("/testcases/{case_id}/run", response_model=TaskOut, summary="执行单条用例（异步）")
def run_single_case(
    case_id: int, db: DbSession, current_user: CurrentUser, environment_id: int | None = None
) -> TaskOut:
    """执行单条用例。

    Args:
        case_id: 用例 ID。
        db: 数据库会话。
        current_user: 当前登录用户。
        environment_id: 指定执行环境。

    Returns:
        已创建的任务。
    """
    _ = current_user
    case = _get_case_or_404(db, case_id)
    service = TestRunnerService(db)
    task = service.create_task(
        case_ids=[case.id],
        project_id=case.project_id,
        environment_id=environment_id,
        name=f"单条执行 · {case.name}",
    )
    output = serialize_task(db, task)
    service.submit(task.id)
    return output
