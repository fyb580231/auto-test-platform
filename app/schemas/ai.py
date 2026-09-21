"""AI 能力相关的请求/响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.testcase import TestCaseCreateRequest


class GenerateCasesRequest(BaseModel):
    """AI 生成用例请求。

    Attributes:
        url: 接口地址（可写相对路径，执行时按环境 base_url 拼接）。
        method: 请求方法。
        description: 业务描述，例如「用户登录，账号密码正确返回 token」。
        case_count: 期望生成的用例条数（4-12）。
        tags: 生成用例默认带上的标签。
        extra_requirements: 额外要求，例如「必须覆盖密码错误 5 次锁定」。
    """

    url: str = Field(min_length=1, max_length=1024, description="接口地址")
    method: str = Field(default="GET", max_length=16, description="请求方法")
    description: str = Field(min_length=2, max_length=2000, description="业务描述")
    case_count: int = Field(default=6, ge=4, le=12, description="期望生成条数")
    tags: list[str] = Field(default_factory=lambda: ["ai"], description="默认标签")
    extra_requirements: str | None = Field(default=None, max_length=2000)


class GenerateCasesResponse(BaseModel):
    """AI 生成用例响应。

    Attributes:
        cases: 生成的用例列表（可直接调用导入接口落库）。
        model: 实际使用的模型名。
        mocked: 是否走了 Mock 降级（未配置 API Key 时为 True）。
        usage: Token 用量统计，用于成本控制。
        raw: 模型原始返回，便于排查生成质量问题。
    """

    cases: list[TestCaseCreateRequest] = Field(default_factory=list)
    model: str = ""
    mocked: bool = False
    usage: dict[str, Any] = Field(default_factory=dict)
    raw: str = ""


class AnalyzeRequest(BaseModel):
    """AI 失败分析请求。

    Attributes:
        task_id: 任务 ID。
        case_result_index: 指定分析第几条失败结果；为空则分析第一条失败用例。
        include_request: 是否把请求详情一并送入模型（可能包含敏感信息）。
    """

    task_id: int = Field(description="任务 ID")
    case_result_index: int | None = Field(default=None, ge=0)
    include_request: bool = Field(default=True)


class AnalysisResponse(BaseModel):
    """AI 失败分析响应。

    Attributes:
        task_id: 任务 ID。
        case_name: 被分析的用例名。
        category: 归因分类（接口缺陷 / 脚本缺陷 / 环境问题 / 用例设计问题）。
        summary: 一句话结论。
        reasons: 判断依据列表。
        suggestions: 修复建议列表。
        raw: 模型原始输出。
        mocked: 是否走了 Mock 降级。
        usage: Token 用量。
    """

    task_id: int
    case_name: str = ""
    category: str = "未知"
    summary: str = ""
    reasons: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    raw: str = ""
    mocked: bool = False
    usage: dict[str, Any] = Field(default_factory=dict)


class QueryReportRequest(BaseModel):
    """AI 自然语言查报告请求。

    Attributes:
        question: 自然语言问题，例如「最近一周哪个项目失败最多」。
        days: 统计窗口天数。
    """

    question: str = Field(min_length=2, max_length=500, description="自然语言问题")
    days: int = Field(default=7, ge=1, le=90, description="统计窗口天数")


class QueryReportResponse(BaseModel):
    """AI 自然语言查报告响应。

    Attributes:
        question: 原始问题。
        answer: 自然语言回答。
        stats: 供模型与前端共用的结构化统计上下文。
        mocked: 是否走了 Mock 降级。
        usage: Token 用量。
    """

    question: str
    answer: str = ""
    stats: dict[str, Any] = Field(default_factory=dict)
    mocked: bool = False
    usage: dict[str, Any] = Field(default_factory=dict)


class AIStatusOut(BaseModel):
    """AI 能力状态响应，用于前端提示「当前是 Mock 模式」。

    Attributes:
        enabled: 开关是否打开。
        available: 是否可发起真实模型调用。
        mocked: 当前是否处于 Mock 降级。
        model: 模型名。
        base_url: 接口地址。
        message: 给用户看的提示文案。
    """

    enabled: bool = True
    available: bool = False
    mocked: bool = True
    model: str = ""
    base_url: str = ""
    message: str = ""
