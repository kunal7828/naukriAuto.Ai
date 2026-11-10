from playwright.async_api import Page
import random
import re
from app.utils.human import human_delay
from app.config.config import MAX_EXPERIENCE_YEARS, PREFERRED_ROLES

_REVIEW_COUNT_PATTERN = re.compile(r"^[\d,]+\s*Reviews?$", re.IGNORECASE)
_EXP_RANGE_PATTERN = re.compile(r"(\d+)\s*-\s*(\d+)\s*Yrs?", re.IGNORECASE)
_EXP_SINGLE_PATTERN = re.compile(r"\b(\d+)\s*Yrs?\b", re.IGNORECASE)
_FRESHER_PATTERN = re.compile(r"\bfresher\b", re.IGNORECASE)

# URLs/keys attempted this run (skip duplicates across cycles).
_seen_job_keys: set[str] = set()

_CARD_HTML_DUMPED = False

# Checkbox candidates inside a job card.
_CHECKBOX_SELECTORS = [
    '.tuple-check-box',
    'input[type="checkbox"]',
    '[role="checkbox"]',
    'label[class*="check" i]',
    '[class*="tuple-check" i]',
    '[class*="checkbox" i]',
    'span[class*="check" i]',
]

# Elements indicating a card is already selected.
_SELECTED_SELECTORS = [
    'input[type="checkbox"]:checked',
    '.naukicon-ot-Checked',
    '[class*="Checked"]',
    '[class*="checked"]',
    '[class*="selected" i]',
]


def _job_key(job_info: dict) -> str:
    if job_info.get("url"):
        return job_info["url"]
    return f"{job_info.get('title', '')}|{job_info.get('company', '')}"


def _role_priority(title: str) -> int:
    """Rank a job title against PREFERRED_ROLES (0 = best match).

    Lower is better. Unmatched roles sort last but are still selectable, so
    preferred roles are always ticked before anything else on the page.
    """
    if not PREFERRED_ROLES:
        return len(PREFERRED_ROLES)
    normalized = " ".join((title or "").lower().split())
    if not normalized:
        return len(PREFERRED_ROLES)
    for idx, role in enumerate(PREFERRED_ROLES):
        if role in normalized:
            return idx
    return len(PREFERRED_ROLES)



def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://www.naukri.com" + url
    return url


async def _get_min_experience_required(article) -> int | None:
    try:
        text = await article.inner_text()
    except Exception:
        return None

    if _FRESHER_PATTERN.search(text):
        return 0

    range_match = _EXP_RANGE_PATTERN.search(text)
    if range_match:
        return int(range_match.group(1))

    single_match = _EXP_SINGLE_PATTERN.search(text)
    if single_match:
        return int(single_match.group(1))

    return None


async def _extract_job_info(article) -> dict:
    async def safe_text(selectors: list[str], reject: re.Pattern | None = None) -> str:
        for selector in selectors:
            try:
                locator = article.locator(selector)
                count = await locator.count()
                for idx in range(count):
                    raw = (await locator.nth(idx).inner_text()).strip()
                    if not raw:
                        continue
                    candidate = raw.splitlines()[0].strip() or raw
                    if candidate and not (reject and reject.match(candidate)):
                        return candidate
            except Exception:
                continue
        return "Unknown"

    async def safe_href(selectors: list[str]) -> str:
        for selector in selectors:
            try:
                locator = article.locator(selector)
                count = await locator.count()
                for idx in range(count):
                    href = await locator.nth(idx).get_attribute("href")
                    if href and "ambitionbox.com" not in href:
                        return href
            except Exception:
                continue
        return ""

    title_selectors = [
        'a.title', '.title a', '.title', '[data-testid="jobTupleHeader"] a',
        'h2 a', 'h3 a', 'a[href*="/job-listings/"]', 'a[href*="/job-detail/"]',
        '.job-title a', '.jobTitle a', 'a.jobTitle'
    ]
    company_selectors = [
        'a.comp-name', '.comp-name', '.companyInfo a', '.companyInfo', '.subTitle',
        '.company-name a', '.companyName'
    ]

    url = await safe_href(title_selectors + ['a[href*="job-listings"]', 'a[href*="job-detail"]', 'a'])
    return {
        "title": await safe_text(title_selectors),
        "company": await safe_text(company_selectors, reject=_REVIEW_COUNT_PATTERN),
        "url": _normalize_url(url),
    }


async def _is_walkin(article) -> bool:
    try:
        return await article.get_by_text("Walk-in", exact=False).count() > 0
    except Exception:
        return False


async def _find_job_cards(page: Page):
    """Try multiple selectors to find job card elements on the current Naukri DOM."""
    selectors = [
        'article.jobTuple',
        'article',
        '.jobTuple',
        '[class*="jobTuple"]',
        '[class*="jobCard"]',
        '[class*="job-card"]',
        '.srp-jobtuple',
        '.job-card',
    ]
    for sel in selectors:
        try:
            locator = page.locator(sel)
            count = await locator.count()
            if count > 0:
                sample = locator.nth(0)
                txt = await sample.inner_text()
                if txt and len(txt.strip()) > 20:
                    print(f"✅ Naukri AutoAI: Found {count} job cards using selector: {sel}")
                    return locator
        except Exception:
            continue
    return None


async def _get_checkbox(card):
    """Return (element, is_native_input) for the card checkbox, or (None, False)."""
    # Prefer the known Naukri custom checkbox class first.
    for sel in _CHECKBOX_SELECTORS:
        try:
            loc = card.locator(sel)
            count = await loc.count()
            for i in range(count):
                el = loc.nth(i)
                try:
                    visible = await el.is_visible()
                except Exception:
                    visible = False
                if sel == 'input[type="checkbox"]':
                    # Native checkbox may be visually hidden but still clickable via check().
                    if visible or count > 0:
                        return el, True
                elif visible:
                    return el, False
        except Exception:
            continue
    return None, False


async def _is_selected(card) -> bool:
    for sel in _SELECTED_SELECTORS:
        try:
            if await card.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


async def _count_selected_on_page(articles) -> int:
    total = await articles.count()
    selected = 0
    for i in range(total):
        try:
            if await _is_selected(articles.nth(i)):
                selected += 1
        except Exception:
            continue
    return selected


async def selectJobInBulk(page: Page, applied_urls: set[str] | None = None, max_jobs: int = 5) -> list[dict]:
    """Tick the card checkboxes for up to `max_jobs` eligible jobs on the current listings page.

    Returns the job infos that were selected. Does NOT click the page-level Apply button.
    """
    if applied_urls is None:
        applied_urls = set()

    articles = await _find_job_cards(page)
    if articles is None:
        print("⚠️ Naukri AutoAI: No job cards found on this page.")
        return []

    total = await articles.count()

    already_selected = await _count_selected_on_page(articles)
    if already_selected:
        print(f"ℹ️ Naukri AutoAI: {already_selected} job(s) already selected on this page.")

    selected_jobs: list[dict] = []
    remaining_slots = max(0, max_jobs - already_selected)
    if remaining_slots == 0:
        return selected_jobs

    # Pass 1: gather every eligible card on the page with its role priority.
    # Filtering first lets us tick the best-matching roles no matter where
    # they sit in the list, instead of just taking the first five in order.
    candidates: list[tuple[int, int, object, dict]] = []

    for i in range(total):
        card = articles.nth(i)

        # Random scroll simulation
        if random.random() > 0.6:
            await page.mouse.wheel(0, random.randint(200, 400))

        if await _is_walkin(card):
            print("⏭️ Naukri AutoAI: Skipping Walk-in listing (not supported by quick apply).")
            continue

        min_experience = await _get_min_experience_required(card)
        if min_experience is not None and min_experience > MAX_EXPERIENCE_YEARS:
            print(f"⏭️ Naukri AutoAI: Skipping job requiring {min_experience}+ yrs experience (limit is {MAX_EXPERIENCE_YEARS} yrs).")
            continue

        job_info = await _extract_job_info(card)
        key = _job_key(job_info)

        if key in _seen_job_keys:
            print(f"⏭️ Naukri AutoAI: Already attempted this run, skipping: {job_info['title']} @ {job_info['company']}")
            continue

        job_url = job_info.get("url", "")
        if job_url and job_url in applied_urls:
            print(f"⏭️ Naukri AutoAI: Skipping already applied job: {job_info['title']} @ {job_info['company']}")
            continue

        candidates.append((_role_priority(job_info["title"]), i, card, job_info))

    # Pass 2: tick preferred roles first, falling back to page order for the rest.
    candidates.sort(key=lambda item: (item[0], item[1]))
    matched = sum(1 for rank, *_ in candidates if rank < len(PREFERRED_ROLES))
    if matched:
        print(f"🎯 Naukri AutoAI: {matched} eligible job(s) match a preferred role.")

    for rank, _, card, job_info in candidates:
        if len(selected_jobs) >= remaining_slots:
            break

        if await _is_selected(card):
            # Already ticked (shouldn't normally happen since we counted), keep it.
            selected_jobs.append(job_info)
            continue

        cb, is_native = await _get_checkbox(card)
        if cb is None:
            print(f"⚠️ Naukri AutoAI: No checkbox found on card: {job_info['title']}")
            # Dump the first card's HTML once to help debug selector issues.
            global _CARD_HTML_DUMPED
            if not _CARD_HTML_DUMPED:
                try:
                    import os
                    os.makedirs("data/diagnostics", exist_ok=True)
                    html = await card.evaluate("el => el.outerHTML")
                    with open("data/diagnostics/job_card.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    _CARD_HTML_DUMPED = True
                    print("🗂️ Naukri AutoAI: Saved card HTML to data/diagnostics/job_card.html")
                except Exception:
                    pass
            continue

        try:
            if is_native:
                await cb.check(force=True)
            else:
                await cb.click()
            await human_delay(0.4, 1.0)
        except Exception as e:
            print(f"⚠️ Naukri AutoAI: Could not tick checkbox: {e}")
            continue

        _seen_job_keys.add(_job_key(job_info))
        selected_jobs.append(job_info)
        star = "⭐" if rank < len(PREFERRED_ROLES) else "▫️"
        print(f"{star} Selected job {len(selected_jobs) + already_selected}/{max_jobs}: {job_info['title']} @ {job_info['company']}")

    return selected_jobs


# Backwards-compatible alias
async def collect_jobs(page: Page, applied_urls: set[str] | None = None, max_jobs: int = 5):
    return await selectJobInBulk(page, applied_urls, max_jobs)
