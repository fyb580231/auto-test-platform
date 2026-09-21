"""测试用例相关的请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import (
    AssertionRuleSchema,
    ExtractRuleSchema,
    ORMModel,
    UIStepSchema,
)

CaseTypeLiteral = Literal["api", "ui"]


class TestCaseBase(BaseModel):
    """用例的公共字段。

    Attributes:
        name: 用例名称。
        case_type: 用例类型（api / ui）。
        description: 用例说明。
        tags: 标签列表。
        method: 请求方法。
        url: 请求地址。
        headers: 请求头。
        params: Query 参数。
        body: JSON 请求体。
        form: 表单请求体。
        setup_case_id: 前置用例 ID。
        extract: 变量提取规则。
        steps: UI 步骤。
        assertions: 断言规则。
        enabled: 是否启用。
    """

    name: str = Field(min_length=1, max_length=255, description="用例名称")
    case_type: CaseTypeLiteral = Field(default="api", description="用例类型")
    description: str | None = Field(default=None, max_length=2000)

    tags: list[str] = Field(default_factory=list, description="标签，如 smoke / regression")
    method: str = Field(default="GET", max_length=16)
    url: str = Field(default="", max_length=1024)
    headers: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    body: Any = None
    form: dict[str, Any] = Field(default_factory=dict)

    setup_case_id: int | None = None
    extract: list[ExtractRuleSchema] = Field(default_factory=list)

    steps: list[UIStepSchema] = Field(default_factory=list)
    assertions: list[AssertionRuleSchema] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("method")
    @classmethod
    def _upper_method(cls, value: str) -> str:
        """统一把请求方法转成大写。

        Args:
            value: 原始方法名。

        Returns:
            大写方法名。
        """
        return value.strip().upper() or "GET"

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        """标签去重、去空格并保持顺序。

        Args:
            value: 原始标签列表。

        Returns:
            规范化后的标签列表。
        """
        seen: set[str] = set()
        result: list[str] = []
        for tag in value:
            cleaned = str(tag).strip().lower()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result


class TestCaseCreateRequest(TestCaseBase):
    """创建用例请求。"""


class TestCaseUpdateRequest(BaseModel):
    """更新用例请求（全部字段可选）。

    Attributes:
        name: 用例名称。
        case_type: 用例类型。
        description: 用例说明。
        tags: 标签列表。
        method: 请求方法。
        url: 请求地址。
        headers: 请求头。
        params: Query 参数。
        body: JSON 请求体。
        form: 表单请求体。
        setup_case_id: 前置用例 ID。
        extract: 变量提取规则。
        steps: UI 步骤。
        assertions: 断言规则。
        enabled: 是否启用。
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    case_type: CaseTypeLiteral | None = None
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = None
    method: str | None = Field(default=None, max_length=16)
    url: str | None = Field(default=None, max_length=1024)
    headers: dict[str, Any] | None = None
    params: dict[str, Any] | None = None
    body: Any = None
    form: dict[str, Any] | None = None
    setup_case_id: int | None = None
    extract: list[ExtractRuleSchema] | None = None
    steps: list[UIStepSchema] | None = None
    assertions: list[AssertionRuleSchema] | None = None
    enabled: bool | None = None


class TestCaseOut(ORMModel):
    """用例响应。

    Attributes:
        id: 用例 ID。
        project_id: 所属项目。
        name: 用例名称。
        case_type: 用例类型。
        description: 用例说明。
        tags: 标签列表。
        method: 请求方法。
        url: 请求地址。
        headers: 请求头。
        params: Query 参数。
        body: JSON 请求体。
        form: 表单请求体。
        setup_case_id: 前置用例 ID。
        setup_case_name: 前置用例名称（便于前端展示）。
        extract: 变量提取规则。
        steps: UI 步骤。
        assertions: 断言规则。
        enabled: 是否启用。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    id: int
    project_id: int
    name: str
    case_type: CaseTypeLiteral = "api"
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    method: str | None = "GET"
    url: str | None = ""
    headers: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    body: Any = None
    form: dict[str, Any] = Field(default_factory=dict)
    setup_case_id: int | None = None
    setup_case_name: str | None = None
    extract: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    assertions: list[dict[str, Any]] = Field(default_factory=list)
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RunCasesRequest(BaseModel):
    """执行用例请求。

    Attributes:
        case_ids: 要执行的用例 ID 列表。
        environment_id: 指定环境；为空则使用项目默认环境。
        retry_times: 失败重跑次数；为空则使用全局默认值。
        name: 任务名称。
    """

    case_ids: list[int] = Field(min_length=1, description="用例 ID 列表")
    environment_id: int | None = None
    retry_times: int | None = Field(default=None, ge=0, le=5)
    name: str | None = Field(default=None, max_length=255)


class ImportCasesRequest(BaseModel):
    """批量导入用例请求（AI 生成结果 / YAML 文件导入都走它）。

    Attributes:
        cases: 用例数据列表。
        overwrite: 同名用例是否覆盖。
    """

    cases: list[TestCaseCreateRequest] = Field(min_length=1)
    overwrite: bool = False
