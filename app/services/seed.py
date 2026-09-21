"""首次启动初始化：创建默认管理员与内置演示数据。

「clone 下来就能用」的关键一环。初始化逻辑必须**幂等**：
服务反复重启不会重复插入数据，也不会覆盖用户后来改过的内容。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import (
    CaseType,
    Environment,
    Project,
    TestCase,
    TestSuite,
    User,
    UserRole,
)
from app.utils.jwt import hash_password
from app.utils.logger import get_logger
from engine.data_loader import DataLoader, DataLoadError

logger = get_logger(__name__)

DEMO_PROJECT_NAME = "演示项目 · httpbin & saucedemo"
DEMO_PROJECT_DESCRIPTION = (
    "内置演示项目：接口用例指向 httpbin.org，UI 用例指向 saucedemo.com，"
    "均为公开可用的练习站点，无需任何内部系统即可跑通全流程。"
)

# 演示环境：(名称, base_url, 变量, 是否默认, 备注)
_DEMO_ENVIRONMENTS: list[tuple[str, str, dict[str, Any], bool, str]] = [
    (
        "dev",
        "https://httpbin.org",
        {"test_username": "test_user_001", "test_password": "Test@123456"},
        True,
        "接口测试环境（httpbin.org 公有练习服务）",
    ),
    (
        "staging",
        "https://httpbin.org",
        {},
        False,
        "预发环境占位配置：把 base_url 换成你自己的预发地址即可复用全部用例",
    ),
    (
        "ui-demo",
        "https://www.saucedemo.com",
        {
            "standard_user": "standard_user",
            "locked_user": "locked_out_user",
            "password": "secret_sauce",
        },
        False,
        "UI 自动化环境（saucedemo.com 公有练习电商站）",
    ),
]

# 用例集中引用的 YAML 逻辑 ID
_SMOKE_CASE_IDS = ["api_001", "api_002", "api_003", "api_004"]
_UI_SUITE_CASE_IDS = ["ui_001", "ui_002", "ui_003", "ui_004", "ui_005"]


def bootstrap() -> None:
    """执行全部初始化动作（幂等）。

    Returns:
        None
    """
    with SessionLocal() as db:
        _ensure_default_users(db)
        _ensure_demo_project(db)


def _ensure_default_users(db: Session) -> None:
    """创建默认管理员账号。

    Args:
        db: 数据库会话。

    Returns:
        None
    """
    exists = db.query(User).filter(User.username == settings.default_admin_username).one_or_none()
    if exists is not None:
        return
    admin = User(
        username=settings.default_admin_username,
        hashed_password=hash_password(settings.default_admin_password),
        email=None,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    logger.info(
        "已创建默认管理员账号: {} / {}（请在生产环境中及时修改密码）",
        settings.default_admin_username,
        settings.default_admin_password,
    )


def _ensure_demo_project(db: Session) -> None:
    """创建演示项目及其环境、用例、用例集。

    Args:
        db: 数据库会话。

    Returns:
        None
    """
    if db.query(Project).filter(Project.name == DEMO_PROJECT_NAME).one_or_none() is not None:
        logger.info("演示项目已存在，跳过初始化")
        return

    owner = db.query(User).filter(User.username == settings.default_admin_username).one_or_none()
    project = Project(
        name=DEMO_PROJECT_NAME,
        description=DEMO_PROJECT_DESCRIPTION,
        owner_id=owner.id if owner else None,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    environments = _create_environments(db, project)
    api_cases = _create_cases(db, project, "demo_api_cases.yaml", owner)
    ui_cases = _create_cases(db, project, "demo_ui_cases.yaml", owner)
    _create_suites(db, project, environments, api_cases, ui_cases)

    logger.info(
        "演示项目初始化完成: 环境 {} 个 / 用例 {} 条 / 用例集 {} 个",
        len(environments),
        len(api_cases) + len(ui_cases),
        db.query(TestSuite).filter(TestSuite.project_id == project.id).count(),
    )


def _create_environments(db: Session, project: Project) -> dict[str, Environment]:
    """创建演示环境。

    Args:
        db: 数据库会话。
        project: 项目对象。

    Returns:
        环境名到环境对象的映射。
    """
    created: dict[str, Environment] = {}
    for name, base_url, variables, is_default, description in _DEMO_ENVIRONMENTS:
        environment = Environment(
            project_id=project.id,
            name=name,
            base_url=base_url,
            headers={"Content-Type": "application/json"},
            variables=variables,
            verify=True,
            timeout=30,
            is_default=is_default,
            description=description,
        )
        db.add(environment)
        created[name] = environment
    db.commit()
    for environment in created.values():
        db.refresh(environment)
    return created


def _create_cases(
    db: Session, project: Project, file_name: str, owner: User | None
) -> dict[str, TestCase]:
    """从 YAML 文件导入用例。

    Args:
        db: 数据库会话。
        project: 项目对象。
        file_name: data/ 目录下的文件名。
        owner: 创建人。

    Returns:
        YAML 逻辑 ID 到用例对象的映射。
    """
    file_path = settings.data_dir / file_name
    if not file_path.is_file():
        logger.warning("演示用例文件不存在，跳过: {}", file_path)
        return {}

    try:
        loader = DataLoader(file_path).load()
    except DataLoadError as exc:
        logger.error("演示用例文件解析失败: {}", exc)
        return {}

    created: dict[str, TestCase] = {}
    for raw in loader.cases:
        logical_id = str(raw.get("id") or raw.get("name") or "")
        case = _build_case(project.id, raw, owner)
        db.add(case)
        created[logical_id] = case
    db.commit()
    for case in created.values():
        db.refresh(case)

    # 二次遍历：解析 setup_ref 指向的前置用例（此时所有用例都已拿到数据库 ID）
    touched = False
    for raw in loader.cases:
        setup_ref = raw.get("setup_ref")
        if not setup_ref:
            continue
        case = created.get(str(raw.get("id") or ""))
        setup_case = created.get(str(setup_ref))
        if case is not None and setup_case is not None:
            case.setup_case_id = setup_case.id
            touched = True
    if touched:
        db.commit()
    return created


def _build_case(project_id: int, raw: dict[str, Any], owner: User | None) -> TestCase:
    """把 YAML 中的一条用例转换成 ORM 对象。

    Args:
        project_id: 项目 ID。
        raw: YAML 用例字典。
        owner: 创建人。

    Returns:
        用例 ORM 对象。
    """
    case_type = str(raw.get("case_type") or CaseType.API.value).lower()
    return TestCase(
        project_id=project_id,
        name=str(raw.get("name") or "未命名用例"),
        case_type=case_type,
        description=raw.get("description"),
        tags=[str(tag) for tag in raw.get("tags") or []],
        method=str(raw.get("method") or "GET").upper(),
        url=str(raw.get("url") or ""),
        headers=raw.get("headers") or {},
        params=raw.get("params") or {},
        body=raw.get("body"),
        form=raw.get("form") or {},
        extract=raw.get("extract") or [],
        steps=raw.get("steps") or [],
        assertions=raw.get("assertions") or [],
        enabled=True,
        created_by=owner.id if owner else None,
    )


def _create_suites(
    db: Session,
    project: Project,
    environments: dict[str, Environment],
    api_cases: dict[str, TestCase],
    ui_cases: dict[str, TestCase],
) -> None:
    """创建演示用例集。

    Args:
        db: 数据库会话。
        project: 项目对象。
        environments: 环境映射。
        api_cases: 接口用例映射。
        ui_cases: UI 用例映射。

    Returns:
        None
    """
    dev_env = environments.get("dev")
    ui_env = environments.get("ui-demo")

    suites: list[TestSuite] = [
        TestSuite(
            project_id=project.id,
            name="接口冒烟集",
            description="核心链路冒烟，全部用例预期通过；已配置每天 02:00 自动执行。",
            case_ids=[api_cases[cid].id for cid in _SMOKE_CASE_IDS if cid in api_cases],
            environment_id=dev_env.id if dev_env else None,
            cron_expression="0 2 * * *",
            retry_times=2,
            enabled=True,
        ),
        TestSuite(
            project_id=project.id,
            name="接口全量回归集",
            description=(
                "全部接口用例（含 1 条「故意失败」演示用例）。"
                "想跑出全绿结果时，把这条演示用例从用例集里移除即可。"
            ),
            case_ids=[case.id for case in api_cases.values()],
            environment_id=dev_env.id if dev_env else None,
            cron_expression=None,
            retry_times=2,
            enabled=True,
        ),
        TestSuite(
            project_id=project.id,
            name="UI 核心流程集",
            description="saucedemo 登录、加购、下单、异常登录共 5 条 UI 用例，执行前需安装 playwright 浏览器内核。",
            case_ids=[ui_cases[cid].id for cid in _UI_SUITE_CASE_IDS if cid in ui_cases],
            environment_id=ui_env.id if ui_env else None,
            cron_expression=None,
            retry_times=1,
            enabled=True,
        ),
    ]
    db.add_all(suites)
    db.commit()
