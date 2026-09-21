"""通用 Pydantic 模型：分页、消息响应、断言与 UI 步骤结构。

断言规则与 UI 步骤在这里定义**唯一的权威形状**（single source of truth），
前端表单、后端入库、AI 生成结果都按这个形状对齐，避免三处各写一份导致漂移。
"""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

# 断言类型 / 操作符（与 engine.assertions 中的常量保持一致）
AssertType = Literal["status_code", "json_field", "response_time", "schema", "header"]
AssertOp = Literal[
    "eq",
    "ne",
    "contains",
    "not_contains",
    "gt",
    "lt",
    "ge",
    "le",
    "empty",
    "not_empty",
    "in",
    "regex",
    "length_eq",
]

# UI 动作类型（与 engine.ui_actions 中的常量保持一致）
UIAction = Literal[
    "open",
    "click",
    "input",
    "assert_visible",
    "assert_text",
    "assert_url",
    "assert_value",
    "wait",
    "select",
    "hover",
    "press",
    "screenshot",
]


class ORMModel(BaseModel):
    """允许从 ORM 对象直接构造的基类。"""

    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    """统一的简单操作响应。

    Attributes:
        success: 是否成功。
        message: 提示信息。
        data: 附加数据。
    """

    success: bool = True
    message: str = "操作成功"
    data: Any = None


class PageResult(BaseModel, Generic[T]):
    """统一分页响应。

    Attributes:
        total: 总条数。
        page: 当前页（从 1 开始）。
        size: 每页条数。
        items: 当前页数据。
    """

    total: int = 0
    page: int = 1
    size: int = 20
    items: list[T] = Field(default_factory=list)


class AssertionRuleSchema(BaseModel):
    """一条断言规则。

    Attributes:
        type: 断言类型。
        expected: 期望值。
        field: 取值表达式（json_field / header 必填），如 ``$.data.token``。
        op: 比较操作符。
        message: 自定义失败提示。
        name: 规则名称。
    """

    type: AssertType = "status_code"
    expected: Any = None
    field: str | None = None
    op: AssertOp = "eq"
    message: str | None = None
    name: str | None = None


class UIStepSchema(BaseModel):
    """一个 UI 步骤。

    Attributes:
        action: 动作类型。
        selector: 元素选择器。
        value: 输入值或断言期望值。
        timeout: 超时毫秒数。
        name: 步骤名称。
    """

    action: UIAction
    selector: str | None = None
    value: str | None = None
    timeout: int = 15000
    name: str | None = None


class ExtractRuleSchema(BaseModel):
    """前置用例的变量提取规则。

    Attributes:
        name: 变量名，主用例里用 ``{{name}}`` 引用。
        path: JSON 取值路径，如 ``$.data.token``。
    """

    name: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=256)
