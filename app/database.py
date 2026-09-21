"""数据库连接与会话管理（SQLAlchemy 2.0 声明式风格）。

约定：
* 所有数据访问都必须通过 ``get_db`` 依赖注入的 ``Session``，禁止在业务代码里裸写 SQL；
* ``SessionLocal`` 关闭了 ``expire_on_commit``，避免返回 ORM 对象后触发懒加载导致 N+1；
* SQLite 打开 ``check_same_thread=False``，让 FastAPI 的线程池可以安全复用连接。
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def now() -> datetime:
    """统一的当前时间获取方式（本地时间、naive）。

    统一入口的意义在于：以后要切 UTC 或注入测试时钟，只需要改这一个函数。

    Returns:
        当前本地时间。
    """
    return datetime.now()


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    def to_dict(self) -> dict[str, Any]:
        """把 ORM 对象转换成字典（仅包含已加载的列）。

        Returns:
            列名到值的映射。
        """
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


def _build_engine() -> Engine:
    """根据配置创建数据库引擎。

    Returns:
        SQLAlchemy 引擎实例。
    """
    if settings.is_sqlite:
        engine = create_engine(
            settings.database_url,
            echo=False,
            future=True,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, _record: Any) -> None:
            """为 SQLite 打开 WAL 与外键约束（默认是关闭的）。

            Args:
                dbapi_connection: DBAPI 连接对象。
                _record: 连接记录（未使用）。
            """
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    return create_engine(
        settings.database_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


engine: Engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：提供一个请求级数据库会话。

    Yields:
        数据库会话；请求结束后自动关闭。
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """建表（幂等）。

    项目规模不大，直接用 ``create_all``；生产环境如需版本化迁移可接入 Alembic。

    Returns:
        None
    """
    # 导入模型以触发注册（必须在 create_all 之前）
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("数据库初始化完成: {}", settings.database_url)


__all__ = [
    "Base",
    "DateTime",
    "Mapped",
    "Session",
    "SessionLocal",
    "engine",
    "get_db",
    "init_db",
    "mapped_column",
    "now",
]
