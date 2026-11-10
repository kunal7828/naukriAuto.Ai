"""Recruiter questionnaire panel: detect questions, get options, answer (Page Object)."""
import asyncio
import random
import re
from typing import Any
from playwright.async_api import Page, Locator
from langchain_groq import ChatGroq
from app.utils.human import human_delay, human_typing, human_mouse_move
from app.ai.ai_answer import getAiAnswer
from app.repository.repo import findAnswerFromPreviousResponse, saveResponseToDB
from app.utils.answer_sheet import find_curated_answer
from app.utils.report import record_qa

# Candidate selectors for the Naukri chat/questionnaire panel container.
_PANEL_SELECTORS = [
    '.chatbot_MessageContainer',
    '[class*="chatbotContainer"]',
    '[class*="chatbot"]',
    '[class*="chatBot"]',
    '[class*="ChatBot"]',
    '[class*="chat"]',
]

# Candidate selectors for the free-text input box.
_INPUT_SELECTORS = [
    '.textArea[contenteditable="true"]',
    '.textArea',
    '[contenteditable="true"]',
    'textarea',
    'input[type="text"]',
]

# Candidate selectors for the Save/Submit button.
_SAVE_SELECTORS = [
    '.send:not(.disabled) .sendMsg',
    '.sendMsg',
    'button:has-text("Save")',
    'button:has-text("Submit")',
    '[class*="send"]',
]

# Answers that carry no information; re-ask the AI instead of reusing them.
_NON_ANSWERS = {"", "not specified", "n/a", "na", "none", "unknown", "-", "not sure"}


def _is_non_answer(answer: Any) -> bool:
    return answer is None or str(answer).strip().lower() in _NON_ANSWERS


async def _panel_has_input_text(panel: Locator) -> bool:
    """Heuristic: the real chat panel contains a chat input or the placeholder text."""
    try:
        if await panel.locator('[contenteditable="true"], textarea').count() > 0:
            return True
    except Exception:
        pass
    try:
        if await panel.get_by_text("Type message here", exact=False).count() > 0:
            return True
    except Exception:
        pass
    return False


async def _find_panel(page: Page) -> Locator | None:
    for idx, sel in enumerate(_PANEL_SELECTORS):
        try:
            loc = page.locator(sel)
            count = await loc.count()
            if count == 0:
                continue
            first = loc.first
            if not await first.is_visible():
                continue
            # For narrow/known selectors accept directly; for broad fallbacks
            # verify the panel actually looks like the chat panel.
            if idx <= 3 or await _panel_has_input_text(first):
                return first
        except Exception:
            continue
    # Final fallback: locate the element wrapping the chat input / placeholder.
    try:
        placeholder = page.get_by_text("Type message here", exact=False)
        if await placeholder.count() > 0:
            # Walk up to a reasonably sized ancestor container.
            ancestor = placeholder.first.locator(
                'xpath=ancestor::*[contains(@class,"chat") or contains(@class,"Chat")][1]'
            )
            if await ancestor.count() > 0 and await ancestor.first.is_visible():
                return ancestor.first
    except Exception:
        pass
    return None


async def _find_input(page: Page, panel: Locator) -> tuple[Locator | None, bool]:
    """Return (input_locator, is_contenteditable)."""
    for sel in _INPUT_SELECTORS:
        for scope in (panel, page):
            try:
                loc = scope.locator(sel)
                count = await loc.count()
                for i in range(count):
                    el = loc.nth(i)
                    if await el.is_visible():
                        is_ce = (await el.get_attribute("contenteditable")) == "true"
                        return el, is_ce
            except Exception:
                continue
    return None, False


async def _find_save(page: Page, panel: Locator) -> Locator | None:
    for sel in _SAVE_SELECTORS:
        for scope in (panel, page):
            try:
                loc = scope.locator(sel)
                count = await loc.count()
                for i in range(count):
                    el = loc.nth(i)
                    if await el.is_visible():
                        return el
            except Exception:
                continue
    return None


async def handle_questionnaire(page: Page, llm: ChatGroq, resume: str, system_prompt: str, human_prompt: str):
    if not llm:
        return

    # Wait for the chat/questionnaire panel to appear
    panel = None
    for _ in range(12):  # ~12s
        panel = await _find_panel(page)
        if panel is not None:
            break
        await asyncio.sleep(1)

    if panel is None:
        print("ℹ️ Naukri AutoAI: No questionnaire detected.")
        return

    print("🚨 Naukri AutoAI: Questionnaire detected! Analyzing...")

    # Save the panel HTML once to help debug selector issues.
    try:
        import os
        os.makedirs("data/diagnostics", exist_ok=True)
        html = await panel.evaluate("el => el.outerHTML")
        with open("data/diagnostics/questionnaire_panel.html", "w", encoding="utf-8") as f:
            f.write(html)
    except Exception:
        pass

    last_question: str | None = None
    last_answer: str | None = None
    stale_rounds = 0
    max_rounds = 25

    for _ in range(max_rounds):
        panel = await _find_panel(page)
        if panel is None or not await panel.is_visible():
            print("✅ Naukri AutoAI: Questionnaire Closed.")
            break

        await asyncio.sleep(random.uniform(2.0, 3.5))

        question: str | None = await getNaukriBotQuestion(page)
        if question is None:
            stale_rounds += 1
            if stale_rounds >= 3:
                break
            continue

        # If the extracted "question" is actually our own sent answer, skip it.
        if last_answer and question.strip() == last_answer.strip():
            stale_rounds += 1
            if stale_rounds >= 3:
                print("✅ Naukri AutoAI: No new question detected; finishing questionnaire.")
                break
            continue

        # If the question hasn't changed, the panel is likely waiting on us
        # (or we already answered). Avoid re-answering the same one endlessly.
        if question.strip() == (last_question or "").strip():
            stale_rounds += 1
            if stale_rounds >= 3:
                print("✅ Naukri AutoAI: No new question detected; finishing questionnaire.")
                break
            continue
        stale_rounds = 0
        last_question = question

        input_box, is_ce = await _find_input(page, panel)
        is_text = input_box is not None
        available_options: list[str] = []

        if not is_text:
            available_options = await getAvailableOptions(panel)
            if available_options:
                print(f"🔘 Options detected: {available_options}")

        print("🧠 Naukri AutoAI: Thinking...")
        # Priority: your curated answer (Question_Answers.xlsx) -> cached DB -> AI.
        answer = find_curated_answer(question)
        if answer is not None:
            print("📋 Naukri AutoAI: Using your curated answer from Question_Answers.xlsx")
        if answer is None:
            answer = findAnswerFromPreviousResponse(question, available_options)
            if _is_non_answer(answer):
                # A cached "Not specified" is worse than a fresh AI answer.
                print("🧠 Naukri AutoAI: Cached answer was non-committal; asking the AI again.")
                answer = None
        if answer is None:
            answer = await getAiAnswer(system_prompt, human_prompt, resume, available_options, question, llm)
            saveResponseToDB(question, available_options, answer)
        print(f"✅ Naukri AutoAI Answer: {answer}")
        record_qa(question, available_options, answer)
        last_answer = str(answer)

        if is_text:
            await handleTextResponse(input_box, answer, page)
        elif available_options:
            await handleOptionResponse(available_options, answer, panel, page)

        # SUBMIT
        await clickSaveButton(page, panel)


async def handleTextResponse(input_box: Locator, answer: str, page: Page):
    try:
        await input_box.click()
    except Exception:
        pass
    try:
        await page.keyboard.press('Control+A')
        await page.keyboard.press('Backspace')
    except Exception:
        pass
    await human_typing(page.keyboard, answer)
    await human_delay(1, 2)


async def clickSaveButton(page: Page, panel: Locator | None = None):
    save_btn = await _find_save(page, panel) if panel is not None else None
    if save_btn is not None:
        try:
            # Wait briefly for the button to become enabled, then click.
            try:
                await save_btn.wait_for(state="enabled", timeout=5000)
            except Exception:
                pass
            await save_btn.click(force=True)
            print("👆 Naukri AutoAI: Clicked Save.")
            await human_delay(1, 2)
            return
        except Exception:
            pass
    try:
        await page.keyboard.press('Enter')
        print("👆 Naukri AutoAI: Pressed Enter to submit.")
        await human_delay(1, 2)
    except Exception:
        pass


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


# Candidate selectors for Naukri chatbot message bubbles (question text).
# The Naukri apply/chat UI has changed over time, so try several.
_QUESTION_SELECTORS = [
    '.botItem .botMsg span',
    '.botItem .botMsg',
    '[class*="botMsg"]',
    '[class*="botMessage"]',
    '[class*="chat"] [class*="msg"]',
    '[class*="chat"] [class*="Message"]',
    '[class*="message"]',
    '[class*="Message"]',
]

# Text that is clearly not a real question (greeting / instructions / confirmations).
_NON_QUESTION_HINTS = (
    "thank you for showing interest",
    "kindly answer all the recruiter",
    "successfully apply for the job",
    "your application was successful",
    "application was successful",
    "successfully applied",
    "thank you for applying",
    "your application has been submitted",
    "application has been submitted",
)


async def getNaukriBotQuestion(page: Page) -> str | None:
    """Return the latest recruiter/bot question text from the Naukri chat panel."""
    for selector in _QUESTION_SELECTORS:
        try:
            loc = page.locator(selector)
            count = await loc.count()
            if count == 0:
                continue
            # Walk backwards from the most recent bubble and return the first
            # meaningful question (skip greetings / instructions).
            for i in range(count - 1, -1, -1):
                try:
                    raw = (await loc.nth(i).inner_text()).strip()
                except Exception:
                    continue
                if not raw:
                    continue
                lowered = raw.lower()
                if any(hint in lowered for hint in _NON_QUESTION_HINTS):
                    continue
                return raw
        except Exception:
            continue
    return None
