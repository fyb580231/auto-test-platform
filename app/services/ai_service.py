"""AI 能力服务：通过 OpenAI SDK 调用 DeepSeek（OpenAI 兼容接口）。

三条硬性设计原则：

1. **绝不阻塞主流程。** 所有模型调用都有超时、有限重试与异常兜底；
   调用失败时自动降级为「基于真实数据的规则兜底结果」，并把 ``mocked=True`` 透出给前端，
   平台其余功能完全不受影响。
2. **提示词与代码分离。** 每个能力的 system prompt 放在 ``prompts/*.md``，
   调优提示词不需要改代码、不需要重新部署。
3. **成本可控。** 送入模型前统一做长度截断，返回后统一记录 token 用量，
   调用方可以把用量落到日志/表里做成本核算。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from app.config import settings
from app.schemas.ai import (
    AIStatusOut,
    AnalysisResponse,
    GenerateCasesRequest,
    GenerateCasesResponse,
    QueryReportResponse,
)
from app.schemas.common import AssertionRuleSchema
from app.schemas.testcase import TestCaseCreateRequest
from app.utils.logger import get_logger

logger = get_logger(__name__)

PROMPT_DIR: Path = Path(__file__).resolve().parent / "prompts"
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

# 归因分类（与 failure_analysis.md 中约定一致）
CATEGORY_API_BUG = "接口缺陷"
CATEGORY_SCRIPT_BUG = "脚本缺陷"
CATEGORY_ENV_ISSUE = "环境问题"
CATEGORY_DESIGN_ISSUE = "用例设计问题"

_PROMPT_FILE_MAP = {
    "generate_cases": "generate_cases.md",
    "failure_analysis": "failure_analysis.md",
    "report_qa": "report_qa.md",
}


class AIUnavailableError(RuntimeError):
    """AI 能力不可用（未配置 Key、开关关闭或调用失败）。"""


def load_prompt(name: str) -> str:
    """从 prompts 目录加载系统提示词。

    Args:
        name: 能力名（generate_cases / failure_analysis / report_qa）。

    Returns:
        提示词内容。

    Raises:
        KeyError: 未知能力名。
        FileNotFoundError: 提示词文件缺失。
    """
    if name not in _PROMPT_FILE_MAP:
        raise KeyError(f"未知的 AI 能力: {name}")
    file_path = PROMPT_DIR / _PROMPT_FILE_MAP[name]
    if not file_path.is_file():
        raise FileNotFoundError(f"提示词文件缺失: {file_path}")
    return file_path.read_text(encoding="utf-8")


def _truncate(text: str, limit: int) -> str:
    """按字符数截断文本，避免超长日志打爆 token 预算。

    Args:
        text: 原始文本。
        limit: 最大字符数。

    Returns:
        截断后的文本（会附加省略标记）。
    """
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...[已截断，原始长度 {len(text)} 字符]"


def _extract_json(text: str) -> dict[str, Any]:
    """从模型输出中稳健地提取 JSON 对象。

    模型有时会画蛇添足地加上 ```json 代码块或前后解释，这里做三层兜底。

    Args:
        text: 模型原始输出。

    Returns:
        解析后的字典。

    Raises:
        ValueError: 三层兜底后仍无法解析。
    """
    if not text:
        raise ValueError("模型返回内容为空")
    candidates: list[str] = [text.strip()]

    fenced = _JSON_FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())

    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"模型返回内容不是合法 JSON: {text[:200]}")


class AIService:
    """AI 能力服务。

    Attributes:
        model: 使用的模型名。
    """

    def __init__(self) -> None:
        """初始化服务（延迟创建 SDK 客户端，未配置 Key 时不会报错）。"""
        self.model = settings.deepseek_model
        self._client: Any = None

    # ------------------------------------------------------------------ #
    # 状态
    # ------------------------------------------------------------------ #
    @property
    def available(self) -> bool:
        """是否可以发起真实模型调用。"""
        return settings.ai_available

    def status(self) -> AIStatusOut:
        """返回 AI 能力状态，供前端提示当前是否为 Mock 模式。

        Returns:
            状态响应对象。
        """
        if not settings.ai_enabled:
            message = "AI 能力已在配置中关闭（AI_ENABLED=false）"
        elif settings.ai_mock:
            message = "AI_MOCK=true，当前为 Mock 模式，返回的是内置示例结果"
        elif not settings.deepseek_api_key.strip():
            message = "未配置 DEEPSEEK_API_KEY，当前为 Mock 模式；配置后自动启用真实模型调用"
        else:
            message = "已接入 DeepSeek，AI 能力可用"
        return AIStatusOut(
            enabled=settings.ai_enabled,
            available=self.available,
            mocked=not self.available,
            model=self.model,
            base_url=settings.deepseek_base_url,
            message=message,
        )

    # ------------------------------------------------------------------ #
    # 能力一：AI 生成用例
    # ------------------------------------------------------------------ #
    def generate_cases(self, request: GenerateCasesRequest) -> GenerateCasesResponse:
        """根据接口信息生成接口测试用例。

        Args:
            request: 生成请求参数。

        Returns:
            生成结果；模型不可用时返回规则兜底结果且 ``mocked=True``。
        """
        if not self.available:
            logger.info("AI 不可用，使用规则兜底生成用例")
            return self._mock_generate_cases(request)

        user_prompt = self._build_generate_prompt(request)
        try:
            content, usage = self._chat(
                prompt_name="generate_cases",
                user_prompt=user_prompt,
                json_mode=True,
            )
            payload = _extract_json(content)
            cases = self._parse_generated_cases(payload, request)
            if not cases:
                raise ValueError("模型未返回任何有效用例")
            return GenerateCasesResponse(
                cases=cases, model=self.model, mocked=False, usage=usage, raw=content
            )
        except Exception as exc:  # noqa: BLE001 - AI 失败必须降级，不能影响主流程
            logger.warning("AI 生成用例失败，降级为规则兜底: {}", exc)
            response = self._mock_generate_cases(request)
            response.raw = f"模型调用失败（{exc}），已降级为规则兜底结果。"
            return response

    # ------------------------------------------------------------------ #
    # 能力二：AI 失败分析
    # ------------------------------------------------------------------ #
    def analyze_failure(self, context: dict[str, Any]) -> AnalysisResponse:
        """分析一条失败用例的根因。

        Args:
            context: 失败上下文，包含 ``task_id`` / ``case_name`` / ``message`` /
                ``traceback`` / ``request`` / ``response`` / ``assertions``。

        Returns:
            分析结果；模型不可用时返回规则兜底结果且 ``mocked=True``。
        """
        task_id = int(context.get("task_id") or 0)
        case_name = str(context.get("case_name") or "")

        if not self.available:
            logger.info("AI 不可用，使用规则兜底做失败分析")
            return self._mock_analyze_failure(context)

        user_prompt = self._build_analysis_prompt(context)
        try:
            content, usage = self._chat(
                prompt_name="failure_analysis",
                user_prompt=user_prompt,
                json_mode=True,
            )
            payload = _extract_json(content)
            return AnalysisResponse(
                task_id=task_id,
                case_name=case_name,
                category=str(payload.get("category") or CATEGORY_SCRIPT_BUG),
                summary=str(payload.get("summary") or ""),
                reasons=[str(item) for item in payload.get("reasons") or []],
                suggestions=[str(item) for item in payload.get("suggestions") or []],
                raw=content,
                mocked=False,
                usage=usage,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("AI 失败分析失败，降级为规则兜底: {}", exc)
            response = self._mock_analyze_failure(context)
            response.raw = f"模型调用失败（{exc}），已降级为规则兜底结果。"
            return response

    # ------------------------------------------------------------------ #
    # 能力三：自然语言查报告
    # ------------------------------------------------------------------ #
    def answer_report_question(self, question: str, stats: dict[str, Any]) -> QueryReportResponse:
        """基于结构化统计上下文，用自然语言回答报告问题。

        Args:
            question: 用户问题。
            stats: 由 ``report_service`` 聚合出的结构化统计。

        Returns:
            回答结果；模型不可用时返回基于真实统计的规则答案。
        """
        if not self.available:
            logger.info("AI 不可用，使用规则兜底回答报告问题")
            return self._mock_answer_question(question, stats)

        user_prompt = (
            f"# 用户问题\n{question}\n\n"
            f"# 统计上下文\n```json\n"
            f"{json.dumps(stats, ensure_ascii=False, indent=2, default=str)}\n```"
        )
        try:
            content, usage = self._chat(
                prompt_name="report_qa",
                user_prompt=user_prompt,
                json_mode=False,
            )
            return QueryReportResponse(
                question=question, answer=content.strip(), stats=stats, mocked=False, usage=usage
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("AI 报告问答失败，降级为规则兜底: {}", exc)
            response = self._mock_answer_question(question, stats)
            response.answer = (
                f"{response.answer}\n\n> 注：模型调用失败（{exc}），以上为基于原始统计的规则结果。"
            )
            return response

    # ------------------------------------------------------------------ #
    # 模型调用底座
    # ------------------------------------------------------------------ #
    def _get_client(self) -> Any:
        """创建（并缓存）OpenAI SDK 客户端。

        Returns:
            OpenAI 客户端实例。

        Raises:
            AIUnavailableError: 未配置 API Key。
        """
        if not settings.deepseek_api_key.strip():
            raise AIUnavailableError("未配置 DEEPSEEK_API_KEY")
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=settings.deepseek_api_key.strip(),
                base_url=settings.deepseek_base_url,
                timeout=settings.ai_timeout_seconds,
                max_retries=0,  # 重试策略由本服务自己控制，便于记录日志
            )
        return self._client

    def _chat(
        self,
        prompt_name: str,
        user_prompt: str,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> tuple[str, dict[str, Any]]:
        """发起一次对话补全，内置重试与耗时统计。

        Args:
            prompt_name: 提示词文件名（不含扩展名）。
            user_prompt: 用户侧提示词。
            json_mode: 是否要求模型返回 JSON 对象。
            temperature: 采样温度。

        Returns:
            ``(模型输出文本, token 用量)`` 二元组。

        Raises:
            AIUnavailableError: 全部重试后仍失败。
        """
        client = self._get_client()
        system_prompt = load_prompt(prompt_name)
        attempts = max(1, settings.ai_max_retries + 1)
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": settings.ai_max_tokens,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                completion = client.chat.completions.create(**kwargs)
                elapsed = (time.perf_counter() - started) * 1000
                content = (completion.choices[0].message.content or "").strip()
                usage = self._collect_usage(completion, elapsed, prompt_name)
                logger.info(
                    "AI 调用成功: prompt={} 耗时={:.0f}ms tokens={}",
                    prompt_name,
                    elapsed,
                    usage.get("total_tokens"),
                )
                return content, usage
            except Exception as exc:  # noqa: BLE001 - SDK 异常类型繁多，统一处理
                last_error = exc
                logger.warning(
                    "AI 调用失败（{}/{}）: prompt={} error={}", attempt, attempts, prompt_name, exc
                )
                if attempt < attempts:
                    time.sleep(min(2 ** (attempt - 1), 4))

        raise AIUnavailableError(f"AI 调用重试 {attempts} 次后仍失败: {last_error}")

    @staticmethod
    def _collect_usage(completion: Any, elapsed_ms: float, prompt_name: str) -> dict[str, Any]:
        """提取 token 用量，作为成本核算依据。

        Args:
            completion: SDK 返回的补全对象。
            elapsed_ms: 耗时毫秒。
            prompt_name: 能力名。

        Returns:
            用量字典。
        """
        usage: dict[str, Any] = {"prompt_name": prompt_name, "elapsed_ms": round(elapsed_ms, 1)}
        raw_usage = getattr(completion, "usage", None)
        if raw_usage is None:
            return usage
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(raw_usage, field, None)
            if value is not None:
                usage[field] = value
        return usage

    # ------------------------------------------------------------------ #
    # 提示词拼装
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_generate_prompt(request: GenerateCasesRequest) -> str:
        """拼装生成用例的用户提示词。

        Args:
            request: 生成请求参数。

        Returns:
            用户提示词。
        """
        lines = [
            "# 接口信息",
            f"- 请求方法：{request.method.upper()}",
            f"- 接口地址：{request.url}",
            f"- 业务描述：{request.description}",
            "",
            "# 生成要求",
            f"- 生成 {request.case_count} 条用例",
            "- 必须覆盖正向、反向、边界、异常四类场景",
            f"- 所有用例的 tags 默认带上：{', '.join(request.tags) if request.tags else 'ai'}",
        ]
        if request.extra_requirements:
            lines.extend(["", "# 额外要求", request.extra_requirements])
        return "\n".join(lines)

    @staticmethod
    def _build_analysis_prompt(context: dict[str, Any]) -> str:
        """拼装失败分析的用户提示词（含长度截断）。

        Args:
            context: 失败上下文。

        Returns:
            用户提示词。
        """
        limit = settings.ai_max_log_chars
        sections = [
            "# 用例信息",
            f"- 用例名称：{context.get('case_name')}",
            f"- 用例类型：{context.get('case_type', 'api')}",
            f"- 失败摘要：{_truncate(str(context.get('message') or ''), 1000)}",
            "",
            "# 断言明细",
            _truncate(
                json.dumps(context.get("assertions") or [], ensure_ascii=False, indent=2),
                limit // 3,
            ),
        ]
        if context.get("request"):
            sections.extend(
                [
                    "",
                    "# 请求详情",
                    _truncate(
                        json.dumps(
                            context.get("request"), ensure_ascii=False, indent=2, default=str
                        ),
                        limit // 3,
                    ),
                ]
            )
        if context.get("response"):
            sections.extend(
                [
                    "",
                    "# 响应详情",
                    _truncate(
                        json.dumps(
                            context.get("response"), ensure_ascii=False, indent=2, default=str
                        ),
                        limit // 2,
                    ),
                ]
            )
        if context.get("steps"):
            sections.extend(
                [
                    "",
                    "# UI 步骤",
                    _truncate(
                        json.dumps(context.get("steps"), ensure_ascii=False, indent=2), limit // 3
                    ),
                ]
            )
        sections.extend(
            [
                "",
                "# 错误堆栈",
                _truncate(str(context.get("traceback") or ""), limit),
            ]
        )
        return "\n".join(sections)

    # ------------------------------------------------------------------ #
    # 规则兜底实现（无 Key / 调用失败时使用，结果基于真实数据而非随机造）
    # ------------------------------------------------------------------ #
    def _parse_generated_cases(
        self, payload: dict[str, Any], request: GenerateCasesRequest
    ) -> list[TestCaseCreateRequest]:
        """把模型返回的 JSON 校验成合法的用例对象。

        模型输出不可全信，这里逐条做 Pydantic 校验，坏数据直接丢弃并记日志，
        避免脏数据写进数据库。

        Args:
            payload: 模型返回的字典。
            request: 原始生成请求（用于补齐缺失字段）。

        Returns:
            合法的用例列表。
        """
        raw_cases = payload.get("cases")
        if not isinstance(raw_cases, list):
            return []
        parsed: list[TestCaseCreateRequest] = []
        for index, item in enumerate(raw_cases):
            if not isinstance(item, dict):
                continue
            item.setdefault("case_type", "api")
            item.setdefault("method", request.method.upper())
            item.setdefault("url", request.url)
            item.setdefault("tags", request.tags or ["ai"])
            if not item.get("assertions"):
                item["assertions"] = [{"type": "status_code", "expected": 200}]
            try:
                parsed.append(TestCaseCreateRequest.model_validate(item))
            except Exception as exc:  # noqa: BLE001 - 丢弃单条坏数据，不影响其余
                logger.warning("丢弃第 {} 条非法 AI 用例: {}", index + 1, exc)
        return parsed

    def _mock_generate_cases(self, request: GenerateCasesRequest) -> GenerateCasesResponse:
        """规则兜底：按「正向 / 反向 / 边界 / 异常」四类模板生成结构化用例。

        这不是「假数据」——它是有意设计的降级路径：即使没有 API Key，
        用户也能完整体验「生成 -> 导入 -> 执行 -> 报告」的闭环。

        Args:
            request: 生成请求参数。

        Returns:
            生成结果，``mocked=True``。
        """
        method = request.method.upper()
        url = request.url
        tags = request.tags or ["ai"]
        success_code = 200
        body: dict[str, Any] | None = (
            {"username": "test_user_001", "password": "Test@123456"}
            if method in {"POST", "PUT", "PATCH"}
            else None
        )

        templates: list[dict[str, Any]] = [
            {
                "name": f"{request.description[:20]} - 正向流程",
                "description": "主流程正常参数，验证接口在合法输入下能正确返回成功。",
                "tags": [*tags, "smoke"],
                "method": method,
                "url": url,
                "body": body,
                "params": {"page": 1} if method == "GET" else {},
                "assertions": [
                    {
                        "type": "status_code",
                        "expected": success_code,
                        "name": f"状态码 {success_code}",
                    },
                    {"type": "response_time", "expected": 5000, "name": "响应时间小于 5s"},
                ],
            },
            {
                "name": f"{request.description[:20]} - 必填参数缺失",
                "description": "不传任何业务参数，验证服务端对必填校验的防御能力，预期返回 4xx 而不是 5xx。",
                "tags": [*tags, "regression"],
                "method": method,
                "url": url,
                "body": {} if body is not None else None,
                "params": {},
                "assertions": [
                    {
                        "type": "json_field",
                        "field": "$.code",
                        "op": "not_empty",
                        "name": "返回体包含业务错误码",
                    },
                    {"type": "response_time", "expected": 5000, "name": "响应时间小于 5s"},
                ],
            },
            {
                "name": f"{request.description[:20]} - 非法参数类型",
                "description": "传入类型错误的参数（数字传字符串），验证参数校验与错误提示。",
                "tags": [*tags, "regression"],
                "method": method,
                "url": url,
                "body": (
                    {"username": 12345, "password": ["not", "a", "string"]}
                    if body is not None
                    else None
                ),
                "params": {"page": "not_a_number"} if method == "GET" else {},
                "assertions": [
                    {"type": "response_time", "expected": 5000, "name": "响应时间小于 5s"},
                ],
            },
            {
                "name": f"{request.description[:20]} - 超长字段边界",
                "description": "传入超长字符串（1000 字符），验证服务端长度校验与截断策略。",
                "tags": [*tags, "regression"],
                "method": method,
                "url": url,
                "body": (
                    {"username": "a" * 1000, "password": "b" * 1000} if body is not None else None
                ),
                "params": {"q": "x" * 1000} if method == "GET" else {},
                "assertions": [
                    {
                        "type": "response_time",
                        "expected": 8000,
                        "name": "响应时间小于 8s（超长输入不应拖垮服务）",
                    },
                ],
            },
            {
                "name": f"{request.description[:20]} - 未授权访问",
                "description": "不携带认证信息访问，验证接口的鉴权拦截是否生效。",
                "tags": [*tags, "critical"],
                "method": method,
                "url": url,
                "headers": {},
                "body": body,
                "assertions": [
                    {
                        "type": "status_code",
                        "expected": 200,
                        "name": "匿名访问会被业务层拦截（占位断言，请按真实契约调整）",
                    },
                ],
            },
            {
                "name": f"{request.description[:20]} - 并发重复提交",
                "description": "同一请求体连续提交两次，验证幂等性或重复提交保护。",
                "tags": [*tags, "regression"],
                "method": method,
                "url": url,
                "body": body,
                "assertions": [
                    {"type": "response_time", "expected": 5000, "name": "响应时间小于 5s"},
                ],
            },
        ]

        selected = templates[: max(1, min(request.case_count, len(templates)))]
        cases: list[TestCaseCreateRequest] = []
        for index, item in enumerate(selected, start=1):
            item.setdefault("case_type", "api")
            item["name"] = f"{item['name']}（Mock 模板 {index}）"
            try:
                cases.append(TestCaseCreateRequest.model_validate(item))
            except Exception as exc:  # noqa: BLE001
                logger.warning("兜底模板 {} 校验失败: {}", index, exc)

        return GenerateCasesResponse(
            cases=cases,
            model="rule-based-mock",
            mocked=True,
            usage={"prompt_name": "generate_cases", "elapsed_ms": 0.0, "total_tokens": 0},
            raw="未配置 DEEPSEEK_API_KEY，返回内置模板生成的用例。模板覆盖正向/反向/边界/异常四类场景。",
        )

    def _mock_analyze_failure(self, context: dict[str, Any]) -> AnalysisResponse:
        """规则兜底：基于真实失败信息做归因。

        归因规则来自测试团队的经验沉淀，虽然是规则而不是模型，但结论同样**基于真实日志**，
        不是编造文案。

        Args:
            context: 失败上下文。

        Returns:
            分析结果，``mocked=True``。
        """
        message = str(context.get("message") or "")
        traceback_text = str(context.get("traceback") or "")
        assertions = context.get("assertions") or []
        response = context.get("response") or {}
        status_code = response.get("status_code")
        combined = f"{message}\n{traceback_text}".lower()

        category = CATEGORY_SCRIPT_BUG
        reasons: list[str] = []
        suggestions: list[str] = []

        env_keywords = (
            "connectionerror",
            "connecttimeout",
            "readtimeout",
            "timeout",
            "ssl",
            "dns",
            "nameresolution",
            "502",
            "503",
            "504",
            "connection refused",
            "proxy",
        )
        if any(keyword in combined for keyword in env_keywords):
            category = CATEGORY_ENV_ISSUE
            reasons.append(
                "失败信息中出现连接层关键字（超时 / 连接失败 / 5xx 网关错误），而非业务断言不通过"
            )
            reasons.append(f"失败摘要：{message[:200]}")
            suggestions.append("确认目标服务是否可访问：用 curl 或浏览器直接请求一次请求地址")
            suggestions.append("检查项目的环境配置中 base_url 是否正确、是否需要走内网或代理")
            suggestions.append("若目标服务不稳定，可在环境配置里适当调大 timeout 并开启网络层重试")
        elif status_code is not None and response:
            failed_rules = [a for a in assertions if not a.get("passed", True)]
            expected_values = [a.get("expected") for a in failed_rules]
            if status_code and int(status_code) >= 400 and int(status_code) < 500:
                category = CATEGORY_API_BUG if expected_values else CATEGORY_ENV_ISSUE
                reasons.append(f"接口返回了 {status_code}，说明服务端有响应但拒绝了请求")
                reasons.append(
                    "请求参数看起来是合法输入，若为鉴权/权限类 401/403 需确认是否缺少 Token"
                )
                suggestions.append(
                    f"确认接口契约：{status_code} 是否符合预期；若接口要求鉴权，请为该用例配置前置用例获取 Token"
                )
                suggestions.append("核对请求头（Content-Type / Authorization）与接口文档是否一致")
            else:
                category = CATEGORY_API_BUG
                reasons.append(f"接口返回 {status_code}，HTTP 层正常，但业务断言未通过")
                for rule in failed_rules[:3]:
                    reasons.append(
                        f"断言 [{rule.get('label')}] 期望 {rule.get('expected')!r}，实际 {rule.get('actual')!r}"
                    )
                suggestions.append(
                    "对照接口文档确认期望值是否写错；若响应结构已变更，请同步更新断言的字段路径"
                )
                suggestions.append("用返回体里的真实字段值替换断言期望值，再复跑一次确认")
        elif (
            "元素" in message
            or "selector" in combined
            or "playwright" in combined
            or "timeout" in combined
        ):
            category = CATEGORY_SCRIPT_BUG
            reasons.append("UI 步骤在等待元素时失败，通常是选择器失效或页面加载慢于默认超时")
            reasons.append(f"失败摘要：{message[:200]}")
            suggestions.append(
                "用浏览器开发者工具重新确认选择器，优先使用 data-test 之类的稳定属性"
            )
            suggestions.append("为该步骤单独设置更大的 timeout，或在断言前增加等待步骤")
        else:
            reasons.append("未命中环境/网络特征，失败发生在断言或脚本执行阶段")
            reasons.append(f"失败摘要：{message[:200]}")
            suggestions.append("先单独执行这条用例复现问题，排除批量执行时的数据依赖干扰")
            suggestions.append("检查用例的请求地址、参数位置（params vs body）是否与接口文档一致")

        if not reasons:
            reasons.append("信息不足，仅能定位到执行失败")
        if not suggestions:
            suggestions.append("补充完整日志后重新分析")

        summary = f"判定为「{category}」：{reasons[0][:60]}"
        return AnalysisResponse(
            task_id=int(context.get("task_id") or 0),
            case_name=str(context.get("case_name") or ""),
            category=category,
            summary=summary,
            reasons=reasons,
            suggestions=suggestions,
            raw="未配置 DEEPSEEK_API_KEY，以上结论由内置归因规则基于真实失败数据分析得出。",
            mocked=True,
            usage={"prompt_name": "failure_analysis", "elapsed_ms": 0.0, "total_tokens": 0},
        )

    def _mock_answer_question(self, question: str, stats: dict[str, Any]) -> QueryReportResponse:
        """规则兜底：直接对真实统计做排序聚合，再用自然语言表达。

        Args:
            question: 用户问题。
            stats: 结构化统计上下文。

        Returns:
            回答结果，``mocked=True``。
        """
        projects = stats.get("projects") or []
        top_failures = stats.get("top_failed_cases") or []
        summary = stats.get("summary") or {}

        lines: list[str] = []
        if projects:
            worst = max(projects, key=lambda item: item.get("failed", 0))
            best = max(projects, key=lambda item: item.get("pass_rate", 0.0))
            if worst.get("failed", 0) > 0:
                lines.append(
                    f"**失败最多的是「{worst.get('project_name')}」**，"
                    f"共失败 {worst.get('failed')} 条 / 执行 {worst.get('total')} 条，"
                    f"通过率 {worst.get('pass_rate')}%。"
                )
            else:
                lines.append(
                    f"统计窗口内**所有项目都没有失败用例**，共执行 {summary.get('total_cases', 0)} 条。"
                )
            if best.get("project_id") != worst.get("project_id"):
                lines.append(
                    f"表现最好的是「{best.get('project_name')}」，通过率 {best.get('pass_rate')}%。"
                )
            lines.append("")
            lines.append("各项目明细：")
            for item in sorted(projects, key=lambda x: x.get("failed", 0), reverse=True):
                lines.append(
                    f"- {item.get('project_name')}：通过 {item.get('passed')} / 失败 {item.get('failed')}"
                    f" / 通过率 {item.get('pass_rate')}%"
                )
        else:
            lines.append("统计窗口内还没有任何执行记录，先跑一次用例再看报告吧。")

        if top_failures:
            lines.append("")
            lines.append("失败次数最多的用例：")
            for item in top_failures[:5]:
                # 统计上下文里的失败分布是 {"name": 用例名, "value": 失败次数}
                lines.append(f"- {item.get('name')}：失败 {int(item.get('value') or 0)} 次")

        lines.append("")
        lines.append(
            f"> 统计口径：最近 {stats.get('days', 7)} 天，共 {summary.get('task_count', 0)} 个任务、"
            f"{summary.get('total_cases', 0)} 条用例，整体通过率 {summary.get('pass_rate', 0.0)}%。"
        )
        lines.append(
            "> 当前为 Mock 模式（未配置 DEEPSEEK_API_KEY），以上结论由规则聚合真实数据得出。"
        )

        return QueryReportResponse(
            question=question,
            answer="\n".join(lines),
            stats=stats,
            mocked=True,
            usage={"prompt_name": "report_qa", "elapsed_ms": 0.0, "total_tokens": 0},
        )


# 单例：AI 客户端内部有连接池，全局复用一个实例即可
ai_service = AIService()


def default_assertion_rules() -> list[AssertionRuleSchema]:
    """给新建用例提供的默认断言模板。

    Returns:
        默认断言规则列表。
    """
    return [
        AssertionRuleSchema(type="status_code", expected=200, name="状态码 200"),
        AssertionRuleSchema(type="response_time", expected=3000, name="响应时间小于 3s"),
    ]
