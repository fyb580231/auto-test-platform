"""Allure 报告辅助。

平台把 Allure 作为**可选**能力：任何一台机器上都可能没有装 allure 命令行，
但用例本身必须能跑。因此这里所有函数在 allure 不可用时全部降级为 no-op，
只在日志里留一条 debug 记录，绝不因为「装不上 allure」而让测试失败。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from loguru import logger

try:  # pragma: no cover - 取决于运行环境是否安装 allure-pytest
    import allure

    ALLURE_AVAILABLE = True
except ImportError:  # pragma: no cover
    allure = None  # type: ignore[assignment]
    ALLURE_AVAILABLE = False


@contextmanager
def step(title: str) -> Iterator[None]:
    """Allure 步骤上下文管理器；allure 不可用时退化为普通代码块。

    Args:
        title: 步骤标题，会展示在 Allure 报告的时间轴上。

    Yields:
        None
    """
    if ALLURE_AVAILABLE:
        with allure.step(title):
            yield
    else:
        logger.debug("allure 不可用，跳过节包裹: {}", title)
        yield


def attach_text(name: str, content: str, mime: str = "text/plain") -> None:
    """把一段文本挂到 Allure 报告上。

    Args:
        name: 附件名称。
        content: 文本内容。
        mime: MIME 类型，默认 text/plain。
    """
    if not ALLURE_AVAILABLE:
        return
    try:
        allure.attach(content, name=name, attachment_type=_resolve_attachment_type(mime))
    except Exception as exc:  # noqa: BLE001 - 附件写入失败绝不能中断用例
        logger.warning("Allure 文本附件写入失败: {}", exc)


def attach_json(name: str, data: Any) -> None:
    """把任意可序列化对象以 JSON 形式挂到 Allure 报告。

    Args:
        name: 附件名称。
        data: 任意可 JSON 序列化的对象。
    """
    try:
        payload = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError) as exc:
        logger.warning("对象无法 JSON 序列化，改用 str(): {}", exc)
        payload = str(data)
    attach_text(name, payload, mime="application/json")


def attach_file(name: str, file_path: str | Path, mime: str = "application/octet-stream") -> None:
    """把磁盘上的文件挂到 Allure 报告（UI 用例失败截图就靠它）。

    Args:
        name: 附件名称。
        file_path: 文件路径。
        mime: MIME 类型。
    """
    if not ALLURE_AVAILABLE:
        return
    path = Path(file_path)
    if not path.is_file():
        logger.warning("附件文件不存在，跳过: {}", path)
        return
    try:
        allure.attach.file(str(path), name=name, attachment_type=_resolve_attachment_type(mime))
    except Exception as exc:  # noqa: BLE001 - 附件写入失败绝不能中断用例
        logger.warning("Allure 文件附件写入失败: {}", exc)


def attach_screenshot(name: str, file_path: str | Path) -> None:
    """把截图挂到 Allure 报告。

    Args:
        name: 附件名称。
        file_path: 截图文件路径。
    """
    attach_file(name, file_path, mime="image/png")


def _resolve_attachment_type(mime: str) -> Any:
    """把 MIME 字符串映射为 allure.attachment_type 枚举。

    Args:
        mime: MIME 字符串。

    Returns:
        allure.attachment_type 枚举值；无法识别时返回 PNG 之外的 TEXT 兜底。
    """
    if not ALLURE_AVAILABLE:
        return None
    mapping = {
        "text/plain": allure.attachment_type.TEXT,
        "text/html": allure.attachment_type.HTML,
        "application/json": allure.attachment_type.JSON,
        "application/xml": allure.attachment_type.XML,
        "image/png": allure.attachment_type.PNG,
        "image/jpeg": allure.attachment_type.JPG,
    }
    return mapping.get(mime, allure.attachment_type.TEXT)
