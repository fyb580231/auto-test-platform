"""用户模型。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now


class UserRole(str, Enum):
    """用户角色。"""

    ADMIN = "admin"
    """管理员：可创建/删除项目、管理全部用例。"""

    MEMBER = "member"
    """普通成员：可管理自己参与项目下的用例。"""


class User(Base):
    """平台用户。

    Attributes:
        id: 主键。
        username: 登录名，全局唯一。
        hashed_password: bcrypt 哈希后的密码，绝不存明文。
        email: 邮箱（可选）。
        role: 角色，取值见 ``UserRole``。
        is_active: 是否启用。
        created_at: 创建时间。
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default=UserRole.MEMBER.value, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    @property
    def is_admin(self) -> bool:
        """是否为管理员。"""
        return self.role == UserRole.ADMIN.value

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<User id={self.id} username={self.username!r} role={self.role}>"
