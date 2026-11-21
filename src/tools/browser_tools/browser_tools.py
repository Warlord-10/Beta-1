"""Browser tools for the web agent: text only, no screenshots.

The agent sees a page through ``browser_snapshot``: its interactive elements
(links, buttons, fields, ...) and headings, each with a ref like ``e15``.
Actions take a ref from the latest snapshot. ``browser_read`` gives the
page's text for reading content (prices, articles, results).

Clicks and submits that look like they buy, send, post or delete something
ask the user first.
"""

from __future__ import annotations

import functools
import re
from urllib.parse import urlparse

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from src.agents.autonomousagent.permissions import ALLOW
from src.agents.task_runner import TaskContext, no_user
from src.tools.browser_tools.session import browser

_ACTION_TIMEOUT_MS = 5_000
_NAVIGATION_TIMEOUT_MS = 30_000
# ~3-6k tokens. Bigger pages are cut off; `find` narrows them down.
_MAX_CHARS = 12_000

# Snapshot lines worth showing: what the agent can act on, plus headings for orientation.
_SNAPSHOT_ROLES = re.compile(
    r"^- (link|button|textbox|searchbox|combobox|checkbox|radio|switch|slider|tab|menuitem|option|heading)\b"
)
# Clicking one of these needs the user's OK.
_RISKY_CLICK = re.compile(
    r"\b(buy|pay|purchase|order|checkout|send|post|publish|tweet|reply|submit|delete|remove"
    r"|subscribe|unsubscribe|confirm|transfer|book)\b",
    re.IGNORECASE,
)
# Submitting text into one of these needs the user's OK.
_RISKY_FIELD = re.compile(r"\b(message|comment|reply|post|tweet|chat|email)\b", re.IGNORECASE)


def _browser_tool(fn):
    """Turn browser errors into results the agent can react to."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except PlaywrightTimeout:
            return "Timed out. The ref may be stale or the element hidden: take a new snapshot."
        except PlaywrightError as exc:
            return f"Browser error: {str(exc).splitlines()[0]}"
    return wrapper


def _cut(text: str, find: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if find:
        lines = [line for line in lines if find.lower() in line.lower()]
    text = "\n".join(lines) or "(nothing found)"
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + "\n… (cut off: pass `find` to narrow it down)"
    return text


async def _where(page: Page) -> str:
    return f"Now on: {await page.title()} ({page.url})"


async def _settle(page: Page) -> None:
    """Give a click or submit a moment to load whatever it triggers."""
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=_ACTION_TIMEOUT_MS)
    except PlaywrightTimeout:
        pass


def _element(page: Page, ref: str) -> Locator:
    return page.locator(f"aria-ref={ref}")


async def _label(element: Locator) -> str:
    text = await element.evaluate(
        "e => e.getAttribute('aria-label') || e.innerText || e.value || e.placeholder || e.name || ''",
        timeout=_ACTION_TIMEOUT_MS,
    )
    return " ".join(text.split())[:80]


async def _user_allows(runtime: ToolRuntime, page: Page, action: str) -> bool:
    ask = runtime.context.ask if runtime.context else no_user
    site = urlparse(page.url).netloc
    answer = await ask(f"The web agent wants to {action} on {site}. Allow it?", [ALLOW, "Deny"])
    return answer.strip().lower() == ALLOW.lower()


@tool
@_browser_tool
async def browser_open(url: str) -> str:
    """Open a URL in the browser. Take a snapshot next to see the page."""
    async with browser.use() as page:
        await page.goto(url, wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS)
        return await _where(page)


@tool
@_browser_tool
async def browser_snapshot(find: str = "") -> str:
    """List the page's links, buttons, fields and headings, each with a ref
    (e.g. e15) to use with the action tools. Refs change when the page changes:
    take a new snapshot after acting.

    Args:
        find: Optional text to search for. Searches everything on the page,
            text included (e.g. "points", "add to cart"), and shows only the
            matching lines.
    """
    async with browser.use() as page:
        snapshot = await page.locator("body").aria_snapshot(mode="ai")
        lines = [line.strip().replace(" [cursor=pointer]", "") for line in snapshot.splitlines()]
        if not find:   # the overview: only what can be acted on, plus headings
            lines = [line for line in lines if _SNAPSHOT_ROLES.match(line)]
        return f"{await _where(page)}\n{_cut(chr(10).join(lines), find)}"


@tool
@_browser_tool
async def browser_read(find: str = "") -> str:
    """Read the page's visible text: prices, results, article text, messages.

    Args:
        find: Optional text to show only matching lines.
    """
    async with browser.use() as page:
        text = await page.locator("body").inner_text(timeout=_ACTION_TIMEOUT_MS)
        return f"{await _where(page)}\n{_cut(text, find)}"


@tool
@_browser_tool
async def browser_click(ref: str, runtime: ToolRuntime[TaskContext]) -> str:
    """Click an element by its ref from the latest snapshot."""
    async with browser.use() as page:
        element = _element(page, ref)
        label = await _label(element)
        if _RISKY_CLICK.search(label) and not await _user_allows(runtime, page, f'click "{label}"'):
            return f'The user did not allow clicking "{label}".'
        await element.click(timeout=_ACTION_TIMEOUT_MS)
        await _settle(page)
        return f'Clicked "{label}". {await _where(page)}'


@tool
@_browser_tool
async def browser_type(ref: str, text: str, runtime: ToolRuntime[TaskContext], submit: bool = False) -> str:
    """Type into a field by its ref (replaces what's there).

    Args:
        ref: The field's ref from the latest snapshot.
        text: What to type.
        submit: Press Enter afterwards (e.g. to run a search).
    """
    async with browser.use() as page:
        element = _element(page, ref)
        label = await _label(element)
        if submit and _RISKY_FIELD.search(label) and not await _user_allows(
            runtime, page, f'send "{text[:80]}" via "{label}"'
        ):
            return "The user did not allow sending this."
        await element.fill(text, timeout=_ACTION_TIMEOUT_MS)
        if submit:
            await element.press("Enter", timeout=_ACTION_TIMEOUT_MS)
            await _settle(page)
        return f'Typed into "{label}". {await _where(page)}'


@tool
@_browser_tool
async def browser_select(ref: str, option: str) -> str:
    """Choose an option in a dropdown by its ref and the option's visible text."""
    async with browser.use() as page:
        await _element(page, ref).select_option(label=option, timeout=_ACTION_TIMEOUT_MS)
        return f'Selected "{option}". {await _where(page)}'


@tool
@_browser_tool
async def browser_press(key: str) -> str:
    """Press a key on the page, e.g. Enter, Escape, Tab, ArrowDown, PageDown."""
    async with browser.use() as page:
        await page.keyboard.press(key)
        await _settle(page)
        return f"Pressed {key}. {await _where(page)}"


@tool
@_browser_tool
async def browser_back() -> str:
    """Go back to the previous page."""
    async with browser.use() as page:
        await page.go_back(wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS)
        return await _where(page)


@tool
@_browser_tool
async def browser_hand_over(reason: str, runtime: ToolRuntime[TaskContext]) -> str:
    """Show the browser to the user for something only they can do: log in,
    solve a captcha, enter a 2FA code. Waits until they reply. Never ask the
    user for passwords in chat; they type them in the browser window.

    Args:
        reason: What the user should do, e.g. "Please log in to amazon.in".
    """
    ask = runtime.context.ask if runtime.context else no_user
    async with browser.use(headless=False) as page:
        answer = await ask(f"{reason}. The browser window is open: reply when you're done.", ["Done", "Cancel"])
        return f"The user replied: {answer}. {await _where(page)}"


BROWSER_TOOLS = [
    browser_open,
    browser_snapshot,
    browser_read,
    browser_click,
    browser_type,
    browser_select,
    browser_press,
    browser_back,
    browser_hand_over,
]
