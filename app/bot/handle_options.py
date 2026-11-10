import re
from playwright.async_api import Locator, Page

from app.utils.human import human_mouse_move


async def getAvailableOptions(chat_container: Locator):
    """Collect the visible answer options (labels/buttons/chips) from the panel."""
    available_options: list[str] = []

    # Targeted search inside the chat container for option labels and buttons
    # We exclude '.ssrc__radio' to avoid capturing hidden input values directly, preferring visible labels.
    options_locator = chat_container.locator('.ssrc__label, label, button, .chip, [role="button"]')
    for i in range(await options_locator.count()):
        try:
            el = options_locator.nth(i)
            txt = await el.inner_text()
            if not txt:
                txt = await el.get_attribute("value")
            if txt and 0 < len(txt.strip()) < 50:
                available_options.append(txt.strip())
        except Exception:
            continue

    available_options = list(dict.fromkeys(available_options))[-10:]  # Deduplicate and keep most recent
    if available_options:
        print(f"🔘 Options detected: {available_options}")

    return available_options


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


async def _click_option(chat_container: Locator, option: str, page: Page) -> None:
    """Click an option label and force-check its radio button if present."""
    target = chat_container.get_by_text(option, exact=True).last
    try:
        if await target.count() == 0:
            target = chat_container.get_by_text(option, exact=False).last
        await human_mouse_move(page)
        await target.click(force=True)
    except Exception:
        try:
            await chat_container.get_by_text(option, exact=False).last.click(force=True)
        except Exception:
            pass
    # Force check hidden radio button to enable 'Save'
    try:
        radio_id = await target.get_attribute("for")
        if radio_id:
            await page.locator(f"#{radio_id}").check(force=True)
    except Exception:
        pass


async def handleOptionResponse(available_options: list[str], answer: str | object,
                               chat_container: Locator, page: Page):
    """Select the option that best matches the generated answer.

    Matching order: exact -> substring (either direction) -> word overlap.
    If nothing matches reasonably, prefer a "Skip this question" option.
    """
    ans = str(answer or "").strip()

    matched = next(
        (o for o in available_options if o.strip().lower() == ans.lower()), None
    )
    if not matched:
        lowered = ans.lower()
        matched = next(
            (o for o in available_options
             if o.strip().lower() in lowered or lowered in o.strip().lower()),
            None,
        )
    if not matched:
        ans_tokens = _tokens(ans)
        best, best_score = None, 0
        for option in available_options:
            score = len(ans_tokens & _tokens(option))
            if score > best_score:
                best, best_score = option, score
        if best is not None and best_score > 0:
            matched = best

    if matched:
        print(f"🔘 Naukri AutoAI: Selecting option '{matched}' for answer '{ans}'.")
        await _click_option(chat_container, matched, page)
        return

    skip = next(
        (o for o in available_options if "skip" in o.lower()), None
    )
    if skip:
        print(f"🔘 Naukri AutoAI: No matching option; selecting '{skip}'.")
        await _click_option(chat_container, skip, page)
        return

    print(f"⚠️ Naukri AutoAI: No matching option for answer '{ans}'; leaving unanswered.")
