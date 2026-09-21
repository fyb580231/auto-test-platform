"""引擎层独立命令行入口。

这是「引擎层可以脱离 Web 独立使用」的证明：不启动 FastAPI、不连数据库，
直接用 pytest 跑 YAML/JSON 里的用例，适合本地调试和接进任意 CI。

用法示例::

    # 跑全部用例
    python run_engine.py --file data/demo_api_cases.yaml

    # 只跑冒烟标签
    python run_engine.py --file data/demo_api_cases.yaml --tags smoke

    # 只跑 UI 用例、失败重跑 1 次、并生成 Allure 结果
    python run_engine.py --file data/demo_ui_cases.yaml --type ui --retry 1 --allure

    # 覆盖环境地址（不修改用例文件）
    python run_engine.py --file data/demo_api_cases.yaml --var base_url=https://httpbin.org
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from typing import Any

# 保证从任意工作目录执行都能 import 到 engine 包
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.data_loader import DataLoader, DataLoadError  # noqa: E402
from engine.runner import PytestRunner, RunSummary  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。

    Returns:
        参数解析器。
    """
    parser = argparse.ArgumentParser(
        prog="run_engine.py",
        description="auto-test-platform 引擎层命令行：不启动 Web 服务，直接跑用例文件。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--file",
        required=True,
        help="用例文件路径（YAML 或 JSON），例如 data/demo_api_cases.yaml",
    )
    parser.add_argument(
        "--tags",
        default="",
        help="按标签过滤用例，多个标签用英文逗号分隔（任一命中即执行），例如 smoke,critical",
    )
    parser.add_argument(
        "--type",
        dest="case_type",
        choices=["api", "ui"],
        default=None,
        help="只执行指定类型的用例",
    )
    parser.add_argument("--retry", type=int, default=0, help="失败重跑次数，默认 0")
    parser.add_argument("--timeout", type=int, default=600, help="整体执行超时秒数，默认 600")
    parser.add_argument(
        "--allure", action="store_true", help="额外生成 Allure 结果（需安装 allure-pytest）"
    )
    parser.add_argument(
        "--var",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="覆盖环境变量，可重复指定，例如 --var base_url=https://httpbin.org",
    )
    parser.add_argument(
        "--json", action="store_true", help="以 JSON 形式输出汇总结果（便于 CI 消费）"
    )
    parser.add_argument("--report-dir", default="reports", help="报告产物目录，默认 reports")
    return parser


def parse_variables(items: list[str]) -> dict[str, str]:
    """解析 ``--var KEY=VALUE`` 参数。

    Args:
        items: 原始参数列表。

    Returns:
        变量字典。

    Raises:
        SystemExit: 参数格式不合法。
    """
    variables: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"--var 参数格式错误: {item!r}，应为 KEY=VALUE")
        key, _, value = item.partition("=")
        variables[key.strip()] = value
    return variables


def resolve_setup_refs(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把用例里的 ``setup_ref``（引用同文件另一条用例的逻辑 ID）展开成内联前置用例。

    平台数据库模式下前置用例由外键关联；独立命令行模式下没有数据库，
    因此这里在内存里做一次引用解析，让同一份 YAML 两种模式都能跑。

    Args:
        cases: 原始用例列表。

    Returns:
        展开后的用例列表。
    """
    by_id = {str(case.get("id")): case for case in cases if case.get("id")}
    resolved: list[dict[str, Any]] = []
    for case in cases:
        clone = dict(case)
        ref = clone.pop("setup_ref", None)
        if ref:
            target = by_id.get(str(ref))
            if target is None:
                raise SystemExit(f"用例 {clone.get('id')} 的 setup_ref 指向不存在的用例: {ref}")
            clone["setup_case"] = {
                "name": target.get("name"),
                "request": {
                    "method": str(target.get("method") or "GET").upper(),
                    "url": target.get("url") or "",
                    "headers": target.get("headers") or {},
                    "params": target.get("params") or {},
                    "body": target.get("body"),
                },
                "extract": clone.get("extract") or [],
            }
        resolved.append(clone)
    return resolved


def print_summary(summary: RunSummary) -> None:
    """在终端打印执行汇总。

    Args:
        summary: 执行结果。
    """
    print("\n" + "=" * 78)
    print(f"执行结果: {summary.status.upper()}    通过率: {summary.pass_rate}%")
    print(
        f"用例总数 {summary.total} | 通过 {summary.passed} | 失败 {summary.failed} "
        f"| 跳过 {summary.skipped} | 耗时 {summary.duration_ms / 1000:.2f}s"
    )
    print("=" * 78)
    for item in summary.results:
        icon = {
            "passed": "[PASS]",
            "failed": "[FAIL]",
            "error": "[ERROR]",
            "skipped": "[SKIP]",
        }.get(item.status, "[?]")
        print(f"{icon} [{item.case_type}] {item.case_name}  ({item.duration_ms:.0f}ms)")
        if item.status in {"failed", "error"} and item.message:
            for line in item.message.splitlines()[:4]:
                print(f"        {line}")
    if summary.log_path:
        print(f"\n完整日志: {summary.log_path}")
    if summary.allure_results_dir:
        print(f"Allure 结果目录: {summary.allure_results_dir}")
        print(f"查看报告: allure serve {summary.allure_results_dir}")
    print()


def main(argv: list[str] | None = None) -> int:
    """命令行主流程。

    Args:
        argv: 参数列表；为空时取 ``sys.argv[1:]``。

    Returns:
        进程退出码（0 表示全部通过，1 表示存在失败）。
    """
    args = build_parser().parse_args(argv)

    # CLI 场景下把日志收敛到 INFO 级别，避免 DEBUG 噪音淹没执行结果
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level: <7}</level> | {message}")

    file_path = Path(args.file)
    if not file_path.is_absolute():
        file_path = PROJECT_ROOT / file_path
    if not file_path.is_file():
        print(f"[错误] 用例文件不存在: {file_path}", file=sys.stderr)
        return 2

    try:
        loader = DataLoader(file_path).load()
    except DataLoadError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2

    tags = [tag for tag in (args.tags or "").split(",") if tag.strip()]
    cases = loader.filter_by_tags(tags)
    if args.case_type:
        cases = [case for case in cases if case.get("case_type", "api") == args.case_type]

    if not cases:
        print("[提示] 没有匹配到任何用例，请检查 --tags / --type 过滤条件", file=sys.stderr)
        return 2

    try:
        cases = resolve_setup_refs(cases)
    except SystemExit as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2

    variables: dict[str, Any] = {**loader.variables, **parse_variables(args.var)}
    env_config: dict[str, Any] = {
        "name": "cli",
        "base_url": str(variables.get("base_url") or ""),
        "headers": {"Content-Type": "application/json"},
        "variables": variables,
        "verify": True,
        "timeout": 30,
    }

    task_id = f"cli_{uuid.uuid4().hex[:12]}"
    runner = PytestRunner(
        project_root=PROJECT_ROOT, report_root=args.report_dir, timeout=args.timeout
    )
    print(f"准备执行 {len(cases)} 条用例（来源: {file_path.name}）...")
    extra_args = ["--alluredir", str(runner.allure_root / task_id)] if args.allure else []
    summary = runner.run(
        task_id=task_id,
        cases=cases,
        env_config=env_config,
        retry_times=max(0, args.retry),
        extra_args=extra_args,
    )

    if args.json:
        import json

        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    else:
        print_summary(summary)

    return 0 if summary.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
