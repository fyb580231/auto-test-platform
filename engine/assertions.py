"""断言库：状态码 / 响应字段 / 响应时间 / JSON Schema 断言。

平台里的断言不是写死在代码中的，而是「配置」——每条用例带一组断言规则，
本模块负责把规则解释成真正的校验逻辑，并输出结构化的断言明细，
供前端报告页与 AI 失败分析消费。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import jsonschema
from loguru import logger

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注，避免循环导入
    from engine.client import ApiResponse

# 支持的断言类型
ASSERT_TYPE_STATUS = "status_code"
ASSERT_TYPE_JSON_FIELD = "json_field"
ASSERT_TYPE_RESPONSE_TIME = "response_time"
ASSERT_TYPE_SCHEMA = "schema"
ASSERT_TYPE_HEADER = "header"

SUPPORTED_ASSERT_TYPES: frozenset[str] = frozenset(
    {
        ASSERT_TYPE_STATUS,
        ASSERT_TYPE_JSON_FIELD,
        ASSERT_TYPE_RESPONSE_TIME,
        ASSERT_TYPE_SCHEMA,
        ASSERT_TYPE_HEADER,
    }
)

# json_field 支持的比较操作符
OP_EQ = "eq"
OP_NE = "ne"
OP_CONTAINS = "contains"
OP_NOT_CONTAINS = "not_contains"
OP_GT = "gt"
OP_LT = "lt"
OP_GE = "ge"
OP_LE = "le"
OP_EMPTY = "empty"
OP_NOT_EMPTY = "not_empty"
OP_IN = "in"
OP_REGEX = "regex"
OP_LENGTH_EQ = "length_eq"

SUPPORTED_OPS: frozenset[str] = frozenset(
    {
        OP_EQ,
        OP_NE,
        OP_CONTAINS,
        OP_NOT_CONTAINS,
        OP_GT,
        OP_LT,
        OP_GE,
        OP_LE,
        OP_EMPTY,
        OP_NOT_EMPTY,
        OP_IN,
        OP_REGEX,
        OP_LENGTH_EQ,
    }
)

_INDEX_PATTERN = re.compile(r"^(?P<name>[^\[\]]*)\[(?P<index>\d+)\]$")


def resolve_json_path(expression: str, data: Any, default: Any = None) -> Any:
    """按简化版 JSONPath 取值。

    支持 ``$.data.token``、``data.items[0].id``、``[0].name`` 等写法，
    足够覆盖接口测试的绝大多数场景，且不引入额外依赖。

    Args:
        expression: 取值表达式，例如 ``$.data.token``。
        data: 响应 JSON（已反序列化）。
        default: 取不到值时返回的兜底值。

    Returns:
        取到的值；路径不存在时返回 ``default``。
    """
    if not expression:
        return data
    path = expression.strip()
    if path.startswith("$"):
        path = path[1:]
    if path.startswith("."):
        path = path[1:]
    if not path:
        return data

    current = data
    for raw_segment in path.split("."):
        if not raw_segment:
            continue
        segment = raw_segment
        match = _INDEX_PATTERN.match(segment)
        name: str | None = segment
        index: int | None = None
        if match:
            name = match.group("name") or None
            index = int(match.group("index"))

        if name:
            if not isinstance(current, dict) or name not in current:
                return default
            current = current[name]
        if index is not None:
            if not isinstance(current, list) or index >= len(current):
                return default
            current = current[index]
    return current


@dataclass(slots=True)
class AssertionRule:
    """一条断言规则。

    Attributes:
        type: 断言类型，取值见 ``SUPPORTED_ASSERT_TYPES``。
        expected: 期望值；``status_code`` 场景下为期望状态码。
        field: 取值表达式，``json_field`` / ``header`` 场景必填。
        op: 比较操作符，默认 ``eq``。
        message: 自定义失败提示。
        name: 规则名称，便于报告展示。
    """

    type: str
    expected: Any = None
    field: str | None = None
    op: str = OP_EQ
    message: str | None = None
    name: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AssertionRule:
        """从字典构造规则，兼容 ``assert_type`` / ``op`` 等多种字段命名。

        Args:
            raw: 原始规则字典。

        Returns:
            断言规则对象。
        """
        return cls(
            type=str(raw.get("type") or raw.get("assert_type") or ASSERT_TYPE_STATUS),
            expected=raw.get("expected", raw.get("value")),
            field=raw.get("field"),
            op=str(raw.get("op") or raw.get("operator") or OP_EQ),
            message=raw.get("message"),
            name=raw.get("name"),
        )

    @property
    def label(self) -> str:
        """规则的可读描述，用于报告展示。"""
        if self.name:
            return self.name
        if self.type == ASSERT_TYPE_STATUS:
            return f"状态码 == {self.expected}"
        if self.type == ASSERT_TYPE_RESPONSE_TIME:
            return f"响应时间 <= {self.expected} ms"
        if self.type == ASSERT_TYPE_SCHEMA:
            return "JSON Schema 校验"
        target = self.field or "-"
        return f"{target} {self.op} {self.expected!r}"


@dataclass(slots=True)
class AssertionResult:
    """单条断言的执行结果。

    Attributes:
        label: 规则可读描述。
        type: 断言类型。
        expected: 期望值。
        actual: 实际值。
        passed: 是否通过。
        message: 失败原因。
    """

    label: str
    type: str
    expected: Any
    actual: Any
    passed: bool
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。

        Returns:
            字典结构。
        """
        return {
            "label": self.label,
            "type": self.type,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "message": self.message,
        }


class AssertionFailure(AssertionError):
    """断言失败异常：携带全部断言明细，便于报告与 AI 分析。

    Attributes:
        results: 本次全部断言结果。
    """

    def __init__(self, results: list[AssertionResult]) -> None:
        """初始化异常。

        Args:
            results: 本次全部断言结果（含通过项）。
        """
        self.results = results
        failed = [r for r in results if not r.passed]
        detail = "\n".join(f"  - {r.label} -> 实际: {r.actual!r} | {r.message}" for r in failed)
        super().__init__(f"{len(failed)} 条断言未通过:\n{detail}")


class AssertionEngine:
    """断言引擎：把断言规则列表作用到响应对象上。"""

    @staticmethod
    def verify(response: ApiResponse, rules: list[AssertionRule]) -> list[AssertionResult]:
        """执行全部断言。

        Args:
            response: 引擎层的统一响应对象。
            rules: 断言规则列表；为空时仅做「状态码 < 400」的兜底校验。

        Returns:
            断言明细列表。

        Raises:
            AssertionFailure: 存在未通过的断言。
        """
        effective_rules = rules or [
            AssertionRule(type=ASSERT_TYPE_STATUS, expected=200, name="默认断言: 状态码 == 200")
        ]
        results = [AssertionEngine._check_one(response, rule) for rule in effective_rules]
        for item in results:
            logger.debug(
                "断言 [{}] {} -> {}", item.label, "PASS" if item.passed else "FAIL", item.actual
            )
        if any(not item.passed for item in results):
            raise AssertionFailure(results)
        return results

    @staticmethod
    def parse_rules(raw_rules: Any) -> list[AssertionRule]:
        """把数据库/文件中的原始断言配置解析成规则对象。

        Args:
            raw_rules: 原始配置，通常是 ``list[dict]``。

        Returns:
            断言规则列表。
        """
        if not raw_rules:
            return []
        parsed: list[AssertionRule] = []
        for item in raw_rules:
            if isinstance(item, AssertionRule):
                parsed.append(item)
            elif isinstance(item, dict):
                parsed.append(AssertionRule.from_dict(item))
            else:
                logger.warning("忽略无法解析的断言规则: {!r}", item)
        return parsed

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #
    @staticmethod
    def _check_one(response: ApiResponse, rule: AssertionRule) -> AssertionResult:
        """执行单条断言，任何异常都转成「失败结果」而不是抛出。

        Args:
            response: 统一响应对象。
            rule: 断言规则。

        Returns:
            断言结果。
        """
        try:
            if rule.type == ASSERT_TYPE_STATUS:
                return AssertionEngine._check_status(response, rule)
            if rule.type == ASSERT_TYPE_JSON_FIELD:
                return AssertionEngine._check_json_field(response, rule)
            if rule.type == ASSERT_TYPE_RESPONSE_TIME:
                return AssertionEngine._check_response_time(response, rule)
            if rule.type == ASSERT_TYPE_SCHEMA:
                return AssertionEngine._check_schema(response, rule)
            if rule.type == ASSERT_TYPE_HEADER:
                return AssertionEngine._check_header(response, rule)
        except Exception as exc:  # noqa: BLE001 - 断言内部异常统一标记为失败
            return AssertionResult(
                label=rule.label,
                type=rule.type,
                expected=rule.expected,
                actual=None,
                passed=False,
                message=f"断言执行异常: {exc}",
            )
        return AssertionResult(
            label=rule.label,
            type=rule.type,
            expected=rule.expected,
            actual=None,
            passed=False,
            message=f"不支持的断言类型: {rule.type}",
        )

    @staticmethod
    def _check_status(response: ApiResponse, rule: AssertionRule) -> AssertionResult:
        """校验 HTTP 状态码。"""
        try:
            expected = int(rule.expected)
        except (TypeError, ValueError):
            return AssertionResult(
                rule.label,
                rule.type,
                rule.expected,
                response.status_code,
                False,
                "期望状态码必须是整数",
            )
        passed = response.status_code == expected
        return AssertionResult(
            rule.label,
            rule.type,
            expected,
            response.status_code,
            passed,
            "" if passed else f"期望 {expected}，实际 {response.status_code}",
        )

    @staticmethod
    def _check_response_time(response: ApiResponse, rule: AssertionRule) -> AssertionResult:
        """校验响应耗时是否小于等于期望毫秒数。"""
        try:
            limit = float(rule.expected)
        except (TypeError, ValueError):
            return AssertionResult(
                rule.label,
                rule.type,
                rule.expected,
                response.elapsed_ms,
                False,
                "期望耗时必须是数字",
            )
        passed = response.elapsed_ms <= limit
        return AssertionResult(
            rule.label,
            rule.type,
            limit,
            round(response.elapsed_ms, 2),
            passed,
            "" if passed else f"响应耗时 {response.elapsed_ms:.2f}ms 超过阈值 {limit}ms",
        )

    @staticmethod
    def _check_header(response: ApiResponse, rule: AssertionRule) -> AssertionResult:
        """校验响应头。"""
        key = (rule.field or "").lower()
        actual = response.headers.get(key)
        return AssertionEngine._compare(rule, actual)

    @staticmethod
    def _check_json_field(response: ApiResponse, rule: AssertionRule) -> AssertionResult:
        """校验响应 JSON 字段。"""
        body = response.body
        actual = resolve_json_path(rule.field or "", body, default=_MISSING)
        if actual is _MISSING and not isinstance(body, dict | list):
            return AssertionResult(
                rule.label,
                rule.type,
                rule.expected,
                body if isinstance(body, str) else None,
                False,
                "响应不是合法 JSON，无法取字段",
            )
        return AssertionEngine._compare(rule, actual)

    @staticmethod
    def _check_schema(response: ApiResponse, rule: AssertionRule) -> AssertionResult:
        """用 JSON Schema 校验响应结构。"""
        schema = rule.expected
        if not isinstance(schema, dict):
            return AssertionResult(
                rule.label, rule.type, schema, None, False, "schema 断言需要提供 JSON Schema 字典"
            )
        try:
            jsonschema.validate(instance=response.body, schema=schema)
        except jsonschema.ValidationError as exc:
            return AssertionResult(
                rule.label,
                rule.type,
                schema,
                None,
                False,
                f"Schema 校验失败: {exc.message} (path={list(exc.absolute_path)})",
            )
        except jsonschema.SchemaError as exc:
            return AssertionResult(
                rule.label, rule.type, schema, None, False, f"Schema 本身非法: {exc.message}"
            )
        return AssertionResult(rule.label, rule.type, schema, response.body, True)

    @staticmethod
    def _compare(rule: AssertionRule, actual: Any) -> AssertionResult:
        """按操作符比较实际值与期望值。

        Args:
            rule: 断言规则。
            actual: 实际取到的值；可能为 ``_MISSING`` 表示字段不存在。

        Returns:
            断言结果。
        """
        op = rule.op
        expected = rule.expected
        missing = actual is _MISSING
        if op not in SUPPORTED_OPS:
            return AssertionResult(
                rule.label, rule.type, expected, None, False, f"不支持的操作符: {op}"
            )

        passed = False
        message = ""
        display_actual: Any = None if missing else actual

        if op == OP_EMPTY:
            passed = missing or actual is None or actual == "" or actual == [] or actual == {}
            message = "" if passed else "期望为空，但实际有值"
        elif op == OP_NOT_EMPTY:
            passed = not (missing or actual is None or actual == "" or actual == [] or actual == {})
            message = "" if passed else "期望非空，但实际为空"
        elif missing:
            passed = False
            message = f"字段 {rule.field!r} 在响应中不存在"
        elif op == OP_EQ:
            passed = _loose_equal(actual, expected)
            message = "" if passed else f"期望等于 {expected!r}"
        elif op == OP_NE:
            passed = not _loose_equal(actual, expected)
            message = "" if passed else f"期望不等于 {expected!r}"
        elif op == OP_CONTAINS:
            passed = _contains(actual, expected)
            message = "" if passed else f"期望包含 {expected!r}"
        elif op == OP_NOT_CONTAINS:
            passed = not _contains(actual, expected)
            message = "" if passed else f"期望不包含 {expected!r}"
        elif op in {OP_GT, OP_LT, OP_GE, OP_LE}:
            passed, message = _compare_order(op, actual, expected)
        elif op == OP_IN:
            candidates = expected if isinstance(expected, list | tuple | set) else [expected]
            passed = any(_loose_equal(actual, c) for c in candidates)
            message = "" if passed else f"期望取值属于 {list(candidates)!r}"
        elif op == OP_REGEX:
            try:
                passed = bool(re.search(str(expected), str(actual)))
            except re.error as exc:
                passed, message = False, f"正则表达式非法: {exc}"
            message = message or ("" if passed else f"期望匹配正则 {expected!r}")
        elif op == OP_LENGTH_EQ:
            try:
                passed = len(actual) == int(expected)  # type: ignore[arg-type]
            except TypeError:
                passed, message = False, "实际值不支持求长度"
            message = message or ("" if passed else f"期望长度 {expected}")

        if rule.message and not passed:
            message = rule.message
        return AssertionResult(rule.label, rule.type, expected, display_actual, passed, message)


class _Missing:
    """字段缺失的哨兵对象（与 JSON 中的 null 区分开）。"""

    def __repr__(self) -> str:  # pragma: no cover - 仅用于日志
        return "<MISSING>"

    def __bool__(self) -> bool:
        return False


_MISSING = _Missing()


def _loose_equal(actual: Any, expected: Any) -> bool:
    """宽松相等比较：兼容 ``1 == "1"``、``True == "true"`` 等脏数据场景。

    Args:
        actual: 实际值。
        expected: 期望值。

    Returns:
        是否相等。
    """
    if actual == expected:
        return True
    if isinstance(actual, bool) or isinstance(expected, bool):
        return str(actual).lower() == str(expected).lower()
    if isinstance(actual, int | float) and isinstance(expected, str):
        try:
            return float(actual) == float(expected)
        except ValueError:
            return False
    if isinstance(expected, int | float) and isinstance(actual, str):
        try:
            return float(actual) == float(expected)
        except ValueError:
            return False
    return str(actual) == str(expected)


def _contains(actual: Any, expected: Any) -> bool:
    """包含判断，兼容字符串、列表、字典与数字类型。

    Args:
        actual: 实际值。
        expected: 期望包含的内容。

    Returns:
        是否包含。
    """
    if actual is None:
        return False
    if isinstance(actual, dict):
        return str(expected) in actual or expected in actual.values()
    if isinstance(actual, list | tuple | set):
        if expected in actual:
            return True
        return any(str(expected) in str(item) for item in actual)
    return str(expected) in str(actual)


def _compare_order(op: str, actual: Any, expected: Any) -> tuple[bool, str]:
    """大小比较，自动做数字/字符串降级。

    Args:
        op: 操作符。
        actual: 实际值。
        expected: 期望值。

    Returns:
        ``(是否通过, 失败提示)`` 二元组。
    """
    left, right = actual, expected
    if isinstance(left, str) or isinstance(right, str):
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            left, right = str(actual), str(expected)
    try:
        outcomes = {
            OP_GT: left > right,
            OP_LT: left < right,
            OP_GE: left >= right,
            OP_LE: left <= right,
        }
        passed = outcomes[op]
    except TypeError:
        return False, f"无法比较 {actual!r} 与 {expected!r}"
    symbols = {OP_GT: ">", OP_LT: "<", OP_GE: ">=", OP_LE: "<="}
    return passed, "" if passed else f"期望 {symbols[op]} {expected!r}，实际 {actual!r}"


@dataclass(slots=True)
class AssertionRulesHolder:
    """便捷容器：把原始配置一次性解析为可复用规则集合。

    Attributes:
        rules: 解析后的断言规则列表。
    """

    rules: list[AssertionRule] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw_rules: Any) -> AssertionRulesHolder:
        """从原始配置构造。

        Args:
            raw_rules: 原始断言配置。

        Returns:
            容器实例。
        """
        return cls(rules=AssertionEngine.parse_rules(raw_rules))
