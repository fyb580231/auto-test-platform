"""数据加载：YAML / JSON 用例文件读取与占位符渲染。

引擎层可以脱离数据库单独使用，此时用例以 YAML/JSON 文件形式存在，
本模块负责把它们读成统一的 Python 结构。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

SUPPORTED_SUFFIXES: frozenset[str] = frozenset({".yaml", ".yml", ".json"})


class DataLoadError(RuntimeError):
    """数据文件读取或格式解析失败。"""


def load_yaml(file_path: str | Path) -> Any:
    """读取 YAML 文件。

    Args:
        file_path: YAML 文件路径。

    Returns:
        解析后的 Python 对象。

    Raises:
        DataLoadError: 文件不存在或 YAML 语法错误。
    """
    path = Path(file_path)
    if not path.is_file():
        raise DataLoadError(f"YAML 文件不存在: {path}")
    try:
        with path.open("r", encoding="utf-8") as fp:
            return yaml.safe_load(fp)
    except yaml.YAMLError as exc:
        raise DataLoadError(f"YAML 解析失败 {path}: {exc}") from exc


def load_json(file_path: str | Path) -> Any:
    """读取 JSON 文件。

    Args:
        file_path: JSON 文件路径。

    Returns:
        解析后的 Python 对象。

    Raises:
        DataLoadError: 文件不存在或 JSON 语法错误。
    """
    path = Path(file_path)
    if not path.is_file():
        raise DataLoadError(f"JSON 文件不存在: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataLoadError(f"JSON 解析失败 {path}: {exc}") from exc


def load_data_file(file_path: str | Path) -> Any:
    """按文件后缀自动选择解析器。

    Args:
        file_path: YAML / JSON 文件路径。

    Returns:
        解析后的 Python 对象。

    Raises:
        DataLoadError: 后缀不支持或解析失败。
    """
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return load_yaml(path)
    if suffix == ".json":
        return load_json(path)
    raise DataLoadError(f"不支持的文件后缀 {suffix!r}，仅支持 {sorted(SUPPORTED_SUFFIXES)}")


class DataLoader:
    """用例数据加载器：支持单文件、目录批量与标签过滤。

    文件约定格式（YAML 示例）::

        variables:
          base_url: https://httpbin.org
        cases:
          - id: api_001
            name: 获取 IP
            case_type: api
            method: GET
            url: /ip
            assertions:
              - {type: status_code, expected: 200}

    Attributes:
        file_path: 数据文件路径。
    """

    def __init__(self, file_path: str | Path) -> None:
        """初始化加载器。

        Args:
            file_path: 数据文件路径（YAML 或 JSON）。
        """
        self.file_path = Path(file_path)
        self._raw: dict[str, Any] = {}

    def load(self) -> DataLoader:
        """加载并缓存文件内容。

        Returns:
            self，方便链式调用。

        Raises:
            DataLoadError: 文件内容不是字典结构。
        """
        data = load_data_file(self.file_path)
        if not isinstance(data, dict):
            raise DataLoadError(f"用例文件根节点必须是字典: {self.file_path}")
        self._raw = data
        logger.debug("已加载用例文件 {}，共 {} 条", self.file_path, len(self.cases))
        return self

    @property
    def variables(self) -> dict[str, Any]:
        """文件级变量（可用于 {{base_url}} 占位符渲染）。"""
        variables = self._raw.get("variables", {})
        return variables if isinstance(variables, dict) else {}

    @property
    def cases(self) -> list[dict[str, Any]]:
        """用例列表。"""
        cases = self._raw.get("cases", [])
        return [c for c in cases if isinstance(c, dict)] if isinstance(cases, list) else []

    def filter_by_tags(self, tags: list[str] | None) -> list[dict[str, Any]]:
        """按标签过滤用例（任一标签命中即保留）。

        Args:
            tags: 目标标签列表；为空时返回全部用例。

        Returns:
            过滤后的用例列表。
        """
        if not tags:
            return self.cases
        wanted = {t.strip().lower() for t in tags if t.strip()}
        selected: list[dict[str, Any]] = []
        for case in self.cases:
            case_tags = {str(t).strip().lower() for t in case.get("tags", []) or []}
            if wanted & case_tags:
                selected.append(case)
        return selected

    def filter_by_type(self, case_type: str | None) -> list[dict[str, Any]]:
        """按用例类型（api / ui）过滤。

        Args:
            case_type: 用例类型；为空时返回全部。

        Returns:
            过滤后的用例列表。
        """
        if not case_type:
            return self.cases
        return [c for c in self.cases if c.get("case_type", "api") == case_type]

    @classmethod
    def load_directory(cls, directory: str | Path) -> list[dict[str, Any]]:
        """加载目录下所有用例文件并合并用例。

        Args:
            directory: 目录路径。

        Returns:
            合并后的用例列表。

        Raises:
            DataLoadError: 目录不存在。
        """
        root = Path(directory)
        if not root.is_dir():
            raise DataLoadError(f"目录不存在: {root}")
        merged: list[dict[str, Any]] = []
        for path in sorted(root.iterdir()):
            if path.suffix.lower() in SUPPORTED_SUFFIXES and path.is_file():
                merged.extend(cls(path).load().cases)
        return merged
