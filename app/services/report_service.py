"""报告统计服务：把原始执行记录聚合成前端图表与 AI 问答所需的数据。

为什么单独抽一个 service？
* 统计逻辑必须只调用 SQLAlchemy，不能出现在路由层（路由层只做参数校验与转发）；
* Dashboard 图表与「AI 自然语言查报告」用的是**同一份统计口径**，
  抽出来才能保证「AI 说的话」和「图表上的数」永远一致。
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import now
from app.models import Project, Task, TaskStatus, TestCase, TestSuite
from app.schemas.dashboard import (
    DashboardStatsOut,
    DashboardSummary,
    NameValueStat,
    ProjectStat,
    TrendPoint,
)
from app.schemas.task import TaskOut
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 计算失败用例分布时最多回溯的任务数，避免全表扫描
_FAIL_SCAN_TASK_LIMIT = 100
_RECENT_TASK_LIMIT = 10
_TOP_FAIL_CASES = 8


class ReportService:
    """报告与统计服务。

    Attributes:
        db: 数据库会话。
    """

    def __init__(self, db: Session) -> None:
        """初始化服务。

        Args:
            db: 数据库会话。
        """
        self.db = db

    # ------------------------------------------------------------------ #
    # Dashboard
    # ------------------------------------------------------------------ #
    def dashboard(self, days: int = 7) -> DashboardStatsOut:
        """聚合首页所需的全部统计。

        Args:
            days: 统计窗口天数。

        Returns:
            Dashboard 统计响应。
        """
        since = now() - timedelta(days=days)
        tasks = (
            self.db.query(Task)
            .filter(Task.created_at >= since)
            .order_by(Task.created_at.desc())
            .all()
        )
        finished = [task for task in tasks if task.is_finished]

        return DashboardStatsOut(
            summary=self._build_summary(tasks, finished, days),
            trend=self._build_trend(tasks, days),
            project_stats=self._build_project_stats(finished),
            fail_distribution=self._build_fail_distribution(tasks),
            status_distribution=self._build_status_distribution(tasks),
            recent_tasks=self._build_recent_tasks(),
            days=days,
        )

    def stats_context(self, days: int = 7) -> dict[str, Any]:
        """构造给 AI 使用的结构化统计上下文。

        与 ``dashboard()`` 共用同一套口径，保证 AI 回答与图表数据一致；
        同时刻意控制体积（只给 TOP N），避免把整个数据库塞进提示词。

        Args:
            days: 统计窗口天数。

        Returns:
            结构化统计字典。
        """
        since = now() - timedelta(days=days)
        tasks = self.db.query(Task).filter(Task.created_at >= since).all()
        finished = [task for task in tasks if task.is_finished]
        trend = self._build_trend(tasks, days)
        project_stats = self._build_project_stats(finished)
        fail_distribution = self._build_fail_distribution(tasks)

        total_cases = sum(task.total for task in finished)
        passed_cases = sum(task.passed for task in finished)
        return {
            "days": days,
            "generated_at": now().isoformat(timespec="seconds"),
            "summary": {
                "task_count": len(finished),
                "total_cases": total_cases,
                "passed_cases": passed_cases,
                "failed_cases": sum(task.failed for task in finished),
                "pass_rate": round(passed_cases / total_cases * 100, 2) if total_cases else 0.0,
                "project_count": self.db.query(Project).count(),
                "case_count": self.db.query(TestCase).count(),
            },
            "projects": [item.model_dump() for item in project_stats],
            "trend": [point.model_dump() for point in trend],
            "top_failed_cases": [item.model_dump() for item in fail_distribution],
            "status_distribution": [
                item.model_dump() for item in self._build_status_distribution(tasks)
            ],
        }

    # ------------------------------------------------------------------ #
    # 内部聚合实现
    # ------------------------------------------------------------------ #
    def _build_summary(
        self, tasks: list[Task], finished: list[Task], days: int
    ) -> DashboardSummary:
        """构造概览卡片数据。

        Args:
            tasks: 窗口内全部任务。
            finished: 窗口内已结束的任务。
            days: 统计窗口天数。

        Returns:
            概览数据。
        """
        _ = days
        total_cases = sum(task.total for task in finished)
        passed_cases = sum(task.passed for task in finished)
        durations = [task.duration_ms for task in finished if task.duration_ms > 0]
        return DashboardSummary(
            project_count=self.db.query(Project).count(),
            case_count=self.db.query(TestCase).count(),
            suite_count=self.db.query(TestSuite).count(),
            task_count_7d=len(tasks),
            pass_rate_7d=round(passed_cases / total_cases * 100, 2) if total_cases else 0.0,
            failed_task_count_7d=sum(
                1
                for task in finished
                if task.status in {TaskStatus.FAILED.value, TaskStatus.ERROR.value}
            ),
            avg_duration_ms=int(sum(durations) / len(durations)) if durations else 0,
        )

    def _build_trend(self, tasks: list[Task], days: int) -> list[TrendPoint]:
        """按天聚合成通过率趋势（包含没有执行记录的日期，保证 X 轴连续）。

        Args:
            tasks: 窗口内任务。
            days: 统计窗口天数。

        Returns:
            趋势点列表（按日期升序）。
        """
        buckets: dict[str, dict[str, int]] = {}
        today = now().date()
        for offset in range(days - 1, -1, -1):
            key = (today - timedelta(days=offset)).isoformat()
            buckets[key] = {"total": 0, "passed": 0, "failed": 0, "task_count": 0}

        for task in tasks:
            if not task.is_finished and task.status not in {TaskStatus.RUNNING.value}:
                continue
            stamp = task.started_at or task.created_at
            key = stamp.date().isoformat()
            if key not in buckets:
                continue
            buckets[key]["total"] += task.total
            buckets[key]["passed"] += task.passed
            buckets[key]["failed"] += task.failed
            buckets[key]["task_count"] += 1

        points: list[TrendPoint] = []
        for key, value in buckets.items():
            total = value["total"]
            points.append(
                TrendPoint(
                    date=key,
                    total=total,
                    passed=value["passed"],
                    failed=value["failed"],
                    pass_rate=round(value["passed"] / total * 100, 2) if total else 0.0,
                    task_count=value["task_count"],
                )
            )
        return points

    def _build_project_stats(self, tasks: list[Task]) -> list[ProjectStat]:
        """按项目聚合通过率。

        Args:
            tasks: 已结束的任务列表。

        Returns:
            项目统计列表（按失败数降序）。
        """
        projects = {project.id: project.name for project in self.db.query(Project).all()}
        buckets: dict[int, dict[str, int]] = {}
        for task in tasks:
            if task.project_id is None:
                continue
            bucket = buckets.setdefault(
                task.project_id, {"task_count": 0, "total": 0, "passed": 0, "failed": 0}
            )
            bucket["task_count"] += 1
            bucket["total"] += task.total
            bucket["passed"] += task.passed
            bucket["failed"] += task.failed

        stats: list[ProjectStat] = []
        for project_id, bucket in buckets.items():
            total = bucket["total"]
            stats.append(
                ProjectStat(
                    project_id=project_id,
                    project_name=projects.get(project_id, f"项目 {project_id}"),
                    task_count=bucket["task_count"],
                    total=total,
                    passed=bucket["passed"],
                    failed=bucket["failed"],
                    pass_rate=round(bucket["passed"] / total * 100, 2) if total else 0.0,
                )
            )
        return sorted(stats, key=lambda item: item.failed, reverse=True)

    def _build_fail_distribution(self, tasks: list[Task]) -> list[NameValueStat]:
        """统计失败次数最多的用例（供饼图/柱状图展示）。

        实现说明：失败明细以 JSON 形式存在 ``tasks.result_detail`` 里，
        SQLite/MySQL 对 JSON 内数组的聚合能力不一致，因此这里只在**最近 N 个任务**
        上做应用层聚合，用可控的内存换跨数据库一致性。

        Args:
            tasks: 窗口内任务。

        Returns:
            「用例名 -> 失败次数」列表，按次数降序。
        """
        counter: Counter[str] = Counter()
        for scanned, task in enumerate(tasks):
            if scanned >= _FAIL_SCAN_TASK_LIMIT:
                break
            for result in task.results():
                if result.get("status") in {"failed", "error"}:
                    counter[str(result.get("case_name") or "未知用例")] += 1
        return [
            NameValueStat(name=name, value=float(count))
            for name, count in counter.most_common(_TOP_FAIL_CASES)
        ]

    def _build_status_distribution(self, tasks: list[Task]) -> list[NameValueStat]:
        """统计任务状态分布。

        Args:
            tasks: 窗口内任务。

        Returns:
            状态分布列表。
        """
        counter: Counter[str] = Counter(task.status for task in tasks)
        label_map = {
            TaskStatus.SUCCESS.value: "成功",
            TaskStatus.FAILED.value: "失败",
            TaskStatus.ERROR.value: "执行异常",
            TaskStatus.RUNNING.value: "执行中",
            TaskStatus.PENDING.value: "等待中",
        }
        return [
            NameValueStat(name=label_map.get(key, key), value=float(count))
            for key, count in counter.items()
        ]

    def _build_recent_tasks(self) -> list[TaskOut]:
        """获取最近的任务列表。

        Returns:
            最近任务列表。
        """
        tasks = self.db.query(Task).order_by(Task.created_at.desc()).limit(_RECENT_TASK_LIMIT).all()
        return [serialize_task(self.db, task) for task in tasks]


def serialize_task(db: Session, task: Task) -> TaskOut:
    """把任务 ORM 对象序列化成对外响应模型。

    Args:
        db: 数据库会话（用于补齐项目名）。
        task: 任务对象。

    Returns:
        任务响应模型。
    """
    project_name = None
    if task.project_id is not None:
        project = db.get(Project, task.project_id)
        project_name = project.name if project else None
    return TaskOut(
        id=task.id,
        task_no=task.task_no,
        project_id=task.project_id,
        project_name=project_name,
        suite_id=task.suite_id,
        name=task.name,
        trigger_type=task.trigger_type,
        environment_name=task.environment_name,
        case_ids=task.case_ids or [],
        case_count=task.case_count,
        status=task.status,  # type: ignore[arg-type]
        total=task.total,
        passed=task.passed,
        failed=task.failed,
        skipped=task.skipped,
        pass_rate=task.pass_rate,
        duration_ms=task.duration_ms,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error_message=task.error_message,
        has_ai_analysis=bool(task.ai_analysis),
        created_at=task.created_at,
    )


def count_tasks_by_status(db: Session) -> dict[str, int]:
    """按状态统计任务数量（供接口/调试使用）。

    Args:
        db: 数据库会话。

    Returns:
        状态到数量的映射。
    """
    rows = db.query(Task.status, func.count(Task.id)).group_by(Task.status).all()
    return {str(status): int(count) for status, count in rows}
