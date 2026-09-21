"""auto-test-platform 测试引擎层。

本层是一个**不依赖任何 Web 框架**的纯 Python 库，可以：
1. 被服务层（app/）以子进程方式调度，用于平台化执行；
2. 被命令行直接使用（见根目录 run_engine.py），用于本地/CI 快速跑用例。

设计原则：引擎层只关心「怎么把一条用例跑起来」，不关心「用例从哪来」。
用例的持久化、权限、审计全部由服务层负责。
"""

from __future__ import annotations

from engine.allure_helper import attach_file, attach_json, attach_text, step
from engine.assertions import (
    AssertionEngine,
    AssertionFailure,
    AssertionResult,
    AssertionRule,
    resolve_json_path,
)
from engine.client import ApiClient, ApiResponse, render_template
from engine.data_loader import DataLoader, load_data_file, load_json, load_yaml
from engine.runner import CaseResult, CaseTelemetry, PytestRunner, RunSummary, execute_case
from engine.ui_actions import UIPlayer, UIStep, UIStepResult

__version__ = "1.0.0"

__all__ = [
    "ApiClient",
    "ApiResponse",
    "AssertionEngine",
    "AssertionFailure",
    "AssertionResult",
    "AssertionRule",
    "CaseResult",
    "CaseTelemetry",
    "DataLoader",
    "PytestRunner",
    "RunSummary",
    "UIPlayer",
    "UIStep",
    "UIStepResult",
    "__version__",
    "attach_file",
    "attach_json",
    "attach_text",
    "execute_case",
    "load_data_file",
    "load_json",
    "load_yaml",
    "render_template",
    "resolve_json_path",
    "step",
]
