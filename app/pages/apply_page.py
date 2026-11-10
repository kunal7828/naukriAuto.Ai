from playwright.async_api import Page
import re
from langchain_groq import ChatGroq
from app.pages.questionnaire_page import handle_questionnaire
from app.utils.human import human_delay
from app.utils.report import record_applied_jobs, record_failed_jobs

ERROR_TOAST_PATTERN = re.compile(r"error processing your request", re.IGNORECASE)

# Text that indicates Naukri accepted the application.
_SUCCESS_PATTERNS = (
    "successfully applied",
    "application was successful",
    "applied successfully",
    "application has been submitted",
    "application submitted",
    "successfully submitted",
    "your application was successful",
    "application sent",
)

# Whole-button labels that indicate an external company-site apply.
EXTERNAL_APPLY_PATTERN = re.compile(r"company site|external|career", re.IGNORECASE)


async def _close_extra_tabs(context, keep: Page):
    for pg in context.pages:
        if pg is keep:
            continue
        if pg.is_closed():
            continue
        try:
            await pg.close()
        except Exception:
            pass


_BULK_LABEL_PATTERN = re.compile(
    r"^\s*Apply(\s+\d+)?(\s+Jobs?(?:\(s\))?)?\s*$", re.IGNORECASE
)


async def _find_bulk_apply_button(page: Page):
    """Find the page-level (multi-)Apply button used for checkbox bulk apply.

    The same "Apply" label also exists on individual job cards, so we only
    accept buttons that are *not* inside a job card article.
    """
    # Known Naukri class for the checkbox multi-apply button.
    try:
        loc = page.locator('.multi-apply-button')
        for i in range(await loc.count()):
            el = loc.nth(i)
            if await el.is_visible():
                return el
    except Exception:
        pass

    # Fallback: scan buttons and keep only page-level Apply controls.
    try:
        buttons = page.locator('button, [role="button"]')
        for i in range(await buttons.count()):
            el = buttons.nth(i)
            try:
                if not await el.is_visible():
                    continue
                label = (await el.inner_text()).strip()
                if not _BULK_LABEL_PATTERN.match(label):
                    continue
                inside_card = await el.evaluate("el => !!el.closest('article')")
                if not inside_card:
                    return el
            except Exception:
                continue
    except Exception:
        pass

    return None


async def _detect_apply_outcome(page: Page) -> str:
    """Classify what happened after the Apply click: success/error/unknown.

    Returns "success" when a success message is visible, "error" when Naukri
    shows its error toast, otherwise "unknown".
    """
    try:
        text = (await page.inner_text("body")).lower()
    except Exception:
        return "unknown"
    if ERROR_TOAST_PATTERN.search(text):
        return "error"
    for pattern in _SUCCESS_PATTERNS:
        if pattern in text:
            return "success"
    return "unknown"


async def applyInBulk(page: Page, llm: ChatGroq, resume: str, system_prompt: str, human_prompt: str, selected_jobs: list[dict] | None = None) -> int:
    """Click the bulk Apply button for the ticked jobs, answer any questionnaire,
    verify the outcome, and return the number of jobs counted as applied.

    Jobs are only counted when the application was actually submitted (or the
    outcome could not be determined, which is treated conservatively so the
    daily limit is never overshot).
    """
    if not selected_jobs:
        return 0

    context = page.context
    print(f"🤖 Naukri AutoAI: Applying to {len(selected_jobs)} selected job(s) in bulk...")

    apply_btn = await _find_bulk_apply_button(page)
    if apply_btn is None:
        print("⚠️ Naukri AutoAI: Bulk Apply button not found.")
        record_failed_jobs(selected_jobs, "Bulk Apply button not found")
        return 0

    # The button is disabled until at least one checkbox is ticked; wait for it.
    try:
        await apply_btn.wait_for(state="enabled", timeout=15000)
    except Exception:
        if await apply_btn.is_disabled():
            print("⚠️ Naukri AutoAI: Bulk Apply button is still disabled (no jobs selected?).")
            record_failed_jobs(selected_jobs, "Bulk Apply button disabled")
            return 0

    # Capture any new tabs (external company sites) opened by bulk apply.
    opened_tabs = []
    def _on_new_page(new_page):
        opened_tabs.append(new_page)
    context.on("page", _on_new_page)

    await apply_btn.click()
    await human_delay(2, 4)

    context.remove_listener("page", _on_new_page)

    # Close any external tabs straight away.
    for tab in opened_tabs:
        try:
            if not tab.is_closed():
                await tab.close()
        except Exception:
            pass
    if opened_tabs:
        print(f"🔗 Naukri AutoAI: {len(opened_tabs)} external tab(s) opened and closed.")

    # Also close any other stray tabs (e.g. opened by questionnaire links).
    await _close_extra_tabs(context, page)

    # Check for an error toast on the main page.
    error_toast = page.get_by_text(ERROR_TOAST_PATTERN)
    has_error_toast = await error_toast.count() > 0
    if has_error_toast:
        reason = "Naukri error processing the apply request"
        print(f"⚠️ Naukri AutoAI: {reason}.")
        record_failed_jobs(selected_jobs, reason)
        return 0

    # Answer any recruiter questionnaire that appears.
    await handle_questionnaire(page, llm, resume, system_prompt, human_prompt)

    # Verify the application actually went through.
    outcome = await _detect_apply_outcome(page)
    if outcome == "error":
        reason = "Naukri error processing the apply request"
        print(f"⚠️ Naukri AutoAI: {reason} (detected after questionnaire).")
        record_failed_jobs(selected_jobs, reason)
        return 0

    if outcome == "success":
        status = "confirmed"
        print(f"🎉 Naukri AutoAI: Application confirmed for {len(selected_jobs)} job(s).")
    else:
        # No explicit success/error marker: count conservatively so the daily
        # limit is never overshot, but flag the uncertainty in the report.
        status = "attempted"
        print(f"⚠️ Naukri AutoAI: Could not confirm the outcome; counting as attempted.")

    for job in selected_jobs:
        job["status"] = status
    record_applied_jobs(selected_jobs)
    await human_delay(1, 3)
    return len(selected_jobs)


# Kept for potential single-job use.
async def apply_to_job(page: Page, llm: ChatGroq, resume: str, system_prompt: str, human_prompt: str, job_info: dict | None = None) -> bool:
    return bool(await applyInBulk(page, llm, resume, system_prompt, human_prompt, [job_info] if job_info else []))
