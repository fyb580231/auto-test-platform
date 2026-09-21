"""用户与认证相关的请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class UserRegisterRequest(BaseModel):
    """注册请求。

    Attributes:
        username: 登录名，3-64 位。
        password: 明文密码，6-128 位。
        email: 邮箱（可选）。
    """

    username: str = Field(min_length=3, max_length=64, description="登录名")
    password: str = Field(min_length=6, max_length=128, description="密码")
    email: str | None = Field(default=None, max_length=255, description="邮箱")


class UserLoginRequest(BaseModel):
    """登录请求。

    Attributes:
        username: 登录名。
        password: 明文密码。
    """

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(ORMModel):
    """用户信息响应（绝不含密码字段）。

    Attributes:
        id: 用户 ID。
        username: 登录名。
        email: 邮箱。
        role: 角色。
        is_active: 是否启用。
        created_at: 创建时间。
    """

    id: int
    username: str
    email: str | None = None
    role: Literal["admin", "member"] = "member"
    is_active: bool = True
    created_at: datetime | None = None


class TokenOut(BaseModel):
    """登录成功后的令牌响应。

    Attributes:
        access_token: JWT 字符串。
        token_type: 固定为 bearer。
        expires_in: 有效期秒数。
        user: 登录用户信息。
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int = 0
    user: UserOut


class ChangePasswordRequest(BaseModel):
    """修改密码请求。

    Attributes:
        old_password: 原密码。
        new_password: 新密码。
    """

    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)
