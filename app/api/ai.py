"""AI 能力路由：生成用例、失败分析、自然语言查报告、能力状态。

路由层只负责「取数据 + 调服务 + 存档」，提示词与模型交互全在 ``services/ai_service.py``。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.deps import CurrentUser, DbSession
from app.models import Task
from app.schemas.ai import (
    AIStatusOut,
    AnalysisResponse,
    AnalyzeRequest,
    GenerateCasesRequest,
    GenerateCasesResponse,
    QueryReportRequest,
    QueryReportResponse,
)
from app.services.ai_service import ai_service
from app.services.report_service import ReportService
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/ai", tags=["AI 能力"])


@router.get("/status", response_model=AIStatusOut, summary="AI 能力状态")
def ai_status(current_user: CurrentUser) -> AIStatusOut:
    """查询 AI 能力状态（前端据此提示当前是否处于 Mock 模式）。

    Args:
        current_user: 当前登录用户。

    Returns:
        AI 状态。
    """
    _ = current_user
    return ai_service.status()


@router.post("/generate-cases", response_model=GenerateCasesResponse, summary="AI 生成接口用例")
def generate_cases(
    payload: GenerateCasesRequest, current_user: CurrentUser
) -> GenerateCasesResponse:
    """根据接口信息生成用例（结果不会自动入库，由前端确认后调用导入接口）。

    Args:
        payload: 生成请求。
        current_user: 当前登录用户。

    Returns:
        生成的用例列表。模型不可用时返回规则兜底结果，``mocked=True``。
    """
    _ = current_user
    response = ai_service.generate_cases(payload)
    logger.info(
        "AI 生成用例完成: 条数={} mocked={} usage={}",
        len(response.cases),
        response.mocked,
        response.usage.get("total_tokens"),
    )
    return response


@router.post("/analyze-failure", response_model=AnalysisResponse, summary="AI 失败归因分析")
def analyze_failure(
    payload: AnalyzeRequest, db: DbSession, current_user: CurrentUser
) -> AnalysisResponse:
    """分析一条失败用例的根因，并把结论存到任务上。

    Args:
        payload: 分析请求。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        分析结果。

    Raises:
        HTTPException: 任务不存在、没有失败用例或指定下标越界。
    """
    _ = current_user
    task = db.get(Task, payload.task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {payload.task_id} 不存在"
        )

    failed_results = [item for item in task.results() if item.get("status") in {"failed", "error"}]
    if not failed_results:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="该任务没有失败用例，无需分析"
        )

    if payload.case_result_index is None:
        target = failed_results[0]
    else:
        if payload.case_result_index >= len(failed_results):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"失败用例只有 {len(failed_results)} 条，下标 {payload.case_result_index} 越界",
            )
        target = failed_results[payload.case_result_index]

    context: dict[str, Any] = {
        "task_id": task.id,
        "case_name": target.get("case_name"),
        "case_type": target.get("case_type", "api"),
        "message": target.get("message"),
        "traceback": target.get("traceback"),
        "assertions": target.get("assertions") or [],
        "response": target.get("response"),
        "steps": target.get("steps") or [],
    }
    if payload.include_request:
        context["request"] = target.get("request")

    response = ai_service.analyze_failure(context)

    # 落库：一次分析结果覆盖式保存（避免无限膨胀），前端可在报告页直接读到
    task.ai_analysis = (
        f"【{response.category}】{response.summary}\n\n"
        + "判断依据：\n"
        + "\n".join(f"- {item}" for item in response.reasons)
        + "\n\n修复建议：\n"
        + "\n".join(f"- {item}" for item in response.suggestions)
    )
    db.commit()
    return response


@router.post("/query-report", response_model=QueryReportResponse, summary="AI 自然语言查报告")
def query_report(
    payload: QueryReportRequest, db: DbSession, current_user: CurrentUser
) -> QueryReportResponse:
    """用自然语言查询测试报告。

    Args:
        payload: 查询请求。
        db: 数据库会话。
        current_user: 当前登录用户。

    Returns:
        自然语言回答与结构化统计上下文。

    Raises:
        HTTPException: 查询失败。
    """
    _ = current_user
    try:
        stats = ReportService(db).stats_context(days=payload.days)
    except Exception as exc:
        logger.exception("聚合报告统计失败: {}", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"聚合报告统计失败: {exc}"
        ) from exc
    return ai_service.answer_report_question(payload.question, stats)
