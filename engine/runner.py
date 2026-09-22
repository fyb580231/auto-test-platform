"""pytest 执行器：用例编排、进程隔离执行、结果收集。

整体链路::

    服务层把「数据库里的用例」序列化成一份 JSON 载荷
        -> PytestRunner 以**子进程**方式拉起 pytest
        -> testcases/test_dynamic_cases.py 把载荷参数化成 N 条用例
        -> execute_case() 逐条执行（httpx / Playwright + 断言引擎）
        -> conftest.py 里的插件把结果写成 JSON + Allure 结果
        -> 服务层读回 JSON，落库、渲染报告、必要时喂给 AI 做失败分析

为什么用**子进程**而不是在 FastAPI 进程里 `pytest.main()`：
1. 用例代码可能崩溃（段错误、Playwright 挂死），子进程隔离后 Web 服务不受影响；
2. 可以精确控制超时并在超时后强杀；
3. GIL 争抢消失，后续接入 `pytest-xdist` 并行只需改一行参数。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from loguru import logger

from engine.allure_helper import attach_json, attach_screenshot, step
from engine.assertions import AssertionEngine, AssertionFailure
from engine.client import ApiClient, ApiResponse, render_template
from engine.ui_actions import UIPlayer, UIStep

# 运行时环境变量约定（服务层与 conftest.py 共享）
ENV_CASE_FILE = "ATP_CASE_FILE"
ENV_RESULT_FILE = "ATP_RESULT_FILE"
ENV_SCREENSHOT_DIR = "ATP_SCREENSHOT_DIR"
ENV_TASK_ID = "ATP_TASK_ID"
ENV_UI_HEADLESS = "ATP_UI_HEADLESS"
ENV_UI_BROWSER = "ATP_UI_BROWSER"

# pytest 退出码语义
EXIT_OK = 0
EXIT_TESTS_FAILED = 1
EXIT_INTERRUPTED = 2
EXIT_INTERNAL_ERROR = 3
EXIT_USAGE_ERROR = 4
EXIT_NO_TESTS = 5

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"


class CaseTelemetry:
    """单条用例执行期的结构化遥测数据（请求 / 响应 / 断言 / 截图 / 步骤）。

    引擎层执行用例时把可观测信息塞进这里，`testcases/conftest.py` 中的
    pytest 插件再把它们取出来写进结果文件。这样「执行」与「报告」解耦：
    conftest 不需要知道用例是怎么跑的，只需要知道去哪儿取数据。
    """

    _store: ClassVar[dict[str, dict[str, Any]]] = {}

    @classmethod
    def record(cls, case_id: str, payload: dict[str, Any]) -> None:
        """写入一条用例的遥测数据。

        Args:
            case_id: 用例 ID。
            payload: 遥测内容。
        """
        cls._store[case_id] = payload

    @classmethod
    def pop(cls, case_id: str) -> dict[str, Any]:
        """取出并清除一条用例的遥测数据。

        Args:
            case_id: 用例 ID。

        Returns:
            遥测内容；不存在时返回空字典。
        """
        return cls._store.pop(case_id, {})

    @classmethod
    def clear(cls) -> None:
        """清空全部遥测数据（每个 pytest 进程只跑一批，用于兜底清理）。"""
        cls._store.clear()


def load_case_file(file_path: str | Path) -> dict[str, Any]:
    """读取执行载荷。

    Args:
        file_path: 载荷 JSON 路径。

    Returns:
        形如 ``{"task_id": str, "env": dict, "cases": list}`` 的字典。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 文件内容不是合法 JSON 对象。
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"用例载荷文件不存在: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"用例载荷必须是 JSON 对象: {path}")
    payload.setdefault("cases", [])
    payload.setdefault("env", {})
    return payload


def normalize_case(raw: dict[str, Any]) -> dict[str, Any]:
    """把用例统一成引擎内部的嵌套载荷结构。

    平台上的用例有两种来源，形状不同：

    1. **平台导出（嵌套写法）**：``{"request": {"method": ..., "url": ...}}``，
       由 ``TestCase.to_engine_payload`` 生成；
    2. **手写 YAML/JSON（扁平写法）**：``{"method": "GET", "url": "/get"}``，
       人写文件时更自然。

    本函数把第 2 种补全成第 1 种，保证同一条用例在「平台执行」与「命令行执行」
    两条链路上行为完全一致——这也是引擎层可独立使用的必要前提。

    Args:
        raw: 原始用例字典。

    Returns:
        归一化后的用例字典（新对象，不修改入参）。
    """
    case = dict(raw)
    case.setdefault("case_type", "api")

    if "request" not in case:
        case["request"] = {
            "method": str(case.get("method") or "GET").upper(),
            "url": case.get("url") or "",
            "headers": case.get("headers") or {},
            "params": case.get("params") or {},
            "body": case.get("body"),
            "form": case.get("form") or {},
            "timeout": case.get("timeout"),
            "retries": int(case.get("retries", 2)),
            "retry_on_status": bool(case.get("retry_on_status", False)),
            "base_url": case.get("base_url"),
        }

    setup_case = case.get("setup_case")
    if isinstance(setup_case, dict) and setup_case and "request" not in setup_case:
        setup = dict(setup_case)
        setup["request"] = {
            "method": str(setup.get("method") or "GET").upper(),
            "url": setup.get("url") or "",
            "headers": setup.get("headers") or {},
            "params": setup.get("params") or {},
            "body": setup.get("body"),
            "form": setup.get("form") or {},
            "timeout": setup.get("timeout"),
        }
        # 扁平写法下 extract 通常写在主用例上，这里回填给前置用例
        setup.setdefault("extract", case.get("extract") or [])
        case["setup_case"] = setup

    return case


def execute_case(case: dict[str, Any], env_config: dict[str, Any] | None = None) -> None:
    """执行一条用例（由 testcases/test_dynamic_cases.py 调用）。

    Args:
        case: 归一化后的用例载荷。
        env_config: 环境配置（base_url / headers / variables）。

    Raises:
        AssertionError: 断言未通过或 UI 步骤失败。
        RuntimeError: 请求异常等执行期错误。
    """
    case = normalize_case(case)
    env = env_config or {}
    case_id = str(case.get("id") or case.get("name") or "unknown")
    case_name = str(case.get("name") or case_id)
    case_type = str(case.get("case_type") or "api").lower()

    telemetry: dict[str, Any] = {
        "case_id": case_id,
        "case_name": case_name,
        "case_type": case_type,
        "request": None,
        "response": None,
        "assertions": [],
        "screenshots": [],
        "steps": [],
        "setup_result": None,
    }

    # 用 try/finally 保证「失败用例的遥测数据也能落盘」——
    # 断言失败会抛异常，如果只在函数末尾记录，报告页就看不到失败用例的
    # 请求/响应/断言明细，而这恰恰是排查问题最需要的信息。
    try:
        if case_type == "ui":
            _execute_ui_case(case, env, telemetry)
        else:
            _execute_api_case(case, env, telemetry)
    finally:
        CaseTelemetry.record(case_id, telemetry)


# ---------------------------------------------------------------------------- #
# 接口用例
# ---------------------------------------------------------------------------- #
def _execute_api_case(case: dict[str, Any], env: dict[str, Any], telemetry: dict[str, Any]) -> None:
    """执行接口用例：前置用例 -> 主请求 -> 断言。

    Args:
        case: 用例载荷。
        env: 环境配置。
        telemetry: 遥测容器（会被就地修改）。

    Raises:
        AssertionError: 断言失败。
    """
    request_cfg: dict[str, Any] = dict(case.get("request") or {})
    variables: dict[str, Any] = {**(env.get("variables") or {}), **(case.get("variables") or {})}
    base_url = str(request_cfg.get("base_url") or env.get("base_url") or "")
    client = ApiClient(
        base_url=base_url,
        default_headers=dict(env.get("headers") or {}),
        timeout=float(request_cfg.get("timeout") or env.get("timeout") or 15),
        retries=int(request_cfg.get("retries", 2)),
        verify=bool(env.get("verify", True)),
    )

    # ---------- 1. 前置用例：用于登录拿 Token、造数据等场景 ----------
    setup_case = case.get("setup_case")
    if isinstance(setup_case, dict) and setup_case:
        with step("前置用例: " + str(setup_case.get("name", "setup"))):
            setup_cfg: dict[str, Any] = dict(setup_case.get("request") or {})
            setup_response = client.request(
                method=str(setup_cfg.get("method", "GET")),
                url=str(setup_cfg.get("url", "")),
                params=setup_cfg.get("params"),
                headers=setup_cfg.get("headers"),
                json_body=setup_cfg.get("body"),
                variables=variables,
                timeout=setup_cfg.get("timeout"),
            )
            telemetry["setup_result"] = {
                "name": setup_case.get("name"),
                "request": setup_response.request,
                "response": setup_response.to_dict(),
            }
            attach_json("前置用例请求", setup_response.request)
            attach_json("前置用例响应", setup_response.to_dict())
            if not setup_response.ok:
                raise AssertionError(
                    f"前置用例执行失败: {setup_case.get('name')} 返回 {setup_response.status_code}"
                )
            _extract_variables(setup_case, setup_response, variables)

    # ---------- 2. 主请求 ----------
    method = str(request_cfg.get("method", "GET")).upper()
    url = str(request_cfg.get("url", ""))
    with step(f"发送请求 {method} {url}"):
        response = client.request(
            method=method,
            url=url,
            params=request_cfg.get("params"),
            headers=request_cfg.get("headers"),
            json_body=request_cfg.get("body"),
            data=request_cfg.get("form"),
            variables=variables,
            timeout=request_cfg.get("timeout"),
            retry_on_status=bool(request_cfg.get("retry_on_status", False)),
        )

    telemetry["request"] = response.request
    telemetry["response"] = response.to_dict()
    attach_json("请求", response.request)
    attach_json("响应", response.to_dict())

    # ---------- 3. 断言 ----------
    # 断言里的期望值同样要支持 {{变量}}：例如断言 "{{test_username}}" 回显正确
    raw_rules = render_template(case.get("assertions") or [], variables)
    rules = AssertionEngine.parse_rules(raw_rules)
    with step("执行断言"):
        try:
            results = AssertionEngine.verify(response, rules)
        except AssertionFailure as exc:
            telemetry["assertions"] = [r.to_dict() for r in exc.results]
            attach_json("断言结果", telemetry["assertions"])
            raise
    telemetry["assertions"] = [r.to_dict() for r in results]


def _extract_variables(
    setup_case: dict[str, Any], response: ApiResponse, variables: dict[str, Any]
) -> None:
    """从前置用例响应中提取变量，供主用例通过 ``{{变量}}`` 引用。

    Args:
        setup_case: 前置用例配置，``extract`` 形如
            ``[{"name": "token", "path": "$.data.token"}]``。
        response: 前置用例响应。
        variables: 变量字典（会被就地修改）。
    """
    from engine.assertions import resolve_json_path  # 局部导入避免循环引用

    for rule in setup_case.get("extract") or []:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or "").strip()
        if not name:
            continue
        value = resolve_json_path(str(rule.get("path") or ""), response.body)
        if value is None:
            logger.warning("前置用例变量提取失败: {} <- {}", name, rule.get("path"))
            continue
        variables[name] = value
        logger.info("已提取变量 {} = {}", name, "***" if _is_sensitive_name(name) else value)


def _is_sensitive_name(name: str) -> bool:
    """判断变量名是否敏感（日志中需要脱敏）。

    Args:
        name: 变量名。

    Returns:
        是否敏感。
    """
    lowered = name.lower()
    return any(key in lowered for key in ("token", "secret", "password", "key"))


# ---------------------------------------------------------------------------- #
# UI 用例
# ---------------------------------------------------------------------------- #
def _execute_ui_case(case: dict[str, Any], env: dict[str, Any], telemetry: dict[str, Any]) -> None:
    """执行 UI 用例：Playwright 步骤编排，失败自动截图。

    Args:
        case: 用例载荷。
        env: 环境配置。
        telemetry: 遥测容器（会被就地修改）。

    Raises:
        AssertionError: 某一步骤失败。
    """
    raw_steps = case.get("steps") or []
    steps = [UIStep.from_dict(s) for s in raw_steps if isinstance(s, dict)]
    if not steps:
        raise AssertionError("UI 用例未配置任何步骤")

    # UI 步骤同样支持 {{变量}} 占位符，与环境变量共用同一套渲染逻辑
    ui_variables: dict[str, Any] = {**(env.get("variables") or {}), **(case.get("variables") or {})}
    for step_obj in steps:
        rendered_step = render_template(
            {"selector": step_obj.selector, "value": step_obj.value}, ui_variables
        )
        step_obj.selector = rendered_step.get("selector")
        step_obj.value = rendered_step.get("value")

    base_url = str(case.get("base_url") or env.get("base_url") or "")
    headless = os.getenv(ENV_UI_HEADLESS, "true").lower() != "false"
    task_id = os.getenv(ENV_TASK_ID, "manual")
    screenshot_dir = Path(os.getenv(ENV_SCREENSHOT_DIR, "reports/screenshots")) / task_id

    player = UIPlayer(
        base_url=base_url,
        headless=headless,
        screenshot_dir=screenshot_dir,
        browser_type=os.getenv(ENV_UI_BROWSER, "chromium"),
    )
    try:
        player.start()
        try:
            results = player.run_steps(steps, case_name=str(case.get("name") or "ui_case"))
        except AssertionError:
            telemetry["steps"] = [r.to_dict() for r in player.step_results]
            telemetry["screenshots"] = [s for r in player.step_results for s in r.screenshots]
            for shot in telemetry["screenshots"]:
                attach_screenshot(f"失败截图 {Path(shot).name}", shot)
            raise
        telemetry["steps"] = [r.to_dict() for r in results]
        telemetry["assertions"] = [
            {
                "label": item.label,
                "type": "ui_step",
                "expected": "通过",
                "actual": "通过" if item.passed else "失败",
                "passed": item.passed,
                "message": item.message,
            }
            for item in results
        ]
    finally:
        player.close()


# ---------------------------------------------------------------------------- #
# 结果对象
# ---------------------------------------------------------------------------- #
@dataclass(slots=True)
class CaseResult:
    """单条用例的执行结果。

    Attributes:
        case_id: 用例 ID。
        case_name: 用例名称。
        case_type: 用例类型（api / ui）。
        status: 终态（passed / failed / error / skipped）。
        duration_ms: 耗时毫秒。
        message: 失败摘要。
        traceback: 完整堆栈。
        request: 请求快照。
        response: 响应快照。
        assertions: 断言明细。
        screenshots: 截图路径。
        steps: UI 步骤明细。
        reruns: 重跑次数。
    """

    case_id: str
    case_name: str
    case_type: str = "api"
    status: str = STATUS_FAILED
    duration_ms: float = 0.0
    message: str = ""
    traceback: str = ""
    request: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    assertions: list[dict[str, Any]] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    reruns: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。

        Returns:
            字典结构。
        """
        return {
            "case_id": self.case_id,
            "case_name": self.case_name,
            "case_type": self.case_type,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
            "message": self.message,
            "traceback": self.traceback,
            "request": self.request,
            "response": self.response,
            "assertions": self.assertions,
            "screenshots": self.screenshots,
            "steps": self.steps,
            "reruns": self.reruns,
        }


@dataclass(slots=True)
class RunSummary:
    """一次执行的整体结果。

    Attributes:
        task_id: 任务 ID。
        status: 任务终态（success / failed / error）。
        total: 用例总数。
        passed: 通过数。
        failed: 失败数。
        skipped: 跳过数。
        duration_ms: 总耗时毫秒。
        exit_code: pytest 退出码。
        results: 每条用例的明细。
        log_path: 控制台日志文件路径。
        allure_results_dir: Allure 结果目录。
        stdout_tail: 控制台输出尾部（失败排查用）。
    """

    task_id: str
    status: str = STATUS_ERROR
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_ms: float = 0.0
    exit_code: int = EXIT_INTERNAL_ERROR
    results: list[CaseResult] = field(default_factory=list)
    log_path: str = ""
    allure_results_dir: str = ""
    stdout_tail: str = ""

    @property
    def pass_rate(self) -> float:
        """通过率（0-100，保留两位小数）。"""
        if self.total == 0:
            return 0.0
        return round(self.passed / self.total * 100, 2)

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。

        Returns:
            字典结构。
        """
        return {
            "task_id": self.task_id,
            "status": self.status,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "pass_rate": self.pass_rate,
            "duration_ms": round(self.duration_ms, 2),
            "exit_code": self.exit_code,
            "log_path": self.log_path,
            "allure_results_dir": self.allure_results_dir,
            "results": [r.to_dict() for r in self.results],
        }


class PytestRunner:
    """pytest 执行器：把一批用例载荷跑成一份结构化结果。

    Attributes:
        project_root: 项目根目录（用于定位 testcases/ 与拼 PYTHONPATH）。
        report_root: 报告根目录（Allure 结果、日志、截图）。
        timeout: 整体超时秒数。
    """

    def __init__(
        self,
        project_root: str | Path,
        report_root: str | Path = "reports",
        timeout: int = 600,
    ) -> None:
        """初始化执行器。

        Args:
            project_root: 项目根目录。
            report_root: 报告产物根目录。
            timeout: 单次执行的整体超时秒数。
        """
        self.project_root = Path(project_root).resolve()
        self.report_root = Path(report_root)
        if not self.report_root.is_absolute():
            self.report_root = (self.project_root / self.report_root).resolve()
        self.timeout = int(timeout)
        self.generated_dir = self.report_root / "generated"
        self.logs_dir = self.report_root / "logs"
        self.screenshots_dir = self.report_root / "screenshots"
        self.allure_root = self.report_root / "allure-results"

    def run(
        self,
        task_id: str,
        cases: list[dict[str, Any]],
        env_config: dict[str, Any] | None = None,
        retry_times: int = 0,
        extra_args: list[str] | None = None,
    ) -> RunSummary:
        """执行一批用例。

        Args:
            task_id: 任务 ID（同时作为产物目录名）。
            cases: 归一化后的用例载荷列表。
            env_config: 环境配置。
            retry_times: 失败重跑次数。
            extra_args: 透传给 pytest 的额外参数。

        Returns:
            执行结果汇总。
        """
        started = time.perf_counter()
        self._prepare_dirs(task_id)

        case_file = self.generated_dir / f"cases_{task_id}.json"
        result_file = self.generated_dir / f"result_{task_id}.json"
        allure_dir = self.allure_root / task_id
        allure_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.logs_dir / f"task_{task_id}.log"

        case_file.write_text(
            json.dumps(
                {"task_id": task_id, "env": env_config or {}, "cases": cases},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        command = self._build_command(allure_dir, retry_times, extra_args)
        logger.info("开始执行任务 {}，用例数 {}，命令: {}", task_id, len(cases), " ".join(command))

        exit_code, stdout_text, timed_out = self._invoke(command, task_id, result_file, log_path)
        duration_ms = (time.perf_counter() - started) * 1000

        summary = self._collect(
            task_id=task_id,
            cases=cases,
            result_file=result_file,
            exit_code=exit_code,
            duration_ms=duration_ms,
            log_path=log_path,
            allure_dir=allure_dir,
            stdout_text=stdout_text,
            timed_out=timed_out,
        )
        logger.info(
            "任务 {} 执行完成: status={} 通过={}/{} 耗时={:.0f}ms",
            task_id,
            summary.status,
            summary.passed,
            summary.total,
            summary.duration_ms,
        )
        return summary

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #
    def _prepare_dirs(self, task_id: str) -> None:
        """创建本次执行所需的目录。

        Args:
            task_id: 任务 ID。
        """
        for directory in (
            self.generated_dir,
            self.logs_dir,
            self.screenshots_dir / task_id,
            self.allure_root / task_id,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def _build_command(
        self,
        allure_dir: Path,
        retry_times: int,
        extra_args: list[str] | None,
    ) -> list[str]:
        """构造 pytest 命令行。

        Args:
            allure_dir: Allure 结果目录。
            retry_times: 重跑次数。
            extra_args: 额外参数。

        Returns:
            命令参数列表。
        """
        target = self.project_root / "testcases" / "test_dynamic_cases.py"
        command = [
            sys.executable,
            "-m",
            "pytest",
            str(target),
            "-p",
            "no:cacheprovider",
            "-v",
            f"--alluredir={allure_dir}",
            "--clean-alluredir",
        ]
        if retry_times > 0:
            command.extend([f"--reruns={retry_times}", "--reruns-delay=1"])
        command.extend(extra_args or [])
        return command

    def _invoke(
        self, command: list[str], task_id: str, result_file: Path, log_path: Path
    ) -> tuple[int, str, bool]:
        """拉起子进程执行 pytest。

        Args:
            command: 命令列表。
            task_id: 任务 ID。
            result_file: 结果文件路径。
            log_path: 日志文件路径。

        Returns:
            ``(退出码, 控制台输出, 是否超时)`` 三元组。
        """
        env = os.environ.copy()
        env.update(
            {
                ENV_CASE_FILE: str(self.generated_dir / f"cases_{task_id}.json"),
                ENV_RESULT_FILE: str(result_file),
                ENV_TASK_ID: task_id,
                ENV_SCREENSHOT_DIR: str(self.screenshots_dir),
                "PYTHONPATH": f"{self.project_root}{os.pathsep}{env.get('PYTHONPATH', '')}",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        timed_out = False
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.project_root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
            exit_code, output = completed.returncode, (completed.stdout or "") + (
                completed.stderr or ""
            )
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = EXIT_INTERNAL_ERROR
            output = (
                (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            ) + f"\n[执行器] 任务 {task_id} 超过 {self.timeout}s 超时，已被强制终止。\n"

        try:
            log_path.write_text(output, encoding="utf-8")
        except OSError as exc:  # pragma: no cover - 磁盘异常
            logger.warning("写入执行日志失败: {}", exc)
        return exit_code, output, timed_out

    def _collect(
        self,
        *,
        task_id: str,
        cases: list[dict[str, Any]],
        result_file: Path,
        exit_code: int,
        duration_ms: float,
        log_path: Path,
        allure_dir: Path,
        stdout_text: str,
        timed_out: bool,
    ) -> RunSummary:
        """汇总执行结果。

        Args:
            task_id: 任务 ID。
            cases: 用例载荷列表。
            result_file: 结果文件。
            exit_code: pytest 退出码。
            duration_ms: 总耗时。
            log_path: 日志路径。
            allure_dir: Allure 结果目录。
            stdout_text: 控制台输出。
            timed_out: 是否超时。

        Returns:
            执行结果汇总。
        """
        raw_results: list[CaseTelemetry] = []
        payload: dict[str, Any] = {}
        if result_file.is_file():
            try:
                payload = json.loads(result_file.read_text(encoding="utf-8"))
                raw_results = payload.get("results", [])  # type: ignore[assignment]
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("解析结果文件失败: {}", exc)

        case_index = {str(c.get("id")): c for c in cases}
        results: list[CaseResult] = []
        for item in raw_results:
            case_id = str(item.get("case_id", ""))
            source = case_index.get(case_id, {})
            results.append(
                CaseResult(
                    case_id=case_id,
                    case_name=str(item.get("case_name") or source.get("name") or case_id),
                    case_type=str(item.get("case_type") or source.get("case_type") or "api"),
                    status=str(item.get("status") or STATUS_ERROR),
                    duration_ms=float(item.get("duration_ms") or 0),
                    message=str(item.get("message") or ""),
                    traceback=str(item.get("traceback") or ""),
                    request=item.get("request"),
                    response=item.get("response"),
                    assertions=list(item.get("assertions") or []),
                    screenshots=list(item.get("screenshots") or []),
                    steps=list(item.get("steps") or []),
                    reruns=int(item.get("reruns") or 0),
                )
            )

        # 结果文件缺失（例如 collection error / 进程崩溃）时，用载荷兜底，保证前端能看到每条用例
        if not results and cases:
            reason = (
                "执行器超时被终止" if timed_out else f"pytest 退出码 {exit_code}，未产生结果文件"
            )
            results = [
                CaseResult(
                    case_id=str(c.get("id", "")),
                    case_name=str(c.get("name", "")),
                    case_type=str(c.get("case_type", "api")),
                    status=STATUS_ERROR,
                    message=reason,
                    traceback=_extract_traceback(stdout_text),
                )
                for c in cases
            ]

        passed = sum(1 for r in results if r.status == STATUS_PASSED)
        failed = sum(1 for r in results if r.status in {STATUS_FAILED, STATUS_ERROR})
        skipped = sum(1 for r in results if r.status == STATUS_SKIPPED)

        if timed_out or not results:
            status = "error"
        elif failed == 0 and exit_code in {EXIT_OK, EXIT_NO_TESTS}:
            status = "success"
        elif failed == 0 and passed > 0:
            # pytest 退出码异常但用例全绿（例如 xdist/插件告警），以用例结果为准
            status = "success"
        else:
            status = "failed"

        summary = RunSummary(
            task_id=task_id,
            status=status,
            total=len(results),
            passed=passed,
            failed=failed,
            skipped=skipped,
            duration_ms=duration_ms,
            exit_code=exit_code,
            results=results,
            log_path=str(log_path),
            allure_results_dir=str(allure_dir),
            stdout_tail=stdout_text[-4000:],
        )
        attach_json("执行汇总", summary.to_dict() | {"results": f"{len(results)} 条"})
        return summary


def _extract_traceback(stdout_text: str, max_chars: int = 3000) -> str:
    """从 pytest 控制台输出中截取有用的错误片段。

    Args:
        stdout_text: 控制台输出。
        max_chars: 最大保留字符数。

    Returns:
        截取后的文本。
    """
    if not stdout_text:
        return ""
    marker = "ERRORS" if "ERRORS" in stdout_text else "FAILURES"
    index = stdout_text.find(marker)
    snippet = stdout_text[index:] if index >= 0 else stdout_text
    return snippet[:max_chars]


__all__ = [
    "CaseResult",
    "CaseTelemetry",
    "PytestRunner",
    "RunSummary",
    "execute_case",
    "load_case_file",
]
