"""用例集模型：把多条用例打包，支持手工执行与 cron 定时执行。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, now

if TYPE_CHECKING:  # pragma: no cover
    from app.models.project import Project


class TestSuite(Base):
    """测试用例集。

    Attributes:
        id: 主键。
        project_id: 所属项目。
        name: 用例集名称。
        description: 说明。
        case_ids: 包含的用例 ID 列表（保持用户编排顺序）。
        environment_id: 默认执行环境。
        cron_expression: cron 表达式；为空表示不定时执行。
        retry_times: 失败重跑次数。
        enabled: 是否启用（关闭后定时任务不会触发）。
        last_run_at: 上次执行时间。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    __tablename__ = "test_suites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    environment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("environments.id", ondelete="SET NULL"), nullable=True
    )
    cron_expression: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retry_times: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now, onupdate=now, nullable=False
    )

    project: Mapped[Project] = relationship("Project")

    @property
    def job_id(self) -> str:
        """APScheduler 中的任务 ID。"""
        return f"suite_{self.id}"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（含派生字段）。

        Returns:
            字典结构。
        """
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "case_ids": self.case_ids or [],
            "case_count": len(self.case_ids or []),
            "environment_id": self.environment_id,
            "cron_expression": self.cron_expression,
            "retry_times": self.retry_times,
            "enabled": self.enabled,
            "last_run_at": self.last_run_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<TestSuite id={self.id} name={self.name!r} cases={len(self.case_ids or [])}>"
