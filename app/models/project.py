"""项目模型：用例、用例集、环境的隔离边界。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, now

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注
    from app.models.environment import Environment
    from app.models.testcase import TestCase


class Project(Base):
    """测试项目。

    项目是平台里最重要的一层隔离：用例、用例集、环境变量全部挂在项目下，
    删除项目会级联删除其下所有数据，避免出现「孤儿用例」。

    Attributes:
        id: 主键。
        name: 项目名称，全局唯一。
        description: 项目描述。
        owner_id: 创建人 ID。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now, onupdate=now, nullable=False
    )

    testcases: Mapped[list[TestCase]] = relationship(
        "TestCase",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    environments: Mapped[list[Environment]] = relationship(
        "Environment",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Project id={self.id} name={self.name!r}>"
