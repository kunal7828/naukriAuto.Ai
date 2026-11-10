from app.utils.human import human_delay, human_typing, human_mouse_move
from playwright.async_api import Page
from app.config.config import EMAIL, PASSWORD


async def handleLogin(page: Page):
    print("🤖 Naukri AutoAI: Initiating Human Sequence...")
    await page.goto("https://www.naukri.com", wait_until="domcontentloaded")
    await human_delay(2, 4)

    # Already signed in (saved browser session)?
    try:
        login_link = page.get_by_role("link", name="Login", exact=True)
        if await login_link.count() == 0:
            print("✅ Naukri AutoAI: Already logged in (saved session). Cooling down...")
            await human_mouse_move(page)
            await human_delay(3, 5)
            return
    except Exception:
        pass

    # login
    try:
        await page.click("text=Login", timeout=10000)
    except Exception as e:
        print(f"ℹ️ Naukri AutoAI: Login link not clickable ({e}); assuming already logged in.")
        return

    await human_delay(1, 2)

    await human_typing(
        page.locator("//input[@placeholder='Enter your active Email ID / Username']"),
        EMAIL
    )

    await human_typing(
        page.locator("//input[@placeholder='Enter your password']"),
        PASSWORD
    )

    await page.click("//button[@type='submit']")

    try:
        await page.wait_for_selector('.nI-gNb-header__logo', timeout=15000)
        print("✅ Naukri AutoAI: Logged in. Cooling down...")
    except Exception as e:
        print(f"⚠️ Naukri AutoAI: Login confirmation not detected ({e}); continuing anyway.")

    await human_mouse_move(page)
    await human_delay(6, 10)
