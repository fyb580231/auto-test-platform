"""数据驱动的动态用例入口。

平台上的用例是**数据**，不是代码。服务层把用例序列化成 JSON 载荷，
本模块用 ``pytest.mark.parametrize`` 把它参数化成 N 条独立的测试项，
从而实现「零代码新增用例」——新增一条用例不需要改动任何 Python 文件。

这样做的额外好处：
* 每条用例有独立的结果、耗时、重跑次数，互不污染；
* 失败重跑、按标签筛选用例、单条重跑都只是参数问题；
* 用例的请求/响应/断言明细通过 ``engine.runner.CaseTelemetry`` 传递给 conftest。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from engine.runner import ENV_CASE_FILE, execute_case, load_case_file


def _load_cases() -> list[dict[str, Any]]:
    """从 ``ATP_CASE_FILE`` 指向的载荷文件中读出用例列表。

    Returns:
        用例载荷列表；未提供载荷时返回空列表。
    """
    file_path = os.getenv(ENV_CASE_FILE, "")
    if not file_path or not Path(file_path).is_file():
        return []
    try:
        return list(load_case_file(file_path).get("cases") or [])
    except (OSError, ValueError):  # pragma: no cover - 载荷损坏时不应让 collection 崩溃
        return []


_CASES: list[dict[str, Any]] = _load_cases()


def _case_label(case: dict[str, Any]) -> str:
    """生成可读的用例 ID，便于在 pytest 输出中快速定位。

    Args:
        case: 用例载荷。

    Returns:
        用例标签。
    """
    case_type = str(case.get("case_type") or "api").upper()
    name = str(case.get("name") or case.get("id") or "case")
    return f"[{case_type}] {name}"


@pytest.mark.parametrize("case", _CASES, ids=[_case_label(c) for c in _CASES])
def test_dynamic_case(case: dict[str, Any], env_config: dict[str, Any]) -> None:
    """执行一条由平台下发的用例。

    Args:
        case: 用例载荷。
        env_config: 环境配置 fixture。
    """
    execute_case(case, env_config)
