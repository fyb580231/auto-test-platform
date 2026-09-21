"""执行任务模型：每次执行都会落一条记录，作为报告与 AI 分析的数据源。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now


class TaskStatus(str, Enum):
    """任务状态。"""

    PENDING = "pending"
    """已创建，等待执行。"""

    RUNNING = "running"
    """执行中。"""

    SUCCESS = "success"
    """全部用例通过。"""

    FAILED = "failed"
    """存在失败用例。"""

    ERROR = "error"
    """执行器本身异常（超时、崩溃、无结果）。"""


class TriggerType(str, Enum):
    """任务触发来源。"""

    MANUAL = "manual"
    """页面上手工点击执行。"""

    SCHEDULE = "schedule"
    """APScheduler 定时触发。"""

    CI = "ci"
    """CI / 命令行触发。"""


class Task(Base):
    """一次测试执行任务。

    Attributes:
        id: 主键。
        task_no: 任务编号（32 位十六进制），用于命名产物目录与对外展示。
        project_id: 所属项目。
        suite_id: 来源用例集（单条/批量执行时为空）。
        name: 任务名称。
        trigger_type: 触发来源。
        environment_id: 执行环境 ID。
        environment_name: 执行环境名称快照（环境被删后仍可追溯）。
        case_ids: 本次执行的用例 ID 列表。
        case_count: 用例数量。
        retry_times: 失败重跑次数。
        status: 任务状态。
        total: 用例总数。
        passed: 通过数。
        failed: 失败数。
        skipped: 跳过数。
        pass_rate: 通过率（百分比）。
        duration_ms: 总耗时毫秒。
        started_at: 开始时间。
        finished_at: 结束时间。
        log_path: 控制台日志路径。
        allure_results_dir: Allure 原始结果目录。
        allure_report_path: Allure HTML 报告目录。
        result_detail: 每条用例的完整结果（请求/响应/断言/截图）。
        ai_analysis: AI 失败分析结果。
        error_message: 执行器级错误信息。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_no: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    suite_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("test_suites.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), default="手工执行", nullable=False)
    trigger_type: Mapped[str] = mapped_column(
        String(16), default=TriggerType.MANUAL.value, nullable=False
    )

    environment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    environment_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    case_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_times: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), default=TaskStatus.PENDING.value, index=True, nullable=False
    )
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pass_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    log_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    allure_results_dir: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    allure_report_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)

    result_detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    ai_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now, onupdate=now, nullable=False
    )

    @property
    def is_finished(self) -> bool:
        """任务是否已结束（成功或失败）。"""
        return self.status in {
            TaskStatus.SUCCESS.value,
            TaskStatus.FAILED.value,
            TaskStatus.ERROR.value,
        }

    def results(self) -> list[dict[str, Any]]:
        """获取每条用例的结果列表。

        Returns:
            结果列表；无数据时返回空列表。
        """
        detail = self.result_detail or {}
        results = detail.get("results", [])
        return results if isinstance(results, list) else []

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Task id={self.id} no={self.task_no} status={self.status}>"
