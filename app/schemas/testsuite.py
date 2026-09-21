"""用例集相关的请求/响应模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel


def _validate_cron(value: str | None) -> str | None:
    """校验 cron 表达式是否为标准 5 段格式。

    Args:
        value: cron 表达式。

    Returns:
        规范化后的表达式；空值原样返回。

    Raises:
        ValueError: 段数不是 5。
    """
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned.split()) != 5:
        raise ValueError("cron 表达式必须是 5 段，例如 '0 2 * * *' 表示每天 02:00")
    return cleaned


class TestSuiteCreateRequest(BaseModel):
    """创建用例集请求。

    Attributes:
        name: 用例集名称。
        description: 说明。
        case_ids: 包含的用例 ID 列表。
        environment_id: 默认执行环境。
        cron_expression: cron 表达式，为空表示不启用定时执行。
        retry_times: 失败重跑次数。
        enabled: 是否启用。
    """

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    case_ids: list[int] = Field(default_factory=list)
    environment_id: int | None = None
    cron_expression: str | None = Field(default=None, max_length=128)
    retry_times: int = Field(default=2, ge=0, le=5)
    enabled: bool = True

    @field_validator("cron_expression")
    @classmethod
    def _check_cron(cls, value: str | None) -> str | None:
        """校验 cron 表达式。"""
        return _validate_cron(value)


class TestSuiteUpdateRequest(BaseModel):
    """更新用例集请求。

    Attributes:
        name: 用例集名称。
        description: 说明。
        case_ids: 包含的用例 ID 列表。
        environment_id: 默认执行环境。
        cron_expression: cron 表达式。
        retry_times: 失败重跑次数。
        enabled: 是否启用。
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    case_ids: list[int] | None = None
    environment_id: int | None = None
    cron_expression: str | None = Field(default=None, max_length=128)
    retry_times: int | None = Field(default=None, ge=0, le=5)
    enabled: bool | None = None

    @field_validator("cron_expression")
    @classmethod
    def _check_cron(cls, value: str | None) -> str | None:
        """校验 cron 表达式。"""
        return _validate_cron(value)


class TestSuiteOut(ORMModel):
    """用例集响应。

    Attributes:
        id: 用例集 ID。
        project_id: 所属项目。
        name: 用例集名称。
        description: 说明。
        case_ids: 包含的用例 ID 列表。
        case_count: 用例数量。
        environment_id: 默认执行环境。
        cron_expression: cron 表达式。
        retry_times: 失败重跑次数。
        enabled: 是否启用。
        last_run_at: 上次执行时间。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    id: int
    project_id: int
    name: str
    description: str | None = None
    case_ids: list[int] = Field(default_factory=list)
    case_count: int = 0
    environment_id: int | None = None
    cron_expression: str | None = None
    retry_times: int = 2
    enabled: bool = True
    last_run_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RunSuiteRequest(BaseModel):
    """执行用例集请求。

    Attributes:
        environment_id: 覆盖用例集自带的环境配置。
        retry_times: 覆盖重跑次数。
    """

    environment_id: int | None = None
    retry_times: int | None = Field(default=None, ge=0, le=5)
