"""The web agent's browser: one Brave window, shared by every browser tool.

- Started on the first browser tool call, closed after ``IDLE_CLOSE_S`` without
  one, so it uses no RAM while unused (~240 MB while open).
- Headless by default, with images, video and fonts blocked: the agent reads
  the page as text, so they would only cost time and memory.
- Reopened in a visible window when the user has to step in (log in, captcha),
  then headless again, on the same page.
- A persistent profile in ``data/browser_profile`` keeps logins between runs.
  It is separate from the user's own Brave profile.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import BrowserContext, Page, Playwright, Route, async_playwright

from src.config.logger import get_logger

logger = get_logger("tools.browser")

# ponytail: Brave's default install path; move to settings if it ever varies.
BROWSER_PATH = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
PROFILE_DIR = Path(__file__).resolve().parents[3] / "data" / "browser_profile"
IDLE_CLOSE_S = 180

_BLOCKED_RESOURCES = {"image", "media", "font"}
# Background features the agent never needs. Site isolation stays on: it is
# what keeps one website from reading another's data.
_ARGS = ["--no-first-run", "--disable-sync", "--disable-background-networking", "--mute-audio"]


async def _block_heavy(route: Route) -> None:
    if route.request.resource_type in _BLOCKED_RESOURCES:
        await route.abort()
    else:
        await route.continue_()


class BrowserSession:
    def __init__(self):
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._headless = True
        self._last_url: str | None = None   # reopened after a headless/visible switch
        self._lock = asyncio.Lock()          # one tool at a time on the page
        self._idle_timer: asyncio.TimerHandle | None = None

    @asynccontextmanager
    async def use(self, headless: bool = True):
        """The browser's page, opened (or switched to visible/headless) as needed."""
        async with self._lock:
            if self._idle_timer:
                self._idle_timer.cancel()
            try:
                yield await self._page(headless)
            finally:
                self._idle_timer = asyncio.get_running_loop().call_later(
                    IDLE_CLOSE_S, lambda: asyncio.ensure_future(self.close())
                )

    async def close(self) -> None:
        async with self._lock:
            await self._close()

    async def _page(self, headless: bool) -> Page:
        if self._context and self._headless != headless:
            await self._close()
        if self._context is None:
            await self._launch(headless)
            if self._last_url:
                await self._context.pages[0].goto(self._last_url, wait_until="domcontentloaded")
        return self._context.pages[0]

    async def _launch(self, headless: bool) -> None:
        logger.info("Starting browser (%s)", "headless" if headless else "visible")
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            PROFILE_DIR,
            executable_path=BROWSER_PATH,
            headless=headless,
            args=_ARGS,
        )
        if headless:   # the user needs images (e.g. a captcha) in the visible window
            await self._context.route("**/*", _block_heavy)
        self._headless = headless

    async def _close(self) -> None:
        if self._context is None:
            return
        self._last_url = self._context.pages[0].url if self._context.pages else None
        await self._context.close()
        await self._playwright.stop()
        self._context = self._playwright = None
        logger.info("Browser closed")


browser = BrowserSession()
