from playwright.async_api import Page
from app.utils.human import human_delay, human_typing

_SEARCH_INPUT_SELECTORS = [
    'input[placeholder*="skills / designations / companies" i]',
    'input[placeholder*="keyword / designation / companies" i]',
    'input[placeholder*="skills" i]',
    'input[placeholder*="designation" i]',
    '#keyword-search',
    'input[name="keyword"]',
]

_LOCATION_INPUT_SELECTORS = [
    'input[placeholder*="enter location" i]',
    '#location-search',
    'input[name="location"]',
]


async def openJobPage(page: Page):
    print("🤖 Naukri AutoAI: Navigating to Jobs...")
    await page.goto("https://www.naukri.com/mnjuser/recommendedjobs", wait_until="load")
    try:
        await page.wait_for_selector('article.jobTuple', timeout=15000)
    except Exception as e:
        print(f"🤖 Naukri AutoAI: Could not find job listings, continuing anyway... {e}")
    await human_delay(4, 7)


async def _find_search_input(page: Page):
    """Return a visible search input, opening the search overlay if needed."""
    for sel in _SEARCH_INPUT_SELECTORS:
        try:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                return loc.first
        except Exception:
            continue

    # The search bar may be hidden behind the "Search jobs here" button.
    try:
        btn = page.get_by_role("button", name="Search jobs here")
        if await btn.count() > 0 and await btn.first.is_visible():
            await btn.first.click()
            await human_delay(1, 2)
    except Exception:
        pass

    for sel in _SEARCH_INPUT_SELECTORS:
        try:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    return None


async def searchJobs(page: Page, query: str, location: str | None = None) -> bool:
    """Search Naukri by role keyword (and optional location).

    Returns True when job cards are present after the search.
    """
    print(f"🔎 Naukri AutoAI: Searching for '{query}'"
          + (f" in '{location}'" if location else "") + "...")
    await page.goto("https://www.naukri.com/mnjuser/recommendedjobs",
                    wait_until="domcontentloaded")
    await human_delay(2, 3)

    search_input = await _find_search_input(page)
    if search_input is None:
        print("⚠️ Naukri AutoAI: Could not find the search box.")
        return False

    try:
        await search_input.click()
        await search_input.fill("")
        await human_typing(search_input, query)
        await human_delay(0.5, 1.5)

        if location:
            for sel in _LOCATION_INPUT_SELECTORS:
                try:
                    loc = page.locator(sel)
                    if await loc.count() > 0 and await loc.first.is_visible():
                        await loc.first.click()
                        await loc.first.fill("")
                        await human_typing(loc.first, location)
                        break
                except Exception:
                    continue

        await search_input.press("Enter")
    except Exception as e:
        print(f"⚠️ Naukri AutoAI: Search failed: {e}")
        return False

    try:
        await page.wait_for_selector('article.jobTuple', timeout=20000)
    except Exception:
        print("⚠️ Naukri AutoAI: Search returned no job cards.")
        return False

    # Scroll to trigger lazy-loaded results before selecting.
    for _ in range(3):
        await page.mouse.wheel(0, 800)
        await human_delay(1, 2)

    count = await page.locator('article.jobTuple').count()
    print(f"🔎 Naukri AutoAI: Search '{query}' returned {count} job card(s).")
    return count > 0
