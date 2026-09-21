"""认证路由：注册 / 登录 / 当前用户 / 修改密码。

路由层只做「参数校验 + 业务调用 + 组装响应」，密码校验、令牌签发在 utils/jwt.py，
用户查询通过 SQLAlchemy 完成。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.models import User, UserRole
from app.schemas.common import MessageResponse
from app.schemas.user import (
    ChangePasswordRequest,
    TokenOut,
    UserLoginRequest,
    UserOut,
    UserRegisterRequest,
)
from app.utils.jwt import create_access_token, hash_password, verify_password
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=UserOut, summary="注册新用户")
def register(payload: UserRegisterRequest, db: DbSession) -> UserOut:
    """注册新用户。

    Args:
        payload: 注册请求。
        db: 数据库会话。

    Returns:
        新建用户信息。

    Raises:
        HTTPException: 用户名已存在。
    """
    exists = db.query(User).filter(User.username == payload.username).one_or_none()
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已被占用")

    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        email=payload.email,
        role=UserRole.MEMBER.value,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("新用户注册: {}", user.username)
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenOut, summary="登录获取 JWT")
def login(payload: UserLoginRequest, db: DbSession) -> TokenOut:
    """账号密码登录，签发 JWT。

    Args:
        payload: 登录请求。
        db: 数据库会话。

    Returns:
        令牌与用户信息。

    Raises:
        HTTPException: 用户名或密码错误、账号被禁用。
    """
    user = db.query(User).filter(User.username == payload.username).one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        # 统一提示，避免暴露「用户名是否存在」
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用，请联系管理员"
        )

    token = create_access_token(subject=user.username, role=user.role)
    logger.info("用户登录成功: {}", user.username)
    return TokenOut(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_expire_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut, summary="获取当前登录用户")
def read_me(current_user: CurrentUser) -> UserOut:
    """获取当前登录用户信息。

    Args:
        current_user: 当前登录用户。

    Returns:
        用户信息。
    """
    return UserOut.model_validate(current_user)


@router.post("/change-password", response_model=MessageResponse, summary="修改当前用户密码")
def change_password(
    payload: ChangePasswordRequest, current_user: CurrentUser, db: DbSession
) -> MessageResponse:
    """修改当前用户密码。

    Args:
        payload: 修改密码请求。
        current_user: 当前登录用户。
        db: 数据库会话。

    Returns:
        操作结果。

    Raises:
        HTTPException: 原密码错误。
    """
    if not verify_password(payload.old_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码错误")
    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()
    logger.info("用户 {} 修改了密码", current_user.username)
    return MessageResponse(message="密码修改成功，请使用新密码重新登录")
