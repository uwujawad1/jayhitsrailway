import asyncio
import json
import os
import time
import random
import logging
from curl_cffi.requests import AsyncSession

logger = logging.getLogger("skool_accounts")

SKOOL_API = "https://api2.skool.com"
ACCOUNTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skool_accounts.json")
SESSION_TTL = 900
MIN_REQUEST_INTERVAL = 0.5
MAX_CLIENT_AGE = 3600
FAIL_COOLDOWN = 300
CLIENT_TIMEOUT = 45
LOGIN_TIMEOUT = 30
VALIDATE_TIMEOUT = 15
PREFLIGHT_TIMEOUT = 20

PROXY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "proxy.txt")

_proxy_disabled_until = 0


def _load_proxy_list():
    if not os.path.exists(PROXY_FILE):
        return []
    try:
        with open(PROXY_FILE, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return []


def _mark_proxies_dead():
    global _proxy_disabled_until
    _proxy_disabled_until = time.time() + 300
    logger.warning("All proxies marked dead, disabling for 5 minutes")


def _get_random_proxy():
    global _proxy_disabled_until
    if time.time() < _proxy_disabled_until:
        return None
    proxies = _load_proxy_list()
    if not proxies:
        return None
    raw = random.choice(proxies)
    parts = raw.split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
        return f"http://{user}:{pwd}@{host}:{port}"
    elif len(parts) == 2:
        return f"http://{parts[0]}:{parts[1]}"
    return None

_accounts = []
_account_clients = {}
_account_locks = {}
_account_last_request = {}
_accounts_load_ts = 0
_accounts_lock = asyncio.Lock()
_failed_accounts = {}
_round_robin_index = 0
_user_rr_indices = {}
_warmup_done = False

STATUS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skool_status.json")
_account_statuses = {}
_status_loaded = False


def _load_statuses():
    global _account_statuses, _status_loaded
    if _status_loaded:
        return
    try:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, "r") as f:
                _account_statuses = json.load(f)
    except Exception:
        _account_statuses = {}
    _status_loaded = True


def _save_statuses():
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(_account_statuses, f)
    except Exception as e:
        logger.warning(f"Error saving statuses: {e}")

CHROME_IMPERSONATE = "chrome131"


def _load_accounts():
    global _accounts, _accounts_load_ts
    now = time.time()
    if _accounts and (now - _accounts_load_ts) < 60:
        return _accounts

    accounts = []

    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r") as f:
                content = f.read().strip()
            if content:
                data = json.loads(content)
                if isinstance(data, list):
                    accounts = data
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to read skool_accounts.json: {e}")
            if _accounts:
                return _accounts
        except Exception as e:
            logger.warning(f"Unexpected error loading skool_accounts.json: {e}")
            if _accounts:
                return _accounts

    env_email = os.environ.get("SKOOL_EMAIL", "")
    env_pass = os.environ.get("SKOOL_PASS", "")
    if env_email and env_pass:
        env_exists = any(a.get("email") == env_email for a in accounts)
        if not env_exists:
            accounts.insert(0, {"email": env_email, "password": env_pass})

    _accounts = accounts
    _accounts_load_ts = now
    return accounts


def get_account_count():
    return len(_load_accounts())


def _get_lock(email):
    if email not in _account_locks:
        _account_locks[email] = asyncio.Lock()
    return _account_locks[email]


async def get_next_account():
    global _round_robin_index
    accounts = _load_accounts()
    if not accounts:
        return None

    now = time.time()
    async with _accounts_lock:
        tried = 0
        while tried < len(accounts):
            idx = _round_robin_index % len(accounts)
            _round_robin_index += 1
            account = accounts[idx]
            email = account.get("email", "")
            fail_info = _failed_accounts.get(email)
            if fail_info and (now - fail_info["ts"]) < FAIL_COOLDOWN and fail_info["count"] >= 5:
                tried += 1
                continue
            return account

        _round_robin_index += 1
        return accounts[_round_robin_index % len(accounts)]


async def get_fallback_account(exclude_email):
    accounts = _load_accounts()
    if not accounts:
        return None
    now = time.time()
    async with _accounts_lock:
        for account in accounts:
            email = account.get("email", "")
            if email == exclude_email:
                continue
            fail_info = _failed_accounts.get(email)
            if fail_info and (now - fail_info["ts"]) < FAIL_COOLDOWN and fail_info["count"] >= 5:
                continue
            return account
    return None


import threading
_file_lock = threading.Lock()

def _auto_remove_dead_account(email):
    global _accounts, _accounts_load_ts
    removed_from = []

    with _file_lock:
        try:
            if os.path.exists(ACCOUNTS_FILE):
                with open(ACCOUNTS_FILE, "r") as f:
                    global_accs = json.load(f)
                before = len(global_accs)
                global_accs = [a for a in global_accs if a.get("email", "").lower() != email.lower()]
                if len(global_accs) < before:
                    import tempfile
                    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(ACCOUNTS_FILE), suffix=".tmp")
                    try:
                        with os.fdopen(tmp_fd, "w") as tmp_f:
                            json.dump(global_accs, tmp_f, indent=2)
                        os.replace(tmp_path, ACCOUNTS_FILE)
                    except:
                        try:
                            os.remove(tmp_path)
                        except:
                            pass
                        raise
                    removed_from.append("global")
                    _accounts_load_ts = 0
        except Exception as e:
            logger.warning(f"Error removing dead account {email} from global: {e}")

        try:
            if os.path.exists(USER_SKOOL_FILE):
                with open(USER_SKOOL_FILE, "r") as f:
                    user_data = json.load(f)
                changed = False
                for uid in list(user_data.keys()):
                    before = len(user_data[uid])
                    user_data[uid] = [a for a in user_data[uid] if a.get("email", "").lower() != email.lower()]
                    if len(user_data[uid]) < before:
                        changed = True
                        removed_from.append(f"user:{uid}")
                    if not user_data[uid]:
                        del user_data[uid]
                if changed:
                    import tempfile
                    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(USER_SKOOL_FILE), suffix=".tmp")
                    try:
                        with os.fdopen(tmp_fd, "w") as tmp_f:
                            json.dump(user_data, tmp_f, indent=2)
                        os.replace(tmp_path, USER_SKOOL_FILE)
                    except:
                        try:
                            os.remove(tmp_path)
                        except:
                            pass
                        raise
                    global _user_skool_cache, _user_skool_ts
                    _user_skool_cache = user_data
                    _user_skool_ts = time.time()
        except Exception as e:
            logger.warning(f"Error removing dead account {email} from user accounts: {e}")

    if removed_from:
        logger.info(f"Auto-removed dead account {email} from: {', '.join(removed_from)}")

    if email in _account_clients:
        _account_clients[email] = {
            "client": None, "logged_in_ts": 0, "valid": False,
            "created_ts": 0, "last_login_error": "",
        }

_auth_fail_counts = {}

def _mark_account_failed(email, is_login_error=False):
    _load_statuses()
    now = time.time()
    if email not in _failed_accounts:
        _failed_accounts[email] = {"count": 0, "ts": now}
    info = _failed_accounts[email]
    if (now - info["ts"]) > FAIL_COOLDOWN:
        info["count"] = 1
        info["ts"] = now
    else:
        info["count"] += 1
        info["ts"] = now

    if is_login_error:
        if email not in _auth_fail_counts:
            _auth_fail_counts[email] = {"count": 0, "ts": now}
        af = _auth_fail_counts[email]
        if (now - af["ts"]) > FAIL_COOLDOWN * 2:
            af["count"] = 1
            af["ts"] = now
        else:
            af["count"] += 1
            af["ts"] = now
        if af["count"] >= 3:
            _account_statuses[email] = "dead"
            _save_statuses()
            _auto_remove_dead_account(email)
            logger.info(f"Auto-removed {email} after {af['count']} consecutive login failures")
            return

    if info["count"] >= 5:
        _account_statuses[email] = "dead"
        _save_statuses()


def _mark_account_success(email):
    _load_statuses()
    if email in _failed_accounts:
        _failed_accounts[email] = {"count": 0, "ts": 0}
    if email in _auth_fail_counts:
        _auth_fail_counts[email] = {"count": 0, "ts": 0}
    _account_statuses[email] = "active"
    _save_statuses()


def get_account_status(email):
    _load_statuses()
    return _account_statuses.get(email, "unknown")


def get_all_accounts_with_status():
    global _accounts_load_ts
    _load_statuses()
    _accounts_load_ts = 0
    accounts = _load_accounts()
    result = []
    for a in accounts:
        email = a.get("email", "?")
        status = _account_statuses.get(email, "unknown")
        result.append({"email": email, "status": status})
    return result


def mark_account_dead(email):
    _load_statuses()
    _account_statuses[email] = "dead"
    _save_statuses()


def mark_account_active(email):
    _load_statuses()
    _account_statuses[email] = "active"
    _save_statuses()


def _get_client_data(email):
    if email not in _account_clients:
        _account_clients[email] = {
            "client": None,
            "logged_in_ts": 0,
            "valid": False,
            "created_ts": 0,
            "last_login_error": "",
        }
    return _account_clients[email]


def _make_fresh_client(user_proxy=None):
    proxy = user_proxy or _get_random_proxy()
    kwargs = {
        "impersonate": CHROME_IMPERSONATE,
        "timeout": CLIENT_TIMEOUT,
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://www.skool.com",
            "Referer": "https://www.skool.com/",
            "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        },
    }
    if proxy:
        kwargs["proxy"] = proxy
        logger.debug(f"Using proxy: {proxy.split('@')[-1] if '@' in proxy else proxy}")
    return AsyncSession(**kwargs)


def _is_client_closed(client):
    if client is None:
        return True
    try:
        if hasattr(client, 'closed') and client.closed:
            return True
    except Exception:
        pass
    return False


async def _close_client(client):
    if client is None:
        return
    try:
        await client.close()
    except Exception:
        try:
            client.close()
        except Exception:
            pass


async def _ensure_client(email, user_proxy=None):
    data = _get_client_data(email)
    now = time.time()
    needs_new = (
        data["client"] is None
        or _is_client_closed(data["client"])
        or (data.get("created_ts", 0) and (now - data["created_ts"]) > MAX_CLIENT_AGE)
    )
    if needs_new:
        await _close_client(data["client"])
        data["client"] = _make_fresh_client(user_proxy=user_proxy)
        data["logged_in_ts"] = 0
        data["valid"] = False
        data["created_ts"] = now
    return data


async def _throttle_request(email):
    now = time.time()
    last = _account_last_request.get(email, 0)
    wait = MIN_REQUEST_INTERVAL - (now - last)
    if wait > 0:
        await asyncio.sleep(wait)
    _account_last_request[email] = time.time()


async def _do_login(client, email, password):
    r = await client.post(
        f"{SKOOL_API}/auth/login",
        json={"email": email, "password": password},
        timeout=LOGIN_TIMEOUT,
    )
    return r


async def _preflight(client):
    try:
        r = await client.get(
            "https://www.skool.com/",
            timeout=PREFLIGHT_TIMEOUT,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
                "Cache-Control": "max-age=0",
            },
        )
        logger.debug(f"Preflight status: {r.status_code}, cookies: {list(client.cookies.keys()) if hasattr(client, 'cookies') else '?'}")
        return r.status_code < 400
    except Exception as e:
        logger.debug(f"Preflight failed: {e}")
        return False


async def _validate_session(client):
    try:
        r = await client.get(f"{SKOOL_API}/self", timeout=VALIDATE_TIMEOUT)
        if r.status_code == 200:
            body = r.json()
            return bool(body.get("id") or body.get("email"))
        return False
    except Exception:
        return False


async def get_authed_client(account, force_refresh=False, user_proxy=None):
    email = account["email"]
    password = account["password"]

    data = await _ensure_client(email, user_proxy=user_proxy)
    client = data["client"]

    now = time.time()
    session_age = now - data["logged_in_ts"]

    if not force_refresh and data["valid"] and session_age < SESSION_TTL:
        await _throttle_request(email)
        return client

    if not force_refresh and data["valid"] and session_age < SESSION_TTL * 2:
        await _throttle_request(email)
        if await _validate_session(client):
            data["logged_in_ts"] = now
            data["valid"] = True
            _mark_account_success(email)
            return client
        logger.info(f"[{email[:15]}] Session validation failed, re-logging in")

    data["valid"] = False

    for login_attempt in range(3):
        try:
            if login_attempt > 0:
                await _close_client(client)
                client = _make_fresh_client(user_proxy=user_proxy)
                data["client"] = client
                data["created_ts"] = time.time()
                await asyncio.sleep(random.uniform(1.0, 2.5))

            if data.get("created_ts", 0) and (time.time() - data["created_ts"]) < 10:
                await _preflight(client)
                await asyncio.sleep(random.uniform(0.3, 0.8))

            r = await _do_login(client, email, password)

            if r.status_code == 200:
                session_cookies = dict(client.cookies) if hasattr(client, 'cookies') else {}
                auth_token = session_cookies.get("auth_token")
                if auth_token:
                    data["logged_in_ts"] = time.time()
                    data["valid"] = True
                    data["last_login_error"] = ""
                    _mark_account_success(email)
                    await _throttle_request(email)
                    logger.info(f"[{email[:15]}] Login OK (auth_token)")
                    return client
                if session_cookies:
                    valid = await _validate_session(client)
                    if valid:
                        data["logged_in_ts"] = time.time()
                        data["valid"] = True
                        data["last_login_error"] = ""
                        _mark_account_success(email)
                        await _throttle_request(email)
                        logger.info(f"[{email[:15]}] Login OK (session validated)")
                        return client
                try:
                    body = r.json()
                    err_detail = str(body)[:100]
                except Exception:
                    err_detail = r.text[:100]
                data["last_login_error"] = f"200 but no auth: {err_detail}"
                logger.warning(f"[{email[:15]}] Login 200 but no auth_token. cookies={list(session_cookies.keys())}, body={err_detail}")

            elif r.status_code == 403:
                data["last_login_error"] = f"403 blocked (anti-bot)"
                logger.warning(f"[{email[:15]}] Login 403 - anti-bot block, will retry with new client")
                if login_attempt < 2:
                    await _close_client(client)
                    if login_attempt == 1:
                        _mark_proxies_dead()
                    client = _make_fresh_client(user_proxy=user_proxy)
                    data["client"] = client
                    data["created_ts"] = time.time()
                    await asyncio.sleep(random.uniform(2.0, 4.0))
                    await _preflight(client)
                    await asyncio.sleep(random.uniform(0.5, 1.0))
                    continue
                _mark_account_failed(email)
                return None

            elif r.status_code == 429:
                wait = random.uniform(5, 10) * (login_attempt + 1)
                data["last_login_error"] = f"429 rate limited"
                logger.warning(f"[{email[:15]}] Login 429, waiting {wait:.0f}s")
                await asyncio.sleep(wait)
                continue

            else:
                try:
                    body = r.text[:150]
                except Exception:
                    body = "?"
                data["last_login_error"] = f"HTTP {r.status_code}: {body}"
                logger.warning(f"[{email[:15]}] Login failed: {r.status_code} - {body}")

            _mark_account_failed(email, is_login_error=True)
            if login_attempt < 2:
                await asyncio.sleep(random.uniform(1, 2))
                continue
            return None

        except Exception as e:
            err_str = str(e)
            is_proxy_error = any(s in err_str for s in [
                "407", "CONNECT tunnel", "proxy", "Proxy",
                "Name or service not known", "Errno -2", "getaddrinfo",
                "Connection refused", "tunnel failed",
            ])
            if is_proxy_error:
                logger.warning(f"[{email[:15]}] Proxy/network error detected: {err_str[:100]}, switching to direct")
                if not user_proxy:
                    _mark_proxies_dead()
                await _close_client(client)
                client = _make_fresh_client(user_proxy=user_proxy)
                data["client"] = client
                data["created_ts"] = time.time()
                continue
            data["last_login_error"] = f"Exception: {e}"
            logger.warning(f"[{email[:15]}] Login exception: {e}")
            if login_attempt < 2:
                await asyncio.sleep(random.uniform(1, 2))
                continue
            _mark_account_failed(email)
            return None

    _mark_account_failed(email, is_login_error=True)
    return None


def get_last_login_error(account):
    email = account["email"]
    data = _get_client_data(email)
    return data.get("last_login_error", "Unknown")


def invalidate_session(account):
    email = account["email"]
    data = _get_client_data(email)
    data["valid"] = False
    data["logged_in_ts"] = 0


async def close_client(account):
    email = account["email"]
    data = _get_client_data(email)
    await _close_client(data["client"])
    data["client"] = None
    data["valid"] = False
    data["logged_in_ts"] = 0


def get_account_lock(account):
    return _get_lock(account["email"])


async def reset_all_clients():
    global _warmup_done
    accounts = _load_accounts()
    for account in accounts:
        email = account["email"]
        data = _get_client_data(email)
        await _close_client(data["client"])
        data["client"] = None
        data["valid"] = False
        data["logged_in_ts"] = 0
    _warmup_done = False
    logger.info("All clients reset")


async def refresh_all_clients():
    accounts = _load_accounts()
    if not accounts:
        return 0

    for account in accounts:
        email = account["email"]
        data = _get_client_data(email)
        await _close_client(data["client"])
        data["client"] = _make_fresh_client()
        data["created_ts"] = time.time()
        data["valid"] = False
        data["logged_in_ts"] = 0

    login_sem = asyncio.Semaphore(2)

    async def _relogin(account, idx):
        await asyncio.sleep(idx * 1.0)
        async with login_sem:
            email = account["email"]
            lock = _get_lock(email)
            async with lock:
                try:
                    client = await get_authed_client(account)
                    if client:
                        return True
                except Exception:
                    pass
                return False

    results = await asyncio.gather(*[_relogin(a, i) for i, a in enumerate(accounts)])
    success = sum(1 for r in results if r)
    logger.info(f"Refreshed clients: {success}/{len(accounts)} OK")
    return success


async def warmup_all_sessions():
    global _warmup_done
    accounts = _load_accounts()
    if not accounts:
        return 0

    login_sem = asyncio.Semaphore(2)

    async def _warmup_one(account, idx):
        await asyncio.sleep(idx * 1.0)
        async with login_sem:
            email = account["email"]
            lock = _get_lock(email)
            async with lock:
                try:
                    client = await get_authed_client(account)
                    if client:
                        logger.info(f"[{email[:15]}] Warmup OK")
                        return True
                    else:
                        logger.warning(f"[{email[:15]}] Warmup FAILED")
                        return False
                except Exception as e:
                    logger.warning(f"[{email[:15]}] Warmup error: {e}")
                    return False

    results = await asyncio.gather(*[_warmup_one(a, i) for i, a in enumerate(accounts)])
    success = sum(1 for r in results if r)

    _warmup_done = True
    return success


def is_warmed_up():
    return _warmup_done


async def login_session(client, account, force_refresh=False):
    email = account["email"]
    password = account["password"]

    for login_attempt in range(2):
        try:
            r = await _do_login(client, email, password)

            if r.status_code == 200:
                session_cookies = dict(client.cookies) if hasattr(client, 'cookies') else {}
                auth_token = session_cookies.get("auth_token")
                if auth_token:
                    _mark_account_success(email)
                    return True
                if session_cookies:
                    valid = await _validate_session(client)
                    if valid:
                        _mark_account_success(email)
                        return True

            if r.status_code == 429:
                await asyncio.sleep(random.uniform(5, 10) * (login_attempt + 1))
                continue

            _mark_account_failed(email, is_login_error=True)
            if login_attempt < 1:
                await asyncio.sleep(random.uniform(1, 2))
                continue
            return False

        except Exception:
            if login_attempt < 1:
                await asyncio.sleep(random.uniform(1, 2))
                continue
            _mark_account_failed(email)
            return False

    _mark_account_failed(email, is_login_error=True)
    return False


def clear_account_session(account):
    invalidate_session(account)


USER_SKOOL_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "user_skool_accounts.json")
_user_skool_cache = {}
_user_skool_ts = 0


def _load_user_skool_accounts():
    global _user_skool_cache, _user_skool_ts
    now = time.time()
    if _user_skool_cache and (now - _user_skool_ts) < 30:
        return _user_skool_cache
    try:
        if os.path.exists(USER_SKOOL_FILE):
            with open(USER_SKOOL_FILE, "r") as f:
                content = f.read().strip()
            if content:
                parsed = json.loads(content)
                _user_skool_cache = parsed
            elif not _user_skool_cache:
                _user_skool_cache = {}
        elif not _user_skool_cache:
            _user_skool_cache = {}
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to read user_skool_accounts.json: {e}")
        if not _user_skool_cache:
            for attempt in range(2):
                time.sleep(0.2)
                try:
                    with open(USER_SKOOL_FILE, "r") as f:
                        content = f.read().strip()
                    if content:
                        _user_skool_cache = json.loads(content)
                        break
                except Exception:
                    pass
            else:
                _user_skool_cache = {}
    except Exception as e:
        logger.warning(f"Unexpected error loading user_skool_accounts.json: {e}")
        if not _user_skool_cache:
            _user_skool_cache = {}
    _user_skool_ts = now
    return _user_skool_cache


def _save_user_skool_accounts(data):
    global _user_skool_cache, _user_skool_ts
    try:
        import tempfile
        dir_name = os.path.dirname(USER_SKOOL_FILE)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, USER_SKOOL_FILE)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        _user_skool_cache = data
        _user_skool_ts = time.time()
    except Exception as e:
        logger.warning(f"Error saving user skool accounts: {e}")


def get_user_skool_accounts(user_id):
    data = _load_user_skool_accounts()
    return data.get(str(user_id), [])


def get_all_user_skool_accounts():
    data = _load_user_skool_accounts()
    seen = set()
    result = []
    for uid, accounts in data.items():
        for acc in accounts:
            email = acc.get("email", "")
            if email not in seen:
                seen.add(email)
                result.append({"email": email, "password": acc.get("password", ""), "owner": uid})
    return result


def _clear_account_status(email):
    _load_statuses()
    changed = False
    if email in _account_statuses:
        del _account_statuses[email]
        changed = True
    if email in _failed_accounts:
        del _failed_accounts[email]
        changed = True
    if email in _account_clients:
        _account_clients[email] = {
            "client": None,
            "logged_in_ts": 0,
            "valid": False,
            "created_ts": 0,
            "last_login_error": "",
        }
    if changed:
        _save_statuses()


def _reset_user_rr(user_id):
    uid = str(user_id)
    if uid in _user_rr_indices:
        del _user_rr_indices[uid]


def add_user_skool_account(user_id, email, password):
    data = _load_user_skool_accounts()
    uid = str(user_id)
    if uid not in data:
        data[uid] = []
    for acc in data[uid]:
        if acc.get("email") == email:
            if acc.get("password") != password:
                acc["password"] = password
                _save_user_skool_accounts(data)
                _clear_account_status(email)
                _reset_user_rr(user_id)
                return True, "updated"
            return False, "already exists"
    data[uid].append({"email": email, "password": password})
    _save_user_skool_accounts(data)
    _clear_account_status(email)
    _reset_user_rr(user_id)
    return True, "added"


def remove_user_skool_account(user_id, email):
    data = _load_user_skool_accounts()
    uid = str(user_id)
    if uid not in data:
        return False
    before = len(data[uid])
    data[uid] = [a for a in data[uid] if a.get("email", "").lower() != email.lower()]
    if len(data[uid]) == before:
        return False
    if not data[uid]:
        del data[uid]
    _save_user_skool_accounts(data)
    _clear_account_status(email)
    _reset_user_rr(user_id)
    return True


def clear_user_skool_accounts(user_id):
    data = _load_user_skool_accounts()
    uid = str(user_id)
    if uid in data:
        count = len(data[uid])
        del data[uid]
        _save_user_skool_accounts(data)
        _reset_user_rr(user_id)
        return count
    return 0


def _get_admin_combined_pool():
    seen = set()
    pool = []
    for acc in _load_accounts():
        email = acc.get("email", "")
        if email and email not in seen:
            seen.add(email)
            pool.append(acc)
    for acc in get_all_user_skool_accounts():
        email = acc.get("email", "")
        if email and email not in seen:
            seen.add(email)
            pool.append(acc)
    return pool

_admin_rr_index = 0
_admin_rr_lock = asyncio.Lock()

async def get_next_account_for_user(user_id, is_admin=False):
    global _user_rr_indices, _admin_rr_index

    if is_admin:
        pool = _get_admin_combined_pool()
        if not pool:
            return None, None
        async with _admin_rr_lock:
            now = time.time()
            tried = 0
            while tried < len(pool):
                idx = _admin_rr_index % len(pool)
                _admin_rr_index += 1
                account = pool[idx]
                email = account.get("email", "")
                fail_info = _failed_accounts.get(email)
                if fail_info and (now - fail_info["ts"]) < FAIL_COOLDOWN and fail_info["count"] >= 5:
                    tried += 1
                    continue
                return account, "admin_pool"
            _admin_rr_index += 1
            return pool[_admin_rr_index % len(pool)], "admin_pool"

    user_accounts = get_user_skool_accounts(user_id)
    if user_accounts:
        uid_key = str(user_id)
        if uid_key not in _user_rr_indices:
            _user_rr_indices[uid_key] = 0
        now = time.time()
        tried = 0
        while tried < len(user_accounts):
            idx = _user_rr_indices[uid_key] % len(user_accounts)
            _user_rr_indices[uid_key] += 1
            account = user_accounts[idx]
            email = account.get("email", "")
            fail_info = _failed_accounts.get(email)
            if fail_info and (now - fail_info["ts"]) < FAIL_COOLDOWN and fail_info["count"] >= 5:
                tried += 1
                continue
            return account, "user"
        idx = _user_rr_indices[uid_key] % len(user_accounts)
        _user_rr_indices[uid_key] += 1
        logger.warning(f"All accounts in cooldown for user {user_id}, using account anyway")
        return user_accounts[idx], "user"

    return None, None


async def get_fallback_account_for_user(user_id, exclude_email, is_admin=False):
    if is_admin:
        pool = _get_admin_combined_pool()
        now = time.time()
        fallback_any = None
        for account in pool:
            email = account.get("email", "")
            if email == exclude_email:
                continue
            if fallback_any is None:
                fallback_any = account
            fail_info = _failed_accounts.get(email)
            if fail_info and (now - fail_info["ts"]) < FAIL_COOLDOWN and fail_info["count"] >= 5:
                continue
            return account
        return fallback_any

    user_accounts = get_user_skool_accounts(user_id)
    if user_accounts:
        now = time.time()
        fallback_any = None
        for account in user_accounts:
            email = account.get("email", "")
            if email == exclude_email:
                continue
            if fallback_any is None:
                fallback_any = account
            fail_info = _failed_accounts.get(email)
            if fail_info and (now - fail_info["ts"]) < FAIL_COOLDOWN and fail_info["count"] >= 5:
                continue
            return account
        if fallback_any:
            logger.warning(f"All fallback accounts in cooldown for user {user_id}, using one anyway")
            return fallback_any

    return None
