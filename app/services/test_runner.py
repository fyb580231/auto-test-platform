"""测试执行服务：把「数据库里的用例」调度给「引擎层的 pytest」执行，并把结果落库。

并发模型（面试高频问题）：
* **任务级并发**：多条任务可以同时执行，由模块级线程池 + 信号量限流；
* **任务内串行**：单个任务内部用例串行执行，保证用例之间没有资源竞争，
  也保证请求/响应明细能被 conftest 的进程内收集器完整捕获；
* **进程隔离**：每个任务通过 ``subprocess`` 拉起独立 pytest 进程，
  用例代码崩溃/挂死不会拖垮 FastAPI 主进程，超时后可直接强杀。

需要「任务内并行」时，扩展点是给 pytest 加 ``-n``（pytest-xdist）；
代价是结果收集要改成走 xdist 的主从事件通道，请求/响应明细需额外回传，
所以默认关闭——这是有意的工程取舍，而不是没做。
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, now
from app.models import Environment, Project, Task, TaskStatus, TestCase, TriggerType
from app.utils.logger import get_logger
from engine.runner import PytestRunner, RunSummary

logger = get_logger(__name__)

# 任务级并发池：每个任务一个子进程，因此线程只是「调度者」，不会争抢 GIL
_EXECUTOR = ThreadPoolExecutor(
    max_workers=settings.max_concurrent_tasks, thread_name_prefix="atp-task"
)
_SEMAPHORE = threading.BoundedSemaphore(settings.max_concurrent_tasks)
# 已经在跑的任务，避免重复触发（例如用户连点两次执行按钮）
_RUNNING_TASKS: set[int] = set()
_RUNNING_LOCK = threading.Lock()


class TaskNotFoundError(LookupError):
    """任务不存在。"""


class TestRunnerService:
    """测试执行服务（请求级）。

    Attributes:
        db: 数据库会话。
    """

    def __init__(self, db: Session) -> None:
        """初始化服务。

        Args:
            db: 数据库会话。
        """
        self.db = db

    def create_task(
        self,
        *,
        case_ids: list[int],
        project_id: int | None,
        environment_id: int | None = None,
        retry_times: int | None = None,
        trigger_type: str = TriggerType.MANUAL.value,
        suite_id: int | None = None,
        name: str | None = None,
    ) -> Task:
        """创建一条执行任务记录（状态 pending，尚未执行）。

        Args:
            case_ids: 用例 ID 列表（保持顺序）。
            project_id: 所属项目。
            environment_id: 执行环境 ID。
            retry_times: 失败重跑次数。
            trigger_type: 触发来源。
            suite_id: 来源用例集 ID。
            name: 任务名称。

        Returns:
            任务 ORM 对象。
        """
        cases = self._load_cases(case_ids)
        environment = self._resolve_environment(project_id, environment_id, cases)
        task = Task(
            task_no=uuid.uuid4().hex,
            project_id=project_id,
            suite_id=suite_id,
            name=name or f"执行 {len(case_ids)} 条用例",
            trigger_type=trigger_type,
            environment_id=environment.id if environment else None,
            environment_name=environment.name if environment else "",
            case_ids=[case.id for case in cases],
            case_count=len(cases),
            status=TaskStatus.PENDING.value,
            retry_times=retry_times if retry_times is not None else settings.default_retry_times,
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        logger.info("已创建任务 {}（{} 条用例）", task.task_no, task.case_count)
        return task

    def submit(self, task_id: int) -> None:
        """把任务提交到线程池异步执行。

        Args:
            task_id: 任务 ID。
        """
        _EXECUTOR.submit(run_task, task_id)
        logger.info("任务 {} 已提交执行队列", task_id)

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #
    def _load_cases(self, case_ids: list[int]) -> list[TestCase]:
        """按 ID 加载用例并保持传入顺序。

        Args:
            case_ids: 用例 ID 列表。

        Returns:
            用例对象列表（跳过不存在的 ID）。
        """
        if not case_ids:
            return []
        found = {
            case.id: case
            for case in self.db.query(TestCase).filter(TestCase.id.in_(case_ids)).all()
        }
        return [found[cid] for cid in case_ids if cid in found]

    def _resolve_environment(
        self, project_id: int | None, environment_id: int | None, cases: list[TestCase]
    ) -> Environment | None:
        """确定本次执行使用的环境。

        优先级：显式指定 > 项目默认环境 > 项目第一个环境 > 无环境（用例里必须写绝对地址）。

        Args:
            project_id: 项目 ID。
            environment_id: 显式指定的环境 ID。
            cases: 本次执行的用例（用于推断项目）。

        Returns:
            环境对象；无法确定时返回 None。
        """
        if environment_id is not None:
            environment = self.db.get(Environment, environment_id)
            if environment is not None:
                return environment
        effective_project_id = project_id or (cases[0].project_id if cases else None)
        if effective_project_id is None:
            return None
        environments = (
            self.db.query(Environment)
            .filter(Environment.project_id == effective_project_id)
            .order_by(Environment.is_default.desc(), Environment.id.asc())
            .all()
        )
        return environments[0] if environments else None


def run_task(task_id: int) -> None:
    """在线程池中执行任务（模块级函数，避免闭包持有请求级 Session）。

    Args:
        task_id: 任务 ID。
    """
    with _RUNNING_LOCK:
        if task_id in _RUNNING_TASKS:
            logger.warning("任务 {} 正在执行中，忽略重复提交", task_id)
            return
        _RUNNING_TASKS.add(task_id)
    try:
        with _SEMAPHORE:
            TaskExecutor(task_id).run()
    except Exception as exc:
        logger.exception("任务 {} 执行异常: {}", task_id, exc)
        _mark_task_error(task_id, f"执行器异常: {exc}")
    finally:
        with _RUNNING_LOCK:
            _RUNNING_TASKS.discard(task_id)


class TaskExecutor:
    """单个任务的执行器：在独立 Session 中完成「准备 -> 执行 -> 落库 -> 出报告」。

    Attributes:
        task_id: 任务 ID。
    """

    def __init__(self, task_id: int) -> None:
        """初始化执行器。

        Args:
            task_id: 任务 ID。
        """
        self.task_id = task_id
        self.runner = PytestRunner(
            project_root=Path(__file__).resolve().parent.parent.parent,
            report_root=settings.reports_dir,
            timeout=settings.pytest_timeout_seconds,
        )

    def run(self) -> None:
        """执行任务并写回结果。

        Returns:
            None
        """
        with SessionLocal() as db:
            task = db.get(Task, self.task_id)
            if task is None:
                raise TaskNotFoundError(f"任务 {self.task_id} 不存在")

            task.status = TaskStatus.RUNNING.value
            task.started_at = now()
            db.commit()

            try:
                payloads = self._build_payloads(db, task)
                if not payloads:
                    raise ValueError("本次任务没有可执行的用例（用例可能已被删除或全部停用）")
                env_config = self._build_env_config(db, task)
                summary = self.runner.run(
                    task_id=task.task_no,
                    cases=payloads,
                    env_config=env_config,
                    retry_times=int(task.retry_times or 0),
                )
                self._apply_summary(db, task, summary)
            except Exception as exc:
                logger.exception("任务 {} 执行失败: {}", self.task_id, exc)
                task.status = TaskStatus.ERROR.value
                task.error_message = str(exc)
                task.finished_at = now()
                db.commit()

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #
    def _build_payloads(self, db: Session, task: Task) -> list[dict[str, Any]]:
        """把任务里的用例转换成引擎层载荷。

        Args:
            db: 数据库会话。
            task: 任务对象。

        Returns:
            引擎层载荷列表。
        """
        case_ids: list[int] = list(task.case_ids or [])
        cases = db.query(TestCase).filter(TestCase.id.in_(case_ids)).all()
        by_id = {case.id: case for case in cases}
        ordered = [by_id[cid] for cid in case_ids if cid in by_id]

        payloads: list[dict[str, Any]] = []
        for case in ordered:
            if not case.enabled:
                logger.info("跳过已停用用例: {} ({})", case.name, case.id)
                continue
            setup_case = db.get(TestCase, case.setup_case_id) if case.setup_case_id else None
            payloads.append(case.to_engine_payload(setup_case=setup_case))
        return payloads

    def _build_env_config(self, db: Session, task: Task) -> dict[str, Any]:
        """构造引擎层需要的环境配置。

        Args:
            db: 数据库会话。
            task: 任务对象。

        Returns:
            环境配置字典。
        """
        if task.environment_id:
            environment = db.get(Environment, task.environment_id)
            if environment is not None:
                return environment.to_runtime_config()
        return {
            "id": None,
            "name": task.environment_name or "未指定",
            "base_url": "",
            "headers": {},
            "variables": {},
            "verify": True,
            "timeout": 15,
        }

    def _apply_summary(self, db: Session, task: Task, summary: RunSummary) -> None:
        """把执行结果写回任务记录。

        Args:
            db: 数据库会话。
            task: 任务对象。
            summary: 执行结果汇总。
        """
        task.status = summary.status
        task.total = summary.total
        task.passed = summary.passed
        task.failed = summary.failed
        task.skipped = summary.skipped
        task.pass_rate = summary.pass_rate
        task.duration_ms = int(summary.duration_ms)
        task.finished_at = now()
        task.log_path = summary.log_path
        task.allure_results_dir = summary.allure_results_dir
        task.result_detail = {
            "results": [item.to_dict() for item in summary.results],
            "stdout_tail": summary.stdout_tail,
            "exit_code": summary.exit_code,
        }
        if summary.status == TaskStatus.ERROR.value:
            task.error_message = summary.stdout_tail[-1000:] or "执行器未产生结果"
        db.commit()

        report_path = self._generate_allure_report(task)
        if report_path:
            task.allure_report_path = str(report_path)
            db.commit()
        logger.info("任务 {} 结果已落库: {}", task.task_no, task.status)

    def _generate_allure_report(self, task: Task) -> Path | None:
        """调用 allure CLI 生成 HTML 报告。

        Allure 依赖 Java 运行时，并非所有环境都有。生成失败时只记日志、不影响任务状态，
        前端会回退到平台内置的报告视图。

        Args:
            task: 任务对象。

        Returns:
            报告目录路径；未生成时返回 None。
        """
        if not settings.allure_auto_generate:
            return None
        if not task.allure_results_dir or not Path(task.allure_results_dir).is_dir():
            return None
        command = self._resolve_allure_command()
        if command is None:
            logger.info("未检测到 allure 命令行，跳过 HTML 报告生成（平台内置报告视图仍可用）")
            return None

        report_dir = settings.reports_dir / "allure-report" / task.task_no
        try:
            completed = subprocess.run(
                [*command, "generate", task.allure_results_dir, "-o", str(report_dir), "--clean"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("生成 Allure 报告失败: {}", exc)
            return None
        if completed.returncode != 0:
            logger.warning(
                "allure generate 返回非零退出码 {}: {}",
                completed.returncode,
                completed.stderr[:500],
            )
            return None
        logger.info("Allure HTML 报告已生成: {}", report_dir)
        return report_dir

    @staticmethod
    def _resolve_allure_command() -> list[str] | None:
        """定位可用的 allure 命令行。

        Returns:
            命令参数前缀；找不到时返回 None。
        """
        executable = shutil.which(settings.allure_command)
        if executable:
            return [executable]
        # 兼容 Windows 上的 allure.bat 与本地解压的 allure 目录
        for candidate in (settings.allure_command, f"{settings.allure_command}.bat"):
            resolved = shutil.which(candidate)
            if resolved:
                return [resolved]
        return None


def _mark_task_error(task_id: int, message: str) -> None:
    """兜底：把任务标记为执行器错误。

    Args:
        task_id: 任务 ID。
        message: 错误信息。
    """
    try:
        with SessionLocal() as db:
            task = db.get(Task, task_id)
            if task is None:
                return
            task.status = TaskStatus.ERROR.value
            task.error_message = message
            task.finished_at = now()
            db.commit()
    except Exception as exc:  # noqa: BLE001 - 兜底路径，不能再抛异常
        logger.error("回写任务 {} 状态失败: {}", task_id, exc)


def project_statistics(db: Session, project: Project) -> dict[str, int]:
    """统计项目下的资源数量（供项目列表展示）。

    Args:
        db: 数据库会话。
        project: 项目对象。

    Returns:
        含 ``case_count`` / ``suite_count`` / ``environment_count`` 的字典。
    """
    from app.models import TestSuite

    return {
        "case_count": db.query(TestCase).filter(TestCase.project_id == project.id).count(),
        "suite_count": db.query(TestSuite).filter(TestSuite.project_id == project.id).count(),
        "environment_count": db.query(Environment)
        .filter(Environment.project_id == project.id)
        .count(),
    }
