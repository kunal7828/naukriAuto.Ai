from playwright.async_api import Page


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
