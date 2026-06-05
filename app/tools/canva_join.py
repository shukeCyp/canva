import asyncio
import json
import random
from playwright.async_api import async_playwright

DEFAULT_CANVA_URL = (
    "https://www.canva.com/brand/join"
    "?token=XgEBGeDOtDGukpYWODB-dA"
    "&referrer=team-invite"
)

LEONARDO_URL = "https://www.canva.com/business/features/leonardo-ai/"

CREDENTIAL_RAW = "LindsyBillingsleykvz7g@cecolm.us----Phat3479"

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1680, "height": 1050},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
    {"width": 2560, "height": 1440},
]

CHROME_VERSIONS = [131, 130, 129, 128, 127]

GEOLOCATIONS = [
    {"latitude": 31.2304, "longitude": 121.4737},
    {"latitude": 39.9042, "longitude": 116.4074},
    {"latitude": 23.1291, "longitude": 113.2644},
    {"latitude": 30.5728, "longitude": 104.0668},
    {"latitude": 22.5431, "longitude": 114.0579},
]

TIMEZONES = ["Asia/Shanghai", "Asia/Chongqing", "Asia/Harbin", "Asia/Urumqi"]

SESSION_URL_PATTERN = "**/api/auth/get-session"


def random_fingerprint():
    vp = random.choice(VIEWPORTS)
    screen = {
        "width": vp["width"] + random.randint(0, 200),
        "height": vp["height"] + random.randint(50, 150),
    }
    chrome_version = random.choice(CHROME_VERSIONS)
    geo = random.choice(GEOLOCATIONS)
    tz = random.choice(TIMEZONES)
    platform = random.choice(["MacIntel", "Win32"])

    if platform == "MacIntel":
        ua = (
            f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome_version}.0.0.0 Safari/537.36"
        )
    else:
        ua = (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome_version}.0.0.0 Safari/537.36"
        )

    ctx = {
        "user_agent": ua,
        "viewport": vp,
        "screen": screen,
        "device_scale_factor": random.choice([1, 2]),
        "is_mobile": False,
        "has_touch": False,
        "locale": "zh-CN",
        "timezone_id": tz,
        "geolocation": geo,
        "permissions": ["geolocation"],
        "color_scheme": random.choice(["light", "dark"]),
    }

    js = {
        "platform": platform,
        "hardwareConcurrency": random.choice([4, 8, 12, 16]),
        "deviceMemory": random.choice([4, 8, 16]),
    }

    return ctx, js


def parse_credentials(raw: str):
    email, password = raw.split("----")
    return email, password


async def login_flow(email, password, join_url=None, headless=False):
    """ session  dict.

    Args:
        email: 
        password: 
        join_url: Canva  ()
        headless: 
    """

    canva_url = join_url or DEFAULT_CANVA_URL

    print(f"[INFO] email: {email}")
    print(f"[INFO] password: {password}")
    print(f"[INFO] join_url: {canva_url}")
    print(f"[INFO] headless: {headless}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome",
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )

        fp_ctx, fp_js = random_fingerprint()
        print(
            f"[INFO] fingerprint: viewport={fp_ctx['viewport']}, "
            f"platform={fp_js['platform']}, cores={fp_js['hardwareConcurrency']}, "
            f"memory={fp_js['deviceMemory']}GB"
        )

        context = await browser.new_context(**fp_ctx)

        #  session 
        captured_session = {}

        #  get-session 
        async def on_response(response):
            if SESSION_URL_PATTERN.replace("**", "") in response.url:
                try:
                    body = await response.json()
                    if body and body != "null":
                        captured_session["data"] = body
                        print(f"[SESSION]   get-session !")
                        print(f"[SESSION] response status: {response.status}")
                except Exception:
                    pass

        context.on("response", on_response)

        page = await context.new_page()

        await page.add_init_script(f"""
            Object.defineProperty(navigator, 'platform', {{ get: () => '{fp_js["platform"]}' }});
            Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {fp_js["hardwareConcurrency"]} }});
            Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {fp_js["deviceMemory"]} }});
            Object.defineProperty(navigator, 'webdriver', {{ get: () => false }});
            delete navigator.__proto__.webdriver;
        """)

        # =====================================================
        # Step 1:  Canva 
        # =====================================================
        await page.goto(canva_url, wait_until="domcontentloaded", timeout=30000)
        print(f"[INFO] page loaded: {await page.title()}")
        await asyncio.sleep(3)

        # =====================================================
        # Step 2:  "Google"
        # =====================================================
        google_btn = page.locator("span:has-text('Google帐户登录')").first
        await google_btn.wait_for(state="visible", timeout=10000)
        await google_btn.click()
        print("[INFO] clicked Google")
        await asyncio.sleep(3)

        # =====================================================
        # Step 3:  Google 
        # =====================================================
        google_popup = None
        for _ in range(10):
            for p in context.pages:
                if "google" in p.url.lower():
                    google_popup = p
                    break
            if google_popup:
                break
            await asyncio.sleep(1)

        if not google_popup:
            print("[ERROR]  Google ")
            await browser.close()
            return

        print(f"[INFO] Google page: {google_popup.url[:80]}")
        await asyncio.sleep(2)

        # =====================================================
        # Step 4: 
        # =====================================================
        email_input = google_popup.locator("#identifierId").first
        await email_input.wait_for(state="visible", timeout=15000)
        await email_input.fill(email)
        print(f"[INFO] filled email: {email}")
        await asyncio.sleep(1)

        # =====================================================
        # Step 5:  ""
        # =====================================================
        next_btn = google_popup.locator("span:has-text('下一步')").first
        await next_btn.click()
        print("[INFO] clicked  (email)")
        await asyncio.sleep(3)

        #  CAPTCHA
        captcha_input = google_popup.locator('#ca').first
        if await captcha_input.is_visible():
            print("[ERROR] CAPTCHA ")
            await browser.close()
            raise RuntimeError("CAPTCHA_DETECTED")

        # =====================================================
        # Step 6: 
        # =====================================================
        pwd_input = google_popup.locator('input[type="password"]').first
        await pwd_input.wait_for(state="visible", timeout=15000)
        await pwd_input.fill(password)
        print("[INFO] filled password")
        await asyncio.sleep(1)

        # =====================================================
        # Step 7:  ""
        # =====================================================
        next_btn = google_popup.locator("span:has-text('下一步')").first
        await next_btn.click()
        print("[INFO] clicked  (password)")
        await asyncio.sleep(3)

        # =====================================================
        # Step 8:  ""
        # =====================================================
        try:
            confirm_btn = google_popup.locator("#confirm").first
            await confirm_btn.wait_for(state="visible", timeout=10000)
            await confirm_btn.click()
            print("[INFO] clicked ")
            await asyncio.sleep(2)
        except Exception:
            print("[WARN]  ")

        # =====================================================
        # Step 9:  "Continue"
        # =====================================================
        try:
            continue_btn = google_popup.locator("span:has-text('Continue')").first
            await continue_btn.wait_for(state="visible", timeout=10000)
            await continue_btn.click()
            print("[INFO] clicked Continue")
            await asyncio.sleep(2)
        except Exception:
            print("[WARN] Continue ")

        # =====================================================
        # Step 10:  ""
        # =====================================================
        await asyncio.sleep(3)
        try:
            agree_btn = page.locator("span:has-text('我同意')").first
            await agree_btn.wait_for(state="visible", timeout=10000)
            await agree_btn.click()
            print("[INFO] clicked ")
            await asyncio.sleep(2)
        except Exception:
            print("[WARN]  ")

        # =====================================================
        # Step 11: 
        # =====================================================
        try:
            close_btn = page.locator('button[aria-label="关闭"]').first
            await close_btn.wait_for(state="visible", timeout=10000)
            await close_btn.click()
            print("[INFO] clicked ")
            await asyncio.sleep(2)
        except Exception:
            print("[WARN]  ")

        # =====================================================
        # Step 12:  Leonardo.ai
        # =====================================================
        new_page = await context.new_page()
        await new_page.goto(LEONARDO_URL, wait_until="domcontentloaded", timeout=30000)
        print(f"[INFO] Leonardo page: {await new_page.title()}")
        await asyncio.sleep(3)

        # =====================================================
        # Step 13:  "Get started with Leonardo.Ai"
        # =====================================================
        get_started = new_page.locator("span:has-text('Get started with Leonardo.Ai')").first
        await get_started.wait_for(state="visible", timeout=10000)

        async with context.expect_page() as new_tab_info:
            await get_started.click()
        leonardo_page = await new_tab_info.value
        print(f"[INFO] Leonardo tab: {leonardo_page.url[:80]}")
        await asyncio.sleep(2)

        # =====================================================
        # Step 14:  ""
        # =====================================================
        try:
            allow_btn = leonardo_page.locator("span:has-text('允许')").first
            await allow_btn.wait_for(state="visible", timeout=10000)
            await allow_btn.click()
            print("[INFO] clicked ")
            await asyncio.sleep(3)
        except Exception:
            print("[WARN]  ")

        # =====================================================
        # Step 15:  get-session 
        # =====================================================
        print("[INFO]  get-session ...")
        for _ in range(30):
            if captured_session.get("data"):
                break
            await asyncio.sleep(1)

        # =====================================================
        # Step 16:  session 
        # =====================================================
        session_data = captured_session.get("data", {})
        all_cookies = await context.cookies()
        if session_data:
            session_data["cookies"] = all_cookies

        # 
        if session_data:
            with open("session.json", "w", encoding="utf-8") as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)
            print(f"[INFO]  session saved to session.json")
        else:
            print("[WARN]   get-session")

        with open("cookies.txt", "w", encoding="utf-8") as f:
            json.dump(all_cookies, f, indent=2, ensure_ascii=False)
        print(f"[INFO]  {len(all_cookies)} cookies saved to cookies.txt")

        print("[INFO] 3 ")
        await asyncio.sleep(3)
        await browser.close()

        return session_data


async def _async_main():
    email, password = parse_credentials(CREDENTIAL_RAW)
    return await login_flow(email, password, headless=False)


def main():
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
