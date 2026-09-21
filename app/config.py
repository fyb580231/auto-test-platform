"""全局配置：基于 pydantic-settings 从 .env 读取，支持 SQLite / MySQL 双引擎切换。

设计上把「配置读取」收敛到这一个模块，其他模块一律 ``from app.config import settings``，
禁止在各处散落 ``os.getenv``——这样环境变量的来源与默认值只有一处，便于审计与文档化。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（app/ 的上一级）
BASE_DIR: Path = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """平台全部可配置项。

    Attributes:
        app_name: 应用名称。
        app_version: 应用版本。
        debug: 是否开启调试模式（会返回更详细的错误信息）。
        host: 监听地址。
        port: 监听端口。
        cors_origins: 允许跨域的前端地址，逗号分隔。
    """

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 应用 ----------
    app_name: str = "auto-test-platform"
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # ---------- 数据库 ----------
    sqlite_path: str = "./data/auto_test_platform.db"
    db_type: Literal["sqlite", "mysql"] = "sqlite"
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "auto_test_platform"

    # ---------- 认证 ----------
    jwt_secret: str = "dev-only-secret-please-change"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # ---------- 默认管理员 ----------
    default_admin_username: str = "admin"
    default_admin_password: str = "admin123"

    # ---------- AI ----------
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4"
    ai_enabled: bool = True
    ai_mock: bool = False
    ai_timeout_seconds: int = 30
    ai_max_retries: int = 2
    ai_max_tokens: int = 4096
    ai_max_log_chars: int = 6000

    # ---------- 执行引擎 ----------
    pytest_timeout_seconds: int = 300
    pytest_max_workers: int = 1
    default_retry_times: int = 2
    # 同时执行的任务数上限（任务级并发；每个任务一个独立 pytest 子进程）
    max_concurrent_tasks: int = 4
    allure_auto_generate: bool = True
    allure_command: str = "allure"

    # ---------- 日志 ----------
    log_level: str = "INFO"
    log_dir: str = "./reports/logs"
    log_retention_days: int = 14

    # ------------------------------------------------------------------ #
    # 派生属性
    # ------------------------------------------------------------------ #
    @property
    def database_url(self) -> str:
        """SQLAlchemy 连接串。

        Returns:
            根据 ``db_type`` 生成的连接串；SQLite 使用绝对路径，避免受启动目录影响。
        """
        if self.db_type == "mysql":
            return (
                f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
                f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
            )
        sqlite_file = Path(self.sqlite_path)
        if not sqlite_file.is_absolute():
            sqlite_file = (BASE_DIR / sqlite_file).resolve()
        return f"sqlite:///{sqlite_file.as_posix()}"

    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的跨域配置解析成列表。

        Returns:
            域名列表。
        """
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def is_sqlite(self) -> bool:
        """当前是否使用 SQLite。"""
        return self.db_type == "sqlite"

    @property
    def ai_available(self) -> bool:
        """AI 能力是否可用（关闭开关或缺少 Key 时降级为 Mock）。

        Returns:
            True 表示可以发起真实模型调用。
        """
        if not self.ai_enabled or self.ai_mock:
            return False
        return bool(self.deepseek_api_key.strip())

    @property
    def sqlite_file_path(self) -> Path:
        """SQLite 数据库文件绝对路径。"""
        path = Path(self.sqlite_path)
        return path if path.is_absolute() else (BASE_DIR / path).resolve()

    @property
    def reports_dir(self) -> Path:
        """报告产物根目录。"""
        return BASE_DIR / "reports"

    @property
    def logs_dir(self) -> Path:
        """日志目录（相对路径基于项目根目录）。"""
        path = Path(self.log_dir)
        return path if path.is_absolute() else (BASE_DIR / path).resolve()

    @property
    def data_dir(self) -> Path:
        """内置演示数据目录。"""
        return BASE_DIR / "data"

    def ensure_directories(self) -> None:
        """确保运行时目录存在（数据库、日志、报告）。

        Returns:
            None
        """
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        if self.is_sqlite:
            self.sqlite_file_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局配置单例。

    Returns:
        配置对象。
    """
    settings = Settings()
    settings.ensure_directories()
    return settings


settings: Settings = get_settings()
