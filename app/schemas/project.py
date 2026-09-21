"""项目相关的请求/响应模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ProjectCreateRequest(BaseModel):
    """创建项目请求。

    Attributes:
        name: 项目名称，全局唯一。
        description: 项目描述。
    """

    name: str = Field(min_length=1, max_length=128, description="项目名称")
    description: str | None = Field(default=None, max_length=2000, description="项目描述")


class ProjectUpdateRequest(BaseModel):
    """更新项目请求（字段可选）。

    Attributes:
        name: 项目名称。
        description: 项目描述。
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)


class ProjectOut(ORMModel):
    """项目响应。

    Attributes:
        id: 项目 ID。
        name: 项目名称。
        description: 项目描述。
        owner_id: 创建人 ID。
        case_count: 用例数量（派生统计）。
        suite_count: 用例集数量（派生统计）。
        environment_count: 环境数量（派生统计）。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    id: int
    name: str
    description: str | None = None
    owner_id: int | None = None
    case_count: int = 0
    suite_count: int = 0
    environment_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
