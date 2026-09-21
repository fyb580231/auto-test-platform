"""用例模型：接口用例与 UI 用例共用一张表，用 ``case_type`` 区分。

为什么不拆两张表？
* 两者的「元信息」完全一致（名称、项目、标签、断言、启用状态）；
* 用例集、任务、报告都需要混合编排两类用例，拆表会引入大量 UNION 查询；
* 差异只体现在字段占用上（接口用 method/url/body，UI 用 steps），用 JSON 字段承载即可。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, now

if TYPE_CHECKING:  # pragma: no cover
    from app.models.project import Project


class CaseType(str, Enum):
    """用例类型。"""

    API = "api"
    """接口用例：一次 HTTP 请求 + 一组断言。"""

    UI = "ui"
    """UI 用例：一组 Playwright 步骤编排。"""


class CaseTag(str, Enum):
    """内置标签（用户也可以写自定义标签）。"""

    SMOKE = "smoke"
    REGRESSION = "regression"
    CRITICAL = "critical"


class TestCase(Base):
    """一条测试用例。

    Attributes:
        id: 主键。
        project_id: 所属项目。
        name: 用例名称。
        case_type: 用例类型（api / ui）。
        description: 用例说明。
        tags: 标签列表，支持 smoke / regression / critical 或自定义。
        method: 请求方法（接口用例）。
        url: 请求地址，可写相对路径（接口用例）。
        headers: 请求头（接口用例）。
        params: Query 参数（接口用例）。
        body: JSON 请求体（接口用例）。
        form: 表单请求体（接口用例）。
        setup_case_id: 前置用例 ID，用于先登录拿 Token 等场景。
        extract: 从前置用例响应中提取变量的规则。
        steps: UI 步骤列表（UI 用例）。
        assertions: 断言规则列表。
        enabled: 是否参与批量/定时执行。
        created_by: 创建人 ID。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    __tablename__ = "test_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    case_type: Mapped[str] = mapped_column(String(16), default=CaseType.API.value, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # ---------- 接口用例字段 ----------
    method: Mapped[str | None] = mapped_column(String(16), default="GET", nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    headers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    body: Mapped[Any] = mapped_column(JSON, nullable=True)
    form: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # ---------- 用例编排 ----------
    setup_case_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("test_cases.id", ondelete="SET NULL"), nullable=True
    )
    extract: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    # ---------- UI 用例字段 ----------
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    # ---------- 断言 ----------
    assertions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now, onupdate=now, nullable=False
    )

    project: Mapped[Project] = relationship("Project", back_populates="testcases")

    def to_engine_payload(self, setup_case: TestCase | None = None) -> dict[str, Any]:
        """转换成引擎层可执行的用例载荷。

        这一步是「服务层 -> 引擎层」的适配层：数据库模型形状与引擎输入形状解耦，
        以后要改表结构，只需要改这一个方法。

        Args:
            setup_case: 已解析好的前置用例对象。

        Returns:
            引擎层可消费的字典。
        """
        payload: dict[str, Any] = {
            "id": str(self.id),
            "name": self.name,
            "case_type": self.case_type,
            "tags": self.tags or [],
            "assertions": self.assertions or [],
            "extract": self.extract or [],
            "variables": {},
        }
        if self.case_type == CaseType.UI.value:
            payload["steps"] = self.steps or []
            # UI 用例把被测站点地址放在 url 字段（语义即「这条用例的目标地址」）
            payload["base_url"] = self.url or ""
            return payload

        payload["request"] = {
            "method": (self.method or "GET").upper(),
            "url": self.url or "",
            "headers": self.headers or {},
            "params": self.params or {},
            "body": self.body,
            "form": self.form or {},
        }
        if setup_case is not None:
            payload["setup_case"] = {
                "name": setup_case.name,
                "request": {
                    "method": (setup_case.method or "GET").upper(),
                    "url": setup_case.url or "",
                    "headers": setup_case.headers or {},
                    "params": setup_case.params or {},
                    "body": setup_case.body,
                    "form": setup_case.form or {},
                },
                "extract": self.extract or [],
            }
        return payload

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<TestCase id={self.id} name={self.name!r} type={self.case_type}>"
