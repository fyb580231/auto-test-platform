"""pytest 全局配置 + 结果收集插件。

这个文件是「引擎层」和「服务层」之间的**唯一契约点**：

* 从 ``ATP_CASE_FILE`` 读入本次要执行的用例载荷；
* 通过 ``env_config`` fixture 把环境变量（base_url / 公共 Header / 变量）注入用例；
* 通过 pytest 钩子把每条用例的终态写成 ``ATP_RESULT_FILE`` 指向的 JSON，
  服务层读这个 JSON 落库、渲染报告、喂给 AI 做失败分析。

注意：本文件必须保持「零业务依赖」——它不能 import app/ 下的任何模块，
否则引擎层就无法脱离 Web 独立运行了。
"""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from engine.runner import ENV_CASE_FILE, CaseTelemetry, load_case_file

# 单次执行的结果收集器（pytest 进程级单例）
_COLLECTOR: ResultCollector | None = None
_PAYLOAD: dict[str, Any] | None = None


def _load_payload() -> dict[str, Any]:
    """读取本次执行的用例载荷（带进程内缓存）。

    Returns:
        载荷字典；文件缺失时返回空载荷。
    """
    global _PAYLOAD
    if _PAYLOAD is None:
        file_path = os.getenv(ENV_CASE_FILE, "")
        if file_path and Path(file_path).is_file():
            _PAYLOAD = load_case_file(file_path)
        else:
            _PAYLOAD = {"task_id": "", "env": {}, "cases": []}
    return _PAYLOAD


@pytest.fixture(scope="session")
def env_config() -> dict[str, Any]:
    """环境配置 fixture：base_url / 公共 Header / 全局变量。

    Returns:
        环境配置字典。
    """
    return _load_payload().get("env") or {}


@pytest.fixture(scope="session")
def task_id() -> str:
    """本次执行的任务 ID。

    Returns:
        任务 ID 字符串。
    """
    return str(_load_payload().get("task_id") or "")


class ResultCollector:
    """把 pytest 报告转换成平台可消费的结构化结果。

    Attributes:
        results: ``case_id -> 结果字典`` 的映射，保持用例定义顺序。
    """

    def __init__(self) -> None:
        """初始化收集器。"""
        self.results: dict[str, dict[str, Any]] = {}
        # 记录每条用例出现过的 call 阶段报告次数，用于计算失败重跑次数
        self.call_attempts: dict[str, int] = {}

    def mark_call_attempt(self, case_id: str) -> int:
        """累加并返回某条用例的 call 阶段尝试次数。

        Args:
            case_id: 用例 ID。

        Returns:
            累计尝试次数（首次调用返回 1）。
        """
        self.call_attempts[case_id] = self.call_attempts.get(case_id, 0) + 1
        return self.call_attempts[case_id]

    def ensure(self, case_id: str, case_name: str, case_type: str) -> dict[str, Any]:
        """获取（或初始化）某条用例的结果槽位。

        Args:
            case_id: 用例 ID。
            case_name: 用例名称。
            case_type: 用例类型。

        Returns:
            结果字典。
        """
        return self.results.setdefault(
            case_id,
            {
                "case_id": case_id,
                "case_name": case_name,
                "case_type": case_type,
                "status": "error",
                "duration_ms": 0.0,
                "message": "",
                "traceback": "",
                "request": None,
                "response": None,
                "assertions": [],
                "screenshots": [],
                "steps": [],
                "reruns": 0,
            },
        )

    def merge_telemetry(self, case_id: str) -> None:
        """把引擎层记录的遥测数据合并进结果。

        Args:
            case_id: 用例 ID。
        """
        telemetry = CaseTelemetry.pop(case_id)
        if not telemetry:
            return
        slot = self.results.get(case_id)
        if slot is None:
            return
        for key in ("request", "response", "assertions", "screenshots", "steps", "case_type"):
            value = telemetry.get(key)
            if value not in (None, [], ""):
                slot[key] = value

    def as_payload(self) -> dict[str, Any]:
        """导出为可写入文件的字典。

        Returns:
            含 ``results`` 列表的字典。
        """
        ordered = list(self.results.values())
        for slot in ordered:
            slot["duration_ms"] = round(float(slot.get("duration_ms") or 0), 2)
        return {"task_id": _load_payload().get("task_id", ""), "results": ordered}


def pytest_configure(config: pytest.Config) -> None:
    """pytest 启动时初始化结果收集器。

    Args:
        config: pytest 配置对象（未使用，仅为满足钩子签名）。
    """
    global _COLLECTOR
    _COLLECTOR = ResultCollector()
    _ = config


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """整个会话结束时把结果刷到磁盘。

    Args:
        session: pytest 会话对象（未使用）。
        exitstatus: pytest 退出码（未使用）。
    """
    _ = (session, exitstatus)
    if _COLLECTOR is None:
        return
    result_file = os.getenv("ATP_RESULT_FILE", "")
    if not result_file:
        return
    path = Path(result_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_COLLECTOR.as_payload(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo
) -> Generator[None, Any, None]:
    """拦截每条用例的 setup/call/teardown 报告并记录终态。

    Args:
        item: 当前测试项。
        call: 调用阶段信息。

    Yields:
        交给 pytest 继续处理钩子链。
    """
    outcome = yield
    report = outcome.get_result() if hasattr(outcome, "get_result") else outcome
    if _COLLECTOR is None or report is None:
        return

    case = _extract_case(item)
    if case is None:
        return

    case_id = str(case.get("id") or case.get("name") or item.name)
    case_name = str(case.get("name") or case_id)
    case_type = str(case.get("case_type") or "api").lower()
    slot = _COLLECTOR.ensure(case_id, case_name, case_type)

    # pytest-rerunfailures 会把中间失败的 outcome 标成 "rerun"。不同版本行为不一致
    # （有的版本在 makereport 阶段就改了 outcome，有的只在 logreport 阶段改），
    # 因此这里用「call 阶段报告出现的次数」来数重跑次数，做到与插件版本无关。
    if getattr(report, "outcome", "") == "rerun" or getattr(report, "rerun", False):
        if report.when == "call":
            _COLLECTOR.mark_call_attempt(case_id)
        return

    if report.when == "call":
        attempts = _COLLECTOR.mark_call_attempt(case_id)
        slot["reruns"] = max(0, attempts - 1)
        slot["status"] = {"passed": "passed", "failed": "failed", "skipped": "skipped"}.get(
            report.outcome, "error"
        )
        slot["duration_ms"] = float(getattr(report, "duration", 0.0)) * 1000
        if report.outcome != "passed":
            slot["message"] = _short_message(report)
            slot["traceback"] = str(report.longrepr or "")
        _COLLECTOR.merge_telemetry(case_id)
    elif report.when == "setup" and report.outcome == "failed":
        slot["status"] = "error"
        slot["message"] = _short_message(report)
        slot["traceback"] = str(report.longrepr or "")
    elif report.when == "teardown" and report.outcome == "failed":
        if slot.get("status") == "passed":
            slot["status"] = "error"
        slot["message"] = slot.get("message") or _short_message(report)
        slot["traceback"] = slot.get("traceback") or str(report.longrepr or "")
    elif report.when == "setup" and report.outcome == "skipped":
        slot["status"] = "skipped"
        slot["message"] = str(report.longrepr or "已跳过")


def _extract_case(item: pytest.Item) -> dict[str, Any] | None:
    """从测试项中取回该条用例的载荷。

    Args:
        item: pytest 测试项。

    Returns:
        用例字典；取不到时返回 None。
    """
    callspec = getattr(item, "callspec", None)
    if callspec is None:
        return None
    case = callspec.params.get("case")
    return case if isinstance(case, dict) else None


def _short_message(report: Any) -> str:
    """从 pytest 报告中提取一行失败摘要。

    Args:
        report: pytest 报告对象。

    Returns:
        单行摘要字符串。
    """
    text = str(getattr(report, "longrepr", "") or "").strip()
    if not text:
        return "用例执行失败"
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped and not stripped.startswith(("E ", ">", "|")):
            continue
        if stripped:
            return stripped
    return text.splitlines()[-1].strip()[:500]
