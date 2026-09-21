"""Pydantic 模型包：统一导出。"""

from __future__ import annotations

from app.schemas.ai import (
    AIStatusOut,
    AnalysisResponse,
    AnalyzeRequest,
    GenerateCasesRequest,
    GenerateCasesResponse,
    QueryReportRequest,
    QueryReportResponse,
)
from app.schemas.common import (
    AssertionRuleSchema,
    ExtractRuleSchema,
    MessageResponse,
    ORMModel,
    PageResult,
    UIStepSchema,
)
from app.schemas.dashboard import (
    DashboardStatsOut,
    DashboardSummary,
    NameValueStat,
    ProjectStat,
    TrendPoint,
)
from app.schemas.environment import (
    EnvironmentCreateRequest,
    EnvironmentOut,
    EnvironmentUpdateRequest,
)
from app.schemas.project import ProjectCreateRequest, ProjectOut, ProjectUpdateRequest
from app.schemas.task import TaskDetailOut, TaskLogOut, TaskOut, TaskQuery
from app.schemas.testcase import (
    ImportCasesRequest,
    RunCasesRequest,
    TestCaseCreateRequest,
    TestCaseOut,
    TestCaseUpdateRequest,
)
from app.schemas.testsuite import (
    RunSuiteRequest,
    TestSuiteCreateRequest,
    TestSuiteOut,
    TestSuiteUpdateRequest,
)
from app.schemas.user import (
    ChangePasswordRequest,
    TokenOut,
    UserLoginRequest,
    UserOut,
    UserRegisterRequest,
)

__all__ = [
    "AIStatusOut",
    "AnalysisResponse",
    "AnalyzeRequest",
    "AssertionRuleSchema",
    "ChangePasswordRequest",
    "DashboardStatsOut",
    "DashboardSummary",
    "EnvironmentCreateRequest",
    "EnvironmentOut",
    "EnvironmentUpdateRequest",
    "ExtractRuleSchema",
    "GenerateCasesRequest",
    "GenerateCasesResponse",
    "ImportCasesRequest",
    "MessageResponse",
    "NameValueStat",
    "ORMModel",
    "PageResult",
    "ProjectCreateRequest",
    "ProjectOut",
    "ProjectStat",
    "ProjectUpdateRequest",
    "QueryReportRequest",
    "QueryReportResponse",
    "RunCasesRequest",
    "RunSuiteRequest",
    "TaskDetailOut",
    "TaskLogOut",
    "TaskOut",
    "TaskQuery",
    "TestCaseCreateRequest",
    "TestCaseOut",
    "TestCaseUpdateRequest",
    "TestSuiteCreateRequest",
    "TestSuiteOut",
    "TestSuiteUpdateRequest",
    "TokenOut",
    "TrendPoint",
    "UIStepSchema",
    "UserLoginRequest",
    "UserOut",
    "UserRegisterRequest",
]
