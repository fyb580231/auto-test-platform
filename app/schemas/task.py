"""执行任务与报告相关的请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

TaskStatusLiteral = Literal["pending", "running", "success", "failed", "error"]


class TaskOut(ORMModel):
    """任务列表项响应。

    Attributes:
        id: 任务 ID。
        task_no: 任务编号。
        project_id: 所属项目。
        project_name: 项目名称。
        suite_id: 来源用例集。
        name: 任务名称。
        trigger_type: 触发来源。
        environment_name: 执行环境名称。
        case_count: 用例数量。
        status: 任务状态。
        total: 用例总数。
        passed: 通过数。
        failed: 失败数。
        skipped: 跳过数。
        pass_rate: 通过率。
        duration_ms: 耗时毫秒。
        started_at: 开始时间。
        finished_at: 结束时间。
        error_message: 执行器级错误。
        has_ai_analysis: 是否已有 AI 分析。
        created_at: 创建时间。
    """

    id: int
    task_no: str
    project_id: int | None = None
    project_name: str | None = None
    suite_id: int | None = None
    name: str = ""
    trigger_type: str = "manual"
    environment_name: str = ""
    case_ids: list[int] = Field(default_factory=list)
    case_count: int = 0
    status: TaskStatusLiteral = "pending"
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    pass_rate: float = 0.0
    duration_ms: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    has_ai_analysis: bool = False
    created_at: datetime | None = None


class TaskDetailOut(TaskOut):
    """任务详情响应（含每条用例的结果明细）。

    Attributes:
        results: 每条用例的执行结果。
        log_path: 日志路径。
        allure_results_dir: Allure 结果目录。
        allure_report_url: Allure HTML 报告访问地址；未生成时为空。
        ai_analysis: AI 失败分析文本。
        stdout_tail: 控制台输出尾部。
    """

    results: list[dict[str, Any]] = Field(default_factory=list)
    log_path: str = ""
    allure_results_dir: str = ""
    allure_report_url: str = ""
    ai_analysis: str | None = None
    stdout_tail: str = ""


class TaskLogOut(BaseModel):
    """任务日志响应。

    Attributes:
        task_no: 任务编号。
        content: 日志内容。
        truncated: 是否被截断。
    """

    task_no: str
    content: str = ""
    truncated: bool = False


class TaskQuery(BaseModel):
    """任务列表查询条件。

    Attributes:
        project_id: 按项目过滤。
        status: 按状态过滤。
        trigger_type: 按触发来源过滤。
        keyword: 按任务名/编号模糊搜索。
        page: 页码。
        size: 每页条数。
    """

    project_id: int | None = None
    status: TaskStatusLiteral | None = None
    trigger_type: str | None = None
    keyword: str | None = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=200)
