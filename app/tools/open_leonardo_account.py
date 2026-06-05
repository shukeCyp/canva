"""Open Leonardo.ai with account cookies/session data."""

import argparse
import json
import os
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT_DIR = Path(__file__).resolve().parents[2]
ORIGIN = "https://app.leonardo.ai"
TARGET_URL = f"{ORIGIN}/"


def _safe_name(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "account")


def _load_json(path, default):
    try:
        if path and Path(path).exists():
            return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _normalize_cookie(cookie):
    name = cookie.get("name")
    value = cookie.get("value")
    domain = cookie.get("domain")
    path = cookie.get("path", "/")
    if not name or value is None or not domain:
        return None

    result = {
        "name": name,
        "value": str(value),
        "domain": domain,
        "path": path,
        "httpOnly": bool(cookie.get("httpOnly", False)),
        "secure": bool(cookie.get("secure", True)),
    }

    expires = cookie.get("expires")
    if isinstance(expires, (int, float)) and expires > 0:
        result["expires"] = int(expires)

    same_site = cookie.get("sameSite")
    if same_site in ("Strict", "Lax", "None"):
        result["sameSite"] = same_site
    return result


def _account_cookies(account):
    cookies = account.get("cookies") or []
    if not cookies:
        cookies = _load_json(ROOT_DIR / "cookies.txt", [])

    normalized = []
    seen = set()
    for cookie in cookies:
        item = _normalize_cookie(cookie)
        if not item:
            continue
        key = (item["name"], item["domain"], item["path"])
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)

    session_token = account.get("session_token")
    has_session_cookie = any(c["name"] == "__Secure-better-auth.session_token" for c in normalized)
    if session_token and not has_session_cookie:
        normalized.append({
            "name": "__Secure-better-auth.session_token",
            "value": session_token,
            "domain": "app.leonardo.ai",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "Lax",
        })
    return normalized


def _storage_script(account):
    session = {
        "accessToken": account.get("access_token", ""),
        "hasuraUserId": account.get("hasura_user_id", ""),
        "cognitoSub": account.get("cognito_sub", ""),
        "email": account.get("email", ""),
        "userId": account.get("hasura_user_id", ""),
    }
    payload = json.dumps(session)
    return f"""
(() => {{
  const session = {payload};
  const pairs = {{
    accessToken: session.accessToken,
    access_token: session.accessToken,
    hasuraUserId: session.hasuraUserId,
    cognitoSub: session.cognitoSub,
    leo_session: JSON.stringify(session),
    session: JSON.stringify({{ session }}),
  }};
  for (const [key, value] of Object.entries(pairs)) {{
    if (value) {{
      window.localStorage.setItem(key, value);
      window.sessionStorage.setItem(key, value);
    }}
  }}
}})();
"""


def open_account(account_path):
    account = _load_json(account_path, {})
    email = account.get("email", "account")
    profile_dir = ROOT_DIR / "data" / "browser_profiles" / _safe_name(email)
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
        )

        cookies = _account_cookies(account)
        if cookies:
            context.add_cookies(cookies)

        context.add_init_script(_storage_script(account))
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        page.evaluate(_storage_script(account))
        page.reload(wait_until="domcontentloaded", timeout=60000)

        while context.pages:
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    args = parser.parse_args()
    open_account(args.account)


if __name__ == "__main__":
    main()
