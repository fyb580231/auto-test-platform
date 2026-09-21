"""Dashboard 统计相关的响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.task import TaskOut


class TrendPoint(BaseModel):
    """通过率趋势上的一个点。

    Attributes:
        date: 日期（YYYY-MM-DD）。
        total: 当日用例总数。
        passed: 当日通过数。
        failed: 当日失败数。
        pass_rate: 当日通过率（百分比）。
        task_count: 当日任务数。
    """

    date: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    task_count: int = 0


class ProjectStat(BaseModel):
    """按项目聚合的统计。

    Attributes:
        project_id: 项目 ID。
        project_name: 项目名称。
        task_count: 任务数。
        total: 用例总数。
        passed: 通过数。
        failed: 失败数。
        pass_rate: 通过率（百分比）。
    """

    project_id: int
    project_name: str
    task_count: int = 0
    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0


class NameValueStat(BaseModel):
    """通用「名称-数值」统计（用于饼图 / 柱状图）。

    Attributes:
        name: 维度名称。
        value: 数值。
    """

    name: str
    value: float = 0.0


class DashboardSummary(BaseModel):
    """首页概览卡片数据。

    Attributes:
        project_count: 项目数。
        case_count: 用例数。
        suite_count: 用例集数。
        task_count_7d: 近 7 天任务数。
        pass_rate_7d: 近 7 天用例通过率（百分比）。
        failed_task_count_7d: 近 7 天失败任务数。
        avg_duration_ms: 近 7 天平均任务耗时（毫秒）。
    """

    project_count: int = 0
    case_count: int = 0
    suite_count: int = 0
    task_count_7d: int = 0
    pass_rate_7d: float = 0.0
    failed_task_count_7d: int = 0
    avg_duration_ms: int = 0


class DashboardStatsOut(BaseModel):
    """Dashboard 完整统计响应。

    Attributes:
        summary: 概览卡片。
        trend: 通过率趋势。
        project_stats: 各项目通过率。
        fail_distribution: 失败用例 TOP N 分布。
        status_distribution: 任务状态分布。
        recent_tasks: 最近任务。
        days: 统计窗口天数。
    """

    summary: DashboardSummary = Field(default_factory=DashboardSummary)
    trend: list[TrendPoint] = Field(default_factory=list)
    project_stats: list[ProjectStat] = Field(default_factory=list)
    fail_distribution: list[NameValueStat] = Field(default_factory=list)
    status_distribution: list[NameValueStat] = Field(default_factory=list)
    recent_tasks: list[TaskOut] = Field(default_factory=list)
    days: int = 7
    extra: dict[str, Any] = Field(default_factory=dict)
