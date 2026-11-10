import os
import re
import random
import json
from datetime import datetime
from playwright.async_api import async_playwright
from langchain_groq import ChatGroq

from app.utils.human import human_delay
from app.pages.login_page import handleLogin
from app.pages.jobs_page import openJobPage, searchJobs
from app.pages.jobs_page import selectJobInBulk, _seen_job_keys
from app.pages.apply_page import applyInBulk
from app.utils.report import save_and_print_report
from app.utils.applied_log import append_applied, read_applied_log
from app.utils.daily_report import refresh as refresh_dashboard
from app.utils.error_log import log_error
from app.utils.diagnostics import Diagnostics, setup_file_logging
from app.config.config import (
    DAILY_APPLY_LIMIT,
    MAX_BATCH_SIZE,
    PREFERRED_ROLES,
    PREFERRED_LOCATIONS,
    HEADLESS,
    SLOW_MO_MS,
    VIEWPORT_WIDTH,
    VIEWPORT_HEIGHT,
    STORAGE_STATE_PATH,
    DIAGNOSTICS_DIR,
    SCREENSHOT_ON_ERROR,
)

# Give up after this many consecutive cycles where no new job could be selected.
MAX_EMPTY_CYCLES = 3

# Relaunch the browser this many times when Chromium dies mid-run
# (TargetClosedError) instead of aborting the whole session and losing the run.
MAX_BROWSER_RESTARTS = 3

# Role searches tried when the recommendation tabs run dry.
MAX_SEARCHES_PER_CYCLE = 4

# Chromium stability flags: disable GPU raster/GPU process (a common source of
# sudden browser death on Windows) and background networking noise.
_LAUNCH_ARGS = [
    "--disable-gpu",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
]

_diag: Diagnostics | None = None


class BrowserClosedError(RuntimeError):
    """Raised when the Playwright browser/page is gone mid-session."""


def _is_browser_closed(exc: BaseException) -> bool:
    """True when the failure means the browser/page/context vanished."""
    name = type(exc).__name__
    if name in ("TargetClosedError", "BrowserClosedError"):
        return True
    msg = str(exc)
    return (
        "Target page, context or browser has been closed" in msg
        or "browser has been closed" in msg
        or "Target closed" in msg
        or "Connection closed" in msg
        or "TargetClosedError" in msg
    )


def _load_prior_applications() -> tuple[set[str], int, set[str]]:
    """Load previously applied job URLs from reports and the durable log.

    Returns (applied_urls, applied_today_count, failed_today_urls).
    - applied_urls: every job applied on any day (never retry).
    - failed_today_urls: jobs that failed today (skip today, retry tomorrow).
    Counting today's applications makes the daily limit survive bot restarts
    and hard kills (the append-only log is written after every batch).
    """
    applied_urls: set[str] = set()
    todays_urls: set[str] = set()
    failed_today: set[str] = set()
    today = datetime.now().strftime("%Y-%m-%d")

    reports_dir = os.path.join(os.getcwd(), "data", "reports")
    if os.path.isdir(reports_dir):
        for fname in os.listdir(reports_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(reports_dir, fname), "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            for job in data.get("jobs", []):
                url = job.get("url")
                if url:
                    applied_urls.add(url)
                    if str(job.get("applied_at", "")).startswith(today):
                        todays_urls.add(url)
            for job in data.get("failed_jobs", []):
                url = job.get("url")
                if url and str(job.get("attempted_at", "")).startswith(today):
                    failed_today.add(url)

    # Durable append-only log: survives hard kills between report writes.
    for rec in read_applied_log():
        url = (rec.get("url") or "").strip()
        if not url or rec.get("status") == "failed":
            continue
        applied_urls.add(url)
        if str(rec.get("applied_at", "")).startswith(today):
            todays_urls.add(url)

    return applied_urls, len(todays_urls), failed_today


async def run_bot(llm: ChatGroq, resume: str, system_prompt: str, human_prompt: str):
    """Run the bot, relaunching the browser if Chromium dies mid-run.

    A crashed browser used to abort the entire session (0 applications).
    Now we retry with a fresh browser up to MAX_BROWSER_RESTARTS times.
    Daily counts survive because every batch is appended to a durable log and
    re-read on startup.
    """
    global _diag
    log_path, _diag = setup_file_logging(DIAGNOSTICS_DIR)
    print(f"📄 Naukri AutoAI: Run log: {log_path}")

    restarts = 0
    while True:
        try:
            await _run_session(llm, resume, system_prompt, human_prompt)
            break  # session finished on its own (limit reached / no jobs left)
        except Exception as e:
            if _diag is not None:
                _diag.record_error("run_bot", e)
            if _is_browser_closed(e) and restarts < MAX_BROWSER_RESTARTS:
                restarts += 1
                issue_id = log_error("run_bot", e, "")
                print(
                    f"⚠️ Naukri AutoAI: Browser closed unexpectedly [{issue_id}]: {e}\n"
                    f"🔄 Naukri AutoAI: Relaunching browser and resuming "
                    f"(attempt {restarts}/{MAX_BROWSER_RESTARTS})..."
                )
                await human_delay(5, 10)
                continue
            issue_id = log_error("run_bot", e, "")
            print(f"Error [{issue_id}]: {e}")
            await human_delay(20, 40)
            break

    if _diag is not None:
        try:
            _diag.save()
        except Exception:
            pass

    try:
        _, dashboard = refresh_dashboard()
        print(f"📊 Naukri AutoAI: Dashboard updated: {dashboard}")
    except Exception as e:
        print(f"⚠️ Naukri AutoAI: Could not build dashboard: {e}")
    try:
        from app.utils.answer_sheet import refresh_answer_sheet
        sheet = refresh_answer_sheet()
        print(f"📝 Naukri AutoAI: Q&A sheet updated: {sheet}")
    except Exception as e:
        print(f"⚠️ Naukri AutoAI: Could not update Q&A sheet: {e}")
    print("🤖 Naukri AutoAI: Powering down...")


async def _run_session(llm: ChatGroq, resume: str, system_prompt: str, human_prompt: str):
    """One browser session: login, apply until the daily limit or no jobs left.

    Raises if the browser dies so run_bot() can relaunch it.
    """
    global _diag

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO_MS,
            args=_LAUNCH_ARGS,
        )

        storage_state = (
            STORAGE_STATE_PATH
            if STORAGE_STATE_PATH and os.path.exists(STORAGE_STATE_PATH)
            else None
        )
        context = await browser.new_context(
            storage_state=storage_state,
            viewport={'width': VIEWPORT_WIDTH, 'height': VIEWPORT_HEIGHT},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        page = await context.new_page()

        try:
            await handleLogin(page)
            if STORAGE_STATE_PATH:
                try:
                    await context.storage_state(path=STORAGE_STATE_PATH)
                except Exception:
                    pass

            applied_urls, applied_today, failed_today = _load_prior_applications()
            for url in applied_urls | failed_today:
                _seen_job_keys.add(url)
            print(f"📋 Naukri AutoAI: Loaded {len(applied_urls)} applied + {len(failed_today)} failed-today job URLs to skip.")
            print(f"📊 Naukri AutoAI: Already applied to {applied_today}/{DAILY_APPLY_LIMIT} jobs today.")

            if applied_today >= DAILY_APPLY_LIMIT:
                print(
                    f"🤖 Naukri AutoAI: Daily limit of {DAILY_APPLY_LIMIT} already reached "
                    f"({applied_today} applied today). Stopping bot."
                )
                return

            empty_cycles = 0
            while True:
                # Liveness check: a crashed browser would otherwise show up as
                # "no jobs found" and burn the empty-cycle budget silently.
                if page.is_closed() or not browser.is_connected():
                    raise BrowserClosedError("browser or page closed mid-run")

                remaining = DAILY_APPLY_LIMIT - applied_today
                if remaining <= 0:
                    break

                await openJobPage(page)

                tabs_to_check = [
                    '[role="tab"]:has-text("Applies")',
                    '[role="tab"]:has-text("Handpicked")',
                    '[role="tab"]:has-text("Top Candidate")',
                    '[role="tab"]:has-text("Profile")',
                    '[role="tab"]:has-text("Preferences")',
                    '[role="tab"]:has-text("You might like")',
                    'div.tab-list-item:has-text("Applies")',
                    'div.tab-list-item:has-text("Handpicked")',
                    'div.tab-list-item:has-text("Top Candidate")',
                    'div.tab-list-item:has-text("Profile")',
                    'div.tab-list-item:has-text("Preferences")',
                    'div.tab-list-item:has-text("You might like")',
                ]

                selected_this_iteration = False
                seen_tab_labels: set[str] = set()
                batch_size = min(MAX_BATCH_SIZE, remaining)

                for tab_locator in tabs_to_check:
                    # Extract the tab label to avoid clicking the same tab twice
                    # (role=tab and div.tab-list-item variants can point at the same tab).
                    label_match = None
                    m = re.search(r'has-text\("([^"]+)"\)', tab_locator)
                    if m:
                        label_match = m.group(1).lower()
                    if label_match and label_match in seen_tab_labels:
                        continue

                    print(f"🔍 Naukri AutoAI: Checking tab {tab_locator}...")
                    try:
                        tab = page.locator(tab_locator)
                        if await tab.is_visible():
                            await tab.click()
                            if label_match:
                                seen_tab_labels.add(label_match)
                            await human_delay(2, 4)
                        else:
                            print("🔍 Naukri AutoAI: tab not visible, skipping.")
                            continue
                    except Exception as e:
                        if _is_browser_closed(e):
                            raise  # browser died -> let run_bot() relaunch
                        print(f"🔍 Naukri AutoAI: Could not click tab: {e}")
                        continue

                    # SELECT UP TO batch_size JOBS VIA CHECKBOXES
                    selected_jobs = await selectJobInBulk(page, applied_urls, max_jobs=batch_size)
                    if not selected_jobs:
                        print("🔍 Naukri AutoAI: No unapplied jobs found on this tab. Checking another tab...")
                        await human_delay(1, 2)
                        continue

                    # BULK APPLY
                    applied_count = await applyInBulk(
                        page, llm, resume, system_prompt, human_prompt, selected_jobs
                    )
                    if applied_count:
                        applied_today = _record_batch(
                            selected_jobs, applied_count, applied_today, applied_urls
                        )
                        print(f"📈 Naukri AutoAI: Total applied today: {applied_today}/{DAILY_APPLY_LIMIT}")

                    selected_this_iteration = True
                    break

                if applied_today >= DAILY_APPLY_LIMIT:
                    print(
                        f"🤖 Naukri AutoAI: Applied to {applied_today} jobs today. "
                        f"Daily limit of {DAILY_APPLY_LIMIT} reached. Stopping bot."
                    )
                    break

                if not selected_this_iteration:
                    # Recommendation tabs are dry: fall back to role searches.
                    found, applied_today = await _search_and_apply(
                        page, llm, resume, system_prompt, human_prompt,
                        applied_urls, batch_size, applied_today,
                    )
                    if found:
                        selected_this_iteration = True

                if not selected_this_iteration:
                    empty_cycles += 1
                    print(
                        f"🔍 Naukri AutoAI: No jobs selected on any tab this cycle "
                        f"({empty_cycles}/{MAX_EMPTY_CYCLES})."
                    )
                    if empty_cycles >= MAX_EMPTY_CYCLES:
                        print(
                            "🤖 Naukri AutoAI: No new applicable jobs left. "
                            "Stopping bot instead of looping forever."
                        )
                        break
                    await human_delay(3, 5)
                else:
                    empty_cycles = 0

        except Exception as e:
            if _diag is not None:
                shot = None
                try:
                    if SCREENSHOT_ON_ERROR and not page.is_closed():
                        shot = await _diag.take_screenshot(page, "error")
                except Exception:
                    pass
                url = ""
                try:
                    if not page.is_closed():
                        url = page.url
                except Exception:
                    pass
                _diag.record_error("session", e, url, shot)
            raise
        finally:
            # Save the report every session so applications made before a crash
            # still count toward today's limit after the relaunch.
            save_and_print_report()
            try:
                await browser.close()
            except Exception:
                pass


def _record_batch(selected_jobs: list[dict], applied_count: int,
                  applied_today: int, applied_urls: set[str]) -> int:
    """Persist a finished batch to the durable log and update counters."""
    status = next((j.get("status") for j in selected_jobs if j.get("status")), "attempted")
    applied_today += applied_count
    append_applied(selected_jobs, status=status)
    for job in selected_jobs:
        if job.get("url"):
            applied_urls.add(job["url"])
    return applied_today


async def _search_and_apply(page, llm, resume, system_prompt, human_prompt,
                           applied_urls: set[str], batch_size: int,
                           applied_today: int) -> tuple[bool, int]:
    """Try role searches when the recommendation tabs have no selectable jobs.

    Returns (applied_any, updated_applied_today).
    """
    roles = [r for r in PREFERRED_ROLES if r][:MAX_SEARCHES_PER_CYCLE]
    if not roles:
        return False, applied_today

    location = PREFERRED_LOCATIONS[0] if PREFERRED_LOCATIONS else None

    # Never select more than the daily limit allows.
    batch_size = max(1, min(batch_size, DAILY_APPLY_LIMIT - applied_today))
    if batch_size <= 0:
        return False, applied_today

    for role in roles:
        try:
            found = await searchJobs(page, role, location)
        except Exception as e:
            if _is_browser_closed(e):
                raise
            print(f"⚠️ Naukri AutoAI: Search failed: {e}")
            continue
        if not found:
            continue

        selected_jobs = await selectJobInBulk(page, applied_urls, max_jobs=batch_size)
        if not selected_jobs:
            print("🔎 Naukri AutoAI: Search results had no selectable jobs.")
            continue

        applied_count = await applyInBulk(
            page, llm, resume, system_prompt, human_prompt, selected_jobs
        )
        if applied_count:
            applied_today = _record_batch(
                selected_jobs, applied_count, applied_today, applied_urls
            )
            print(f"📈 Naukri AutoAI: Total applied today: {applied_today}/{DAILY_APPLY_LIMIT}")
            return True, applied_today

    return False, applied_today
