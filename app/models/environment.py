"""环境变量模型：同一套用例在不同环境下跑出不同结果的关键。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, now

if TYPE_CHECKING:  # pragma: no cover
    from app.models.project import Project


class Environment(Base):
    """项目下的一个运行环境（dev / staging / prod ...）。

    Attributes:
        id: 主键。
        project_id: 所属项目。
        name: 环境名称，同项目内唯一。
        base_url: 接口基地址，用例里写相对路径时会拼接它。
        headers: 公共请求头，所有用例默认带上。
        variables: 全局变量，用例里用 ``{{变量名}}`` 引用。
        verify: 是否校验 HTTPS 证书。
        timeout: 默认超时秒数。
        is_default: 是否为项目默认环境。
        description: 备注。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    __tablename__ = "environments"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_environment_project_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    headers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    variables: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    verify: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timeout: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now, onupdate=now, nullable=False
    )

    project: Mapped[Project] = relationship("Project", back_populates="environments")

    def to_runtime_config(self) -> dict[str, Any]:
        """转换成引擎层需要的运行环境配置。

        Returns:
            引擎层可直接消费的字典。
        """
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "headers": self.headers or {},
            "variables": self.variables or {},
            "verify": self.verify,
            "timeout": self.timeout,
        }

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Environment id={self.id} name={self.name!r} base_url={self.base_url!r}>"
