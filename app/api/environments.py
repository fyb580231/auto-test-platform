"""环境配置路由：每个项目下的多环境管理。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.deps import CurrentUser, DbSession, get_project_or_404
from app.models import Environment
from app.schemas.common import MessageResponse
from app.schemas.environment import (
    EnvironmentCreateRequest,
    EnvironmentOut,
    EnvironmentUpdateRequest,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["环境配置"])


def _get_environment_or_404(db: DbSession, environment_id: int) -> Environment:
    """按 ID 获取环境。

    Args:
        db: 数据库会话。
        environment_id: 环境 ID。

    Returns:
        环境对象。

    Raises:
        HTTPException: 环境不存在。
    """
    environment = db.get(Environment, environment_id)
    if environment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"环境 {environment_id} 不存在"
        )
    return environment


def _clear_other_defaults(db: DbSession, project_id: int, keep_id: int | None) -> None:
    """保证同一项目下只有一个默认环境。

    Args:
        db: 数据库会话。
        project_id: 项目 ID。
        keep_id: 保留为默认的环境 ID。
    """
    others = (
        db.query(Environment)
        .filter(Environment.project_id == project_id, Environment.is_default.is_(True))
        .all()
    )
    for item in others:
        if item.id != keep_id:
            item.is_default = False


@router.get(
    "/projects/{project_id}/environments",
    response_model=list[EnvironmentOut],
    summary="环境列表",
)
def list_environments(
    project_id: int, db: DbSession, current_user: CurrentUser
) -> list[EnvironmentOut]:
    """获取项目下的环境列表。

    Args:
        project_id: 项目 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        环境列表（默认环境排在最前）。
    """
    _ = current_user
    get_project_or_404(db, project_id)
    environments = (
        db.query(Environment)
        .filter(Environment.project_id == project_id)
        .order_by(Environment.is_default.desc(), Environment.id.asc())
        .all()
    )
    return [EnvironmentOut.model_validate(item) for item in environments]


@router.post(
    "/projects/{project_id}/environments",
    response_model=EnvironmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建环境",
)
def create_environment(
    project_id: int, payload: EnvironmentCreateRequest, db: DbSession, current_user: CurrentUser
) -> EnvironmentOut:
    """创建环境。

    Args:
        project_id: 项目 ID。
        payload: 创建请求。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        新建环境。

    Raises:
        HTTPException: 同项目内环境名重复。
    """
    _ = current_user
    get_project_or_404(db, project_id)
    exists = (
        db.query(Environment)
        .filter(Environment.project_id == project_id, Environment.name == payload.name)
        .one_or_none()
    )
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="同项目下环境名不能重复")

    environment = Environment(
        project_id=project_id,
        name=payload.name,
        base_url=payload.base_url,
        headers=payload.headers,
        variables=payload.variables,
        verify=payload.verify,
        timeout=payload.timeout,
        is_default=payload.is_default,
        description=payload.description,
    )
    db.add(environment)
    db.commit()
    db.refresh(environment)
    if environment.is_default:
        _clear_other_defaults(db, project_id, environment.id)
        db.commit()
    logger.info("已创建环境: {} (project={})", environment.name, project_id)
    return EnvironmentOut.model_validate(environment)


@router.put("/environments/{environment_id}", response_model=EnvironmentOut, summary="更新环境")
def update_environment(
    environment_id: int, payload: EnvironmentUpdateRequest, db: DbSession, current_user: CurrentUser
) -> EnvironmentOut:
    """更新环境配置。

    Args:
        environment_id: 环境 ID。
        payload: 更新请求。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        更新后的环境。
    """
    _ = current_user
    environment = _get_environment_or_404(db, environment_id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(environment, field, value)
    db.commit()
    db.refresh(environment)
    if environment.is_default:
        _clear_other_defaults(db, environment.project_id, environment.id)
        db.commit()
    return EnvironmentOut.model_validate(environment)


@router.delete("/environments/{environment_id}", response_model=MessageResponse, summary="删除环境")
def delete_environment(
    environment_id: int, db: DbSession, current_user: CurrentUser
) -> MessageResponse:
    """删除环境。

    Args:
        environment_id: 环境 ID。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        操作结果。
    """
    _ = current_user
    environment = _get_environment_or_404(db, environment_id)
    name = environment.name
    db.delete(environment)
    db.commit()
    logger.info("已删除环境: {} (id={})", name, environment_id)
    return MessageResponse(message=f"环境「{name}」已删除")
