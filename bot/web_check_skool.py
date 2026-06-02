import sys
import json
import asyncio
import os
import time
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "gates"))
from skool_accounts import (
    _make_fresh_client, _do_login, _validate_session, _preflight,
    _load_statuses, _save_statuses, _account_statuses, _close_client,
    CHROME_IMPERSONATE, CLIENT_TIMEOUT,
)
from curl_cffi.requests import AsyncSession

STATUS_FILE = os.path.join(os.path.dirname(__file__), "skool_status.json")


def load_status():
    try:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_status(data):
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f)


def _make_no_proxy_client():
    return AsyncSession(
        impersonate="chrome131",
        timeout=CLIENT_TIMEOUT,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://www.skool.com",
            "Referer": "https://www.skool.com/",
            "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        },
    )


async def _try_check(client, email, password):
    await _preflight(client)
    await asyncio.sleep(random.uniform(0.3, 0.8))

    r = await _do_login(client, email, password)

    if r.status_code == 200:
        session_cookies = dict(client.cookies) if hasattr(client, "cookies") else {}
        auth_token = session_cookies.get("auth_token")
        if auth_token:
            return {"status": "active", "detail": "Login successful"}
        if session_cookies:
            valid = await _validate_session(client)
            if valid:
                return {"status": "active", "detail": "Session validated"}
        try:
            body = r.json()
            err = str(body)[:100]
        except Exception:
            err = r.text[:100]
        return {"status": "dead", "detail": f"Login returned 200 but no auth: {err}"}

    elif r.status_code == 401:
        return {"status": "dead", "detail": "Invalid credentials"}

    elif r.status_code == 422:
        try:
            body = r.json()
            fields = body.get("fields", [])
            if fields:
                err_msg = fields[0].get("error", r.text[:100])
                return {"status": "dead", "detail": err_msg}
        except Exception:
            pass
        return {"status": "dead", "detail": f"Validation error: {r.text[:100]}"}

    elif r.status_code == 403:
        return {"status": "unknown", "detail": "Blocked by anti-bot (403)"}

    elif r.status_code == 429:
        return {"status": "unknown", "detail": "Rate limited (429)"}

    else:
        try:
            body = r.text[:100]
        except Exception:
            body = "?"
        return {"status": "dead", "detail": f"HTTP {r.status_code}: {body}"}


async def check_account(email, password):
    client = _make_fresh_client()
    try:
        result = await _try_check(client, email, password)
        return result
    except Exception as e:
        err_str = str(e).lower()
        is_proxy_error = any(k in err_str for k in ["proxy", "tunnel", "407", "connect"])
        if is_proxy_error:
            await _close_client(client)
            client = _make_no_proxy_client()
            try:
                result = await _try_check(client, email, password)
                return result
            except Exception as e2:
                return {"status": "unknown", "detail": f"Error: {str(e2)[:100]}"}
        return {"status": "unknown", "detail": f"Error: {str(e)[:100]}"}
    finally:
        await _close_client(client)


async def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: web_check_skool.py <email> <password>"}))
        return

    email = sys.argv[1]
    password = sys.argv[2]

    result = await check_account(email, password)

    status_data = load_status()
    status_data[email] = result["status"]
    save_status(status_data)

    result["email"] = email
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
