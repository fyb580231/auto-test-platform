"""依赖注入：数据库会话、当前用户、权限校验、项目归属校验。

FastAPI 的依赖注入是「路由层保持轻薄」的关键：路由函数只需要声明依赖，
参数校验、鉴权、资源存在性检查全部由依赖完成，业务逻辑则下沉到 services/。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, User
from app.utils.jwt import TokenError, decode_access_token
from app.utils.logger import get_logger

logger = get_logger(__name__)

# auto_error=False：自行抛 401，保证错误响应体格式统一
bearer_scheme = HTTPBearer(auto_error=False, description="在请求头中携带 Bearer Token")

DbSession = Annotated[Session, Depends(get_db)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def get_current_user(db: DbSession, credentials: Credentials) -> User:
    """解析当前登录用户。

    Args:
        db: 数据库会话。
        credentials: HTTP Bearer 凭证。

    Returns:
        当前用户 ORM 对象。

    Raises:
        HTTPException: 未携带令牌、令牌无效或用户不存在/被禁用。
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或缺少访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    username = str(payload.get("sub") or "")
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_admin(current_user: CurrentUser) -> User:
    """要求当前用户是管理员。

    Args:
        current_user: 当前登录用户。

    Returns:
        当前用户 ORM 对象。

    Raises:
        HTTPException: 权限不足。
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user


AdminUser = Annotated[User, Depends(get_current_admin)]


def get_project_or_404(db: Session, project_id: int) -> Project:
    """按 ID 获取项目，不存在则抛 404。

    Args:
        db: 数据库会话。
        project_id: 项目 ID。

    Returns:
        项目 ORM 对象。

    Raises:
        HTTPException: 项目不存在。
    """
    project = db.query(Project).filter(Project.id == project_id).one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"项目 {project_id} 不存在"
        )
    return project


def pagination(
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=20, ge=1, le=200, description="每页条数"),
) -> tuple[int, int]:
    """通用分页参数依赖。

    Args:
        page: 页码。
        size: 每页条数。

    Returns:
        ``(page, size)`` 二元组。
    """
    return page, size


Pagination = Annotated[tuple[int, int], Depends(pagination)]
