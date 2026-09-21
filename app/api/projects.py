"""项目路由：项目 CRUD。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.deps import CurrentUser, DbSession, get_project_or_404
from app.models import Environment, Project, TestCase, TestSuite
from app.schemas.common import MessageResponse
from app.schemas.project import ProjectCreateRequest, ProjectOut, ProjectUpdateRequest
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/projects", tags=["项目"])


def _to_out(db: DbSession, project: Project) -> ProjectOut:
    """把项目 ORM 对象转换成响应模型（含派生统计）。

    Args:
        db: 数据库会话。
        project: 项目对象。

    Returns:
        项目响应模型。
    """
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        owner_id=project.owner_id,
        case_count=db.query(TestCase).filter(TestCase.project_id == project.id).count(),
        suite_count=db.query(TestSuite).filter(TestSuite.project_id == project.id).count(),
        environment_count=db.query(Environment)
        .filter(Environment.project_id == project.id)
        .count(),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("", response_model=list[ProjectOut], summary="项目列表")
def list_projects(
    db: DbSession, current_user: CurrentUser, keyword: str | None = None
) -> list[ProjectOut]:
    """获取项目列表。

    Args:
        db: 数据库会话。
        current_user: 当前登录用户。
        keyword: 项目名模糊搜索关键字。

    Returns:
        项目列表（按创建时间倒序）。
    """
    _ = current_user
    query = db.query(Project)
    if keyword:
        query = query.filter(Project.name.ilike(f"%{keyword.strip()}%"))
    projects = query.order_by(Project.created_at.desc()).all()
    return [_to_out(db, project) for project in projects]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED, summary="创建项目")
def create_project(
    payload: ProjectCreateRequest, db: DbSession, current_user: CurrentUser
) -> ProjectOut:
    """创建项目，并自动初始化一个默认环境。

    Args:
        payload: 创建请求。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        新建项目。

    Raises:
        HTTPException: 项目名已存在。
    """
    exists = db.query(Project).filter(Project.name == payload.name).one_or_none()
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="项目名已存在")

    project = Project(name=payload.name, description=payload.description, owner_id=current_user.id)
    db.add(project)
    db.commit()
    db.refresh(project)

    # 新项目自动带一个 dev 环境，避免用户建完项目后「无环境可用」而卡住
    db.add(
        Environment(
            project_id=project.id,
            name="dev",
            base_url="https://httpbin.org",
            headers={"Content-Type": "application/json"},
            variables={},
            is_default=True,
            timeout=15,
            description="项目创建时自动生成的默认环境，可按需修改 base_url",
        )
    )
    db.commit()
    logger.info("已创建项目: {} (id={})", project.name, project.id)
    return _to_out(db, project)


@router.get("/{project_id}", response_model=ProjectOut, summary="项目详情")
def get_project(project_id: int, db: DbSession, current_user: CurrentUser) -> ProjectOut:
    """获取项目详情。

    Args:
        project_id: 项目 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        项目详情。
    """
    _ = current_user
    return _to_out(db, get_project_or_404(db, project_id))


@router.put("/{project_id}", response_model=ProjectOut, summary="更新项目")
def update_project(
    project_id: int, payload: ProjectUpdateRequest, db: DbSession, current_user: CurrentUser
) -> ProjectOut:
    """更新项目信息。

    Args:
        project_id: 项目 ID。
        payload: 更新请求。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        更新后的项目。

    Raises:
        HTTPException: 新项目名与其他项目冲突。
    """
    _ = current_user
    project = get_project_or_404(db, project_id)
    if payload.name and payload.name != project.name:
        conflict = db.query(Project).filter(Project.name == payload.name).one_or_none()
        if conflict is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="项目名已存在")
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    db.commit()
    db.refresh(project)
    return _to_out(db, project)


@router.delete("/{project_id}", response_model=MessageResponse, summary="删除项目")
def delete_project(project_id: int, db: DbSession, current_user: CurrentUser) -> MessageResponse:
    """删除项目及其下全部用例、用例集、环境。

    Args:
        project_id: 项目 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        操作结果。
    """
    _ = current_user
    project = get_project_or_404(db, project_id)
    name = project.name
    db.delete(project)
    db.commit()
    logger.info("已删除项目: {} (id={})", name, project_id)
    return MessageResponse(message=f"项目「{name}」及其下所有数据已删除")


@router.get("/{project_id}/tags", response_model=list[str], summary="项目内已使用的标签")
def list_tags(project_id: int, db: DbSession, current_user: CurrentUser) -> list[str]:
    """获取项目内出现过的全部用例标签（供前端筛选下拉框使用）。

    Args:
        project_id: 项目 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        去重后的标签列表。
    """
    _ = current_user
    get_project_or_404(db, project_id)
    rows = db.query(TestCase.tags).filter(TestCase.project_id == project_id).all()
    tags: set[str] = set()
    for (row,) in rows:
        for tag in row or []:
            tags.add(str(tag))
    return sorted(tags)


def _count_cases(db: Session, project_id: int) -> int:
    """统计项目下的用例数（供外部复用）。

    Args:
        db: 数据库会话。
        project_id: 项目 ID。

    Returns:
        用例数量。
    """
    return int(
        db.query(func.count(TestCase.id)).filter(TestCase.project_id == project_id).scalar() or 0
    )
