"""定时任务调度：用 APScheduler 按 cron 表达式触发用例集执行。

设计取舍：
* 使用 ``BackgroundScheduler``（线程池）而不是 ``AsyncIOScheduler``——
  任务的真实执行体是「拉起 pytest 子进程」，本身是阻塞 IO，线程模型更直观；
* 调度器**不持久化 jobstore**，每次服务启动都从数据库重新加载用例集配置，
  保证「数据库是唯一事实来源」，避免出现「改了 cron 但调度器还是老的」这类不一致；
* 触发时创建一条正常的 ``Task``，与手工执行走完全相同的执行链路，
  这样报告、AI 分析、失败统计不需要为定时任务写第二套逻辑。
"""

from __future__ import annotations

import threading
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import SessionLocal
from app.models import TaskStatus, TestSuite, TriggerType
from app.services.test_runner import TestRunnerService, run_task
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SchedulerService:
    """用例集定时调度服务。

    Attributes:
        scheduler: APScheduler 实例。
    """

    def __init__(self) -> None:
        """初始化调度器。"""
        self.scheduler = BackgroundScheduler(
            timezone="Asia/Shanghai",
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
        )
        self._started = False

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """启动调度器并从数据库加载定时任务。

        Returns:
            None
        """
        if self._started:
            return
        self.scheduler.start()
        self._started = True
        self.reload_jobs()
        logger.info("定时调度器已启动")

    def shutdown(self, wait: bool = False) -> None:
        """关闭调度器。

        Args:
            wait: 是否等待正在运行的 job 结束。
        """
        if not self._started:
            return
        self.scheduler.shutdown(wait=wait)
        self._started = False
        logger.info("定时调度器已关闭")

    @property
    def running(self) -> bool:
        """调度器是否正在运行。"""
        return self._started

    # ------------------------------------------------------------------ #
    # 任务同步
    # ------------------------------------------------------------------ #
    def reload_jobs(self) -> int:
        """从数据库全量重建定时任务。

        Returns:
            成功注册的定时任务数量。
        """
        for job in self.scheduler.get_jobs():
            self.scheduler.remove_job(job.id)

        registered = 0
        with SessionLocal() as db:
            suites = db.query(TestSuite).filter(TestSuite.enabled.is_(True)).all()
            for suite in suites:
                if self._register(db, suite):
                    registered += 1
        logger.info("定时任务加载完成，共注册 {} 个", registered)
        return registered

    def sync_suite(self, suite_id: int) -> bool:
        """同步单个用例集的定时配置（增删改后调用）。

        Args:
            suite_id: 用例集 ID。

        Returns:
            是否处于「已注册定时任务」状态。
        """
        if not self._started:
            return False
        job_id = f"suite_{suite_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        with SessionLocal() as db:
            suite = db.get(TestSuite, suite_id)
            if suite is None or not suite.enabled or not suite.cron_expression:
                return False
            return self._register(db, suite)

    def _register(self, db: Any, suite: TestSuite) -> bool:
        """把一条用例集注册成 cron 任务。

        Args:
            db: 数据库会话。
            suite: 用例集对象。

        Returns:
            是否注册成功。
        """
        if not suite.cron_expression:
            return False
        try:
            trigger = CronTrigger.from_crontab(suite.cron_expression, timezone="Asia/Shanghai")
        except ValueError as exc:
            logger.error(
                "用例集 {} 的 cron 表达式非法（{}）: {}", suite.id, suite.cron_expression, exc
            )
            return False
        self.scheduler.add_job(
            func=trigger_suite,
            trigger=trigger,
            id=suite.job_id,
            name=f"用例集: {suite.name}",
            kwargs={"suite_id": suite.id},
            replace_existing=True,
        )
        logger.info("已注册定时任务 {} -> {}", suite.job_id, suite.cron_expression)
        return True

    def list_jobs(self) -> list[dict[str, Any]]:
        """列出当前已注册的定时任务。

        Returns:
            任务信息列表。
        """
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
            for job in self.scheduler.get_jobs()
        ]


def trigger_suite(suite_id: int) -> None:
    """定时触发一个用例集（由 APScheduler 在线程池中调用）。

    Args:
        suite_id: 用例集 ID。
    """
    logger.info("定时任务触发用例集 {}", suite_id)
    with SessionLocal() as db:
        suite = db.get(TestSuite, suite_id)
        if suite is None:
            logger.warning("用例集 {} 不存在，跳过本次调度", suite_id)
            return
        if not suite.enabled:
            logger.info("用例集 {} 已停用，跳过本次调度", suite_id)
            return
        if not suite.case_ids:
            logger.warning("用例集 {} 没有任何用例，跳过本次调度", suite_id)
            return

        service = TestRunnerService(db)
        task = service.create_task(
            case_ids=list(suite.case_ids),
            project_id=suite.project_id,
            environment_id=suite.environment_id,
            retry_times=suite.retry_times,
            trigger_type=TriggerType.SCHEDULE.value,
            suite_id=suite.id,
            name=f"定时执行 · {suite.name}",
        )
        task.status = TaskStatus.PENDING.value
        suite.last_run_at = task.created_at
        db.commit()
        task_id = task.id

    threading.Thread(
        target=run_task, args=(task_id,), name=f"atp-schedule-{suite_id}", daemon=True
    ).start()


# 全局单例：FastAPI 的 startup / shutdown 事件共用
scheduler_service = SchedulerService()
