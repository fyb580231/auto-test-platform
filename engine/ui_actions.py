"""Playwright UI 动作封装：打开 / 点击 / 输入 / 断言 / 失败截图。

设计要点：
1. Playwright 采用**同步 API**，与 pytest 的同步用例模型天然契合，无需 async 插件；
2. 浏览器实例在 `UIPlayer` 生命周期内复用，避免每条用例都冷启动浏览器；
3. 任一步骤失败立即截屏并把截图路径带进 `UIStepResult`，由上层挂到 Allure 报告；
4. Playwright 未安装时给出**可操作的**报错提示，而不是一句 ImportError。
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:  # pragma: no cover
    from playwright.sync_api import Browser, Page, Playwright

# 支持的步骤动作
ACTION_OPEN = "open"
ACTION_CLICK = "click"
ACTION_INPUT = "input"
ACTION_ASSERT_VISIBLE = "assert_visible"
ACTION_ASSERT_TEXT = "assert_text"
ACTION_ASSERT_URL = "assert_url"
ACTION_WAIT = "wait"
ACTION_SELECT = "select"
ACTION_HOVER = "hover"
ACTION_SCREENSHOT = "screenshot"
ACTION_PRESS = "press"
ACTION_ASSERT_VALUE = "assert_value"

SUPPORTED_ACTIONS: frozenset[str] = frozenset(
    {
        ACTION_OPEN,
        ACTION_CLICK,
        ACTION_INPUT,
        ACTION_ASSERT_VISIBLE,
        ACTION_ASSERT_TEXT,
        ACTION_ASSERT_URL,
        ACTION_WAIT,
        ACTION_SELECT,
        ACTION_HOVER,
        ACTION_SCREENSHOT,
        ACTION_PRESS,
        ACTION_ASSERT_VALUE,
    }
)

_VIEWPORT = {"width": 1440, "height": 900}
DEFAULT_STEP_TIMEOUT_MS = 15_000


class UIActionError(AssertionError):
    """UI 步骤执行失败（继承 AssertionError，pytest 会标记为用例失败）。"""


@dataclass(slots=True)
class UIStep:
    """一个 UI 步骤。

    Attributes:
        action: 动作类型，取值见 ``SUPPORTED_ACTIONS``。
        selector: 元素选择器（CSS / text= / xpath= 均可）。
        value: 输入值或断言期望值。
        timeout: 该步骤超时毫秒数。
        name: 步骤别名，用于报告展示。
    """

    action: str
    selector: str | None = None
    value: str | None = None
    timeout: int = DEFAULT_STEP_TIMEOUT_MS
    name: str | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> UIStep:
        """从字典构造步骤。

        Args:
            raw: 原始步骤配置。

        Returns:
            步骤对象。
        """
        return cls(
            action=str(raw.get("action", "")).strip().lower(),
            selector=raw.get("selector") or raw.get("target"),
            value=None if raw.get("value") is None else str(raw.get("value")),
            timeout=int(raw.get("timeout") or DEFAULT_STEP_TIMEOUT_MS),
            name=raw.get("name"),
        )

    @property
    def label(self) -> str:
        """步骤的可读描述。"""
        if self.name:
            return self.name
        parts = [self.action]
        if self.selector:
            parts.append(f"selector={self.selector}")
        if self.value is not None:
            parts.append(f"value={self.value}")
        return " ".join(parts)


@dataclass(slots=True)
class UIStepResult:
    """单个 UI 步骤的执行结果。

    Attributes:
        label: 步骤描述。
        action: 动作类型。
        passed: 是否通过。
        duration_ms: 耗时毫秒。
        message: 失败原因。
        screenshots: 产生的截图路径列表。
    """

    label: str
    action: str
    passed: bool
    duration_ms: float
    message: str = ""
    screenshots: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。

        Returns:
            字典结构。
        """
        return {
            "label": self.label,
            "action": self.action,
            "passed": self.passed,
            "duration_ms": round(self.duration_ms, 2),
            "message": self.message,
            "screenshots": self.screenshots,
        }


class UIPlayer:
    """Playwright 播放器：按步骤编排驱动一个真实浏览器。

    使用方式::

        with UIPlayer(base_url="https://www.saucedemo.com", screenshot_dir="reports/screenshots/x") as player:
            results = player.run_steps(steps)

    Attributes:
        base_url: 相对路径步骤的基地址。
        headless: 是否无头模式。
        screenshot_dir: 截图输出目录。
        slow_mo: 每步操作放慢的毫秒数，调试用。
    """

    def __init__(
        self,
        base_url: str = "",
        headless: bool = True,
        screenshot_dir: str | Path = "reports/screenshots",
        slow_mo: int = 0,
        browser_type: str = "chromium",
        viewport: Mapping[str, int] | None = None,
    ) -> None:
        """初始化播放器。

        Args:
            base_url: 基础地址。
            headless: 是否无头运行。
            screenshot_dir: 截图目录。
            slow_mo: 操作放慢毫秒数。
            browser_type: 浏览器类型（chromium / firefox / webkit）。
            viewport: 视口尺寸。
        """
        self.base_url = (base_url or "").rstrip("/")
        self.headless = headless
        self.screenshot_dir = Path(screenshot_dir)
        self.slow_mo = slow_mo
        self.browser_type = browser_type
        self.viewport = dict(viewport or _VIEWPORT)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._step_results: list[UIStepResult] = []

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def start(self) -> UIPlayer:
        """启动浏览器。

        Returns:
            self，便于链式调用。

        Raises:
            RuntimeError: Playwright 未安装或浏览器内核未下载。
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - 环境问题
            raise RuntimeError(
                "未安装 Playwright。请执行 `pip install playwright` 后运行 `playwright install chromium`。"
            ) from exc

        try:
            self._playwright = sync_playwright().start()
            launcher = getattr(self._playwright, self.browser_type)
            self._browser = launcher.launch(headless=self.headless, slow_mo=self.slow_mo)
            context = self._browser.new_context(viewport=self.viewport, ignore_https_errors=True)
            self._page = context.new_page()
            self._page.set_default_timeout(DEFAULT_STEP_TIMEOUT_MS)
        except Exception as exc:
            self.close()
            raise RuntimeError(
                f"启动浏览器失败: {exc}。若提示缺少可执行文件，请运行 `playwright install chromium`。"
            ) from exc
        logger.info("UI 播放器已启动: browser={} headless={}", self.browser_type, self.headless)
        return self

    def close(self) -> None:
        """关闭浏览器并释放资源（幂等，可重复调用）。"""
        for closer in (
            getattr(self._browser, "close", None),
            getattr(self._playwright, "stop", None),
        ):
            if callable(closer):
                try:
                    closer()
                except Exception as exc:  # noqa: BLE001 - 清理阶段吞掉异常，保证 close() 幂等
                    logger.debug("释放 UI 资源时忽略异常: {}", exc)
        self._browser = None
        self._playwright = None
        self._page = None

    def __enter__(self) -> UIPlayer:
        """进入上下文，自动启动浏览器。"""
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        """退出上下文，自动关闭浏览器。"""
        self.close()

    # ------------------------------------------------------------------ #
    # 步骤执行
    # ------------------------------------------------------------------ #
    def run_steps(self, steps: list[UIStep], case_name: str = "ui_case") -> list[UIStepResult]:
        """按顺序执行全部步骤，遇错立即停止并截图。

        Args:
            steps: 步骤列表。
            case_name: 用例名称，用于截图文件命名。

        Returns:
            步骤执行结果列表。

        Raises:
            UIActionError: 某一步骤失败（含断言失败与元素未找到）。
        """
        if self._page is None:
            raise RuntimeError("UIPlayer 尚未启动，请先调用 start() 或使用 with 语句。")

        self._step_results = []
        for index, raw_step in enumerate(steps, start=1):
            step_obj = raw_step if isinstance(raw_step, UIStep) else UIStep.from_dict(raw_step)
            started = time.perf_counter()
            try:
                self._execute(step_obj)
            except Exception as exc:
                duration = (time.perf_counter() - started) * 1000
                shot = self._capture(f"{case_name}_step{index}_failed")
                message = f"步骤 {index} [{step_obj.label}] 执行失败: {exc}"
                result = UIStepResult(
                    label=step_obj.label,
                    action=step_obj.action,
                    passed=False,
                    duration_ms=duration,
                    message=message,
                    screenshots=[str(shot)] if shot else [],
                )
                self._step_results.append(result)
                logger.error(message)
                raise UIActionError(message) from exc
            duration = (time.perf_counter() - started) * 1000
            self._step_results.append(
                UIStepResult(
                    label=step_obj.label,
                    action=step_obj.action,
                    passed=True,
                    duration_ms=duration,
                )
            )
            logger.debug("UI 步骤通过: {}", step_obj.label)
        return list(self._step_results)

    @property
    def step_results(self) -> list[UIStepResult]:
        """已执行的步骤结果。"""
        return list(self._step_results)

    def screenshot(self, name: str) -> Path | None:
        """主动截屏（供用例显式调用）。

        Args:
            name: 截图名称。

        Returns:
            截图路径；失败时返回 None。
        """
        return self._capture(name)

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #
    def _execute(self, step_obj: UIStep) -> None:
        """执行单个步骤。

        Args:
            step_obj: 步骤对象。

        Raises:
            ValueError: 动作类型不支持或缺少必填参数。
        """
        page = self._page
        assert page is not None  # 由 run_steps 保证

        if step_obj.action not in SUPPORTED_ACTIONS:
            raise ValueError(f"不支持的 UI 动作: {step_obj.action}")

        if step_obj.action == ACTION_OPEN:
            target = self._absolute(step_obj.value or step_obj.selector or "")
            page.goto(target, wait_until="domcontentloaded", timeout=step_obj.timeout)
            return

        if step_obj.action == ACTION_WAIT:
            seconds = float(step_obj.value or 1)
            time.sleep(seconds)
            return

        selector = step_obj.selector
        if not selector:
            raise ValueError(f"动作 {step_obj.action} 缺少 selector")

        if step_obj.action == ACTION_CLICK:
            page.click(selector, timeout=step_obj.timeout)
        elif step_obj.action == ACTION_INPUT:
            page.fill(selector, step_obj.value or "", timeout=step_obj.timeout)
        elif step_obj.action == ACTION_SELECT:
            page.select_option(selector, step_obj.value or "", timeout=step_obj.timeout)
        elif step_obj.action == ACTION_HOVER:
            page.hover(selector, timeout=step_obj.timeout)
        elif step_obj.action == ACTION_PRESS:
            page.press(selector, step_obj.value or "Enter", timeout=step_obj.timeout)
        elif step_obj.action == ACTION_ASSERT_VISIBLE:
            if not page.is_visible(selector):
                raise AssertionError(f"元素不可见: {selector}")
        elif step_obj.action == ACTION_ASSERT_TEXT:
            actual = page.inner_text(selector)
            expected = step_obj.value or ""
            if expected not in actual:
                raise AssertionError(f"文本断言失败: 期望包含 {expected!r}，实际 {actual!r}")
        elif step_obj.action == ACTION_ASSERT_VALUE:
            actual = page.input_value(selector)
            if (step_obj.value or "") != actual:
                raise AssertionError(f"输入值断言失败: 期望 {step_obj.value!r}，实际 {actual!r}")
        elif step_obj.action == ACTION_ASSERT_URL:
            actual_url = page.url
            if not re.search(step_obj.value or "", actual_url):
                raise AssertionError(
                    f"URL 断言失败: 期望匹配 {step_obj.value!r}，实际 {actual_url!r}"
                )
        elif step_obj.action == ACTION_SCREENSHOT:
            self._capture(step_obj.value or step_obj.name or "manual")

    def _absolute(self, url: str) -> str:
        """把相对路径转换为绝对 URL。

        Args:
            url: 相对或绝对地址。

        Returns:
            绝对 URL。
        """
        if url.startswith(("http://", "https://")):
            return url
        if not self.base_url:
            return url
        return f"{self.base_url}/{url.lstrip('/')}"

    def _capture(self, name: str) -> Path | None:
        """截屏并落盘。

        Args:
            name: 截图名称。

        Returns:
            截图路径；失败时返回 None。
        """
        if self._page is None:
            return None
        try:
            self.screenshot_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r"[^\w\-.]+", "_", name)[:120]
            path = self.screenshot_dir / f"{safe_name}.png"
            self._page.screenshot(path=str(path), full_page=True)
            logger.info("已保存失败截图: {}", path)
            return path
        except Exception as exc:  # noqa: BLE001 - 截图失败不影响主流程，只降级为「无截图」
            logger.warning("截屏失败: {}", exc)
            return None
