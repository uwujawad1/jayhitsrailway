import asyncio
import time
import random
import string
import json
import re
import os
import logging
import aiohttp

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

from gates.skool_accounts import (
    get_next_account, get_authed_client, invalidate_session,
    get_account_lock, get_fallback_account,
    get_next_account_for_user, get_fallback_account_for_user,
)

logger = logging.getLogger("skool_autoskool")

SKOOL_API = "https://api2.skool.com"
STRIPE_API = "https://api.stripe.com/v1"

BILLING_PK = "pk_live_51Msq2SK2xk1aF7GmLfdnbGQwTp0k2kt23vSuMyDBouKfriqp9W52yocwbPK72oXs5LtVsFYqiJ0oMfXouhXZMFSu00T7SlnP47"

MAX_RETRIES = 2
RETRY_DELAY_MIN = 0.5
RETRY_DELAY_MAX = 1.5
REQUEST_TIMEOUT = 15

FOUND_GATES_FILE = os.path.join(os.path.dirname(__file__), "..", "found_gates.json")

_discovered_groups = {"groups": [], "ts": 0}
_group_index = {"idx": 0}
_tried_groups_per_account = {}

DISCOVERY_CACHE_TTL = 1800

DISCOVERY_DORKS = [
    'site:skool.com "join" "$1" "month"',
    'site:skool.com "$5" "join"',
    'site:skool.com "$7" "join"',
    'site:skool.com "$9" "join"',
    'site:skool.com "$10" "join"',
    'site:skool.com "join" "per month"',
    'site:skool.com "$29" "join"',
    'site:skool.com "$49" "join"',
    'site:skool.com "$99" "join"',
]

YAHOO_SEARCH_URL = "https://search.yahoo.com/search"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

BLOCKED_KEYWORDS = [
    "blog", "article", "review", "tutorial", "guide", "how-to", "help",
    "docs", "documentation", "support", "forum", "reddit", "youtube",
    "twitter", "facebook", "instagram", "linkedin", "tiktok",
]


def _random_guid():
    return "".join(random.choices(string.hexdigits.lower(), k=32))


def _load_found_gates():
    try:
        if os.path.exists(FOUND_GATES_FILE):
            with open(FOUND_GATES_FILE, "r") as f:
                data = json.load(f)
            paid = [g for g in data if g.get("is_paid") and g.get("slug")]
            paid.sort(key=lambda g: g.get("price") or 999)
            return paid
    except Exception:
        pass
    return []


def _save_found_gates(groups):
    try:
        existing = []
        if os.path.exists(FOUND_GATES_FILE):
            with open(FOUND_GATES_FILE, "r") as f:
                existing = json.load(f)
        existing_slugs = {g["slug"] for g in existing}
        added = 0
        for g in groups:
            if g["slug"] not in existing_slugs:
                existing.append(g)
                existing_slugs.add(g["slug"])
                added += 1
        existing.sort(key=lambda g: g.get("price") or 999)
        with open(FOUND_GATES_FILE, "w") as f:
            json.dump(existing, f, indent=2)
        if added:
            logger.info(f"Saved {added} new group(s) to found_gates.json (total: {len(existing)})")
    except Exception as e:
        logger.warning(f"Error saving found gates: {e}")


def _extract_yahoo_urls(html):
    from urllib.parse import urlparse, unquote
    urls = []
    if not HAS_BS4:
        for match in re.finditer(r'https?://[^"\'<>\s]*skool\.com/([a-zA-Z0-9_-]+)', html):
            slug = match.group(1)
            if slug and slug not in ("blog", "games", "search") and slug not in urls:
                if not any(kw in slug.lower() for kw in BLOCKED_KEYWORDS):
                    urls.append(slug)
        return urls
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        if "skool.com" in href:
            clean = href
            if "/RU=" in clean:
                match = re.search(r'/RU=([^/]+)/', clean)
                if match:
                    clean = unquote(match.group(1))
            if "skool.com" in clean and clean.startswith("http"):
                parsed = urlparse(clean)
                path = parsed.path.strip("/")
                parts = path.split("/")
                if parts and parts[0] and parts[0] not in ("blog", "games", "search"):
                    group_slug = parts[0]
                    if not any(kw in clean.lower() for kw in BLOCKED_KEYWORDS):
                        if group_slug not in urls:
                            urls.append(group_slug)
    return urls


async def _yahoo_search_slugs(session, query, max_pages=2):
    all_slugs = []
    for page in range(max_pages):
        params = {"p": query, "b": str(page * 10 + 1)}
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            async with session.get(YAHOO_SEARCH_URL, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    break
                html = await resp.text()
                if "captcha" in html.lower() or "robot" in html.lower():
                    break
                slugs = _extract_yahoo_urls(html)
                new_count = 0
                for s in slugs:
                    if s not in all_slugs:
                        all_slugs.append(s)
                        new_count += 1
                if new_count == 0:
                    break
        except Exception:
            break
        await asyncio.sleep(random.uniform(1.5, 3.0))
    return all_slugs


async def _validate_group(session, slug):
    headers = {"User-Agent": random.choice(USER_AGENTS), "Accept": "application/json"}
    info = {"slug": slug, "name": None, "group_id": None, "price": None, "is_paid": False, "status": "unknown"}
    try:
        async with session.get(f"{SKOOL_API}/groups/{slug}", headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                data = await resp.json()
                info["name"] = data.get("name", slug)
                info["group_id"] = data.get("id") or data.get("groupId")

                price_data = data.get("price") or data.get("subscription") or {}
                if isinstance(price_data, dict):
                    amount = price_data.get("amount") or price_data.get("price")
                    if amount:
                        info["price"] = amount
                        info["is_paid"] = True

                if not info["is_paid"]:
                    raw = json.dumps(data).lower()
                    price_match = re.search(r'\$(\d+(?:\.\d{2})?)\s*(?:/\s*)?(?:per\s+)?month', raw)
                    if price_match:
                        info["price"] = float(price_match.group(1))
                        info["is_paid"] = True
                    elif any(k in raw for k in ['"price"', '"amount"', '"subscription"', "per month"]):
                        info["is_paid"] = True

                info["status"] = "paid" if info["is_paid"] else "free"
            elif resp.status == 404:
                info["status"] = "not_found"
            else:
                info["status"] = f"error_{resp.status}"
    except Exception as e:
        info["status"] = f"error: {str(e)[:50]}"

    if not info["is_paid"] and info["status"] not in ("not_found",):
        try:
            async with session.get(f"{SKOOL_API}/groups/{slug}/about", headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    raw = json.dumps(data).lower()
                    if any(k in raw for k in ['"price"', '"amount"', "per month", "subscription"]):
                        info["is_paid"] = True
                        info["status"] = "paid"
                        price_match = re.search(r'\$(\d+(?:\.\d{2})?)', raw)
                        if price_match:
                            info["price"] = float(price_match.group(1))
                    if not info["group_id"]:
                        gid = data.get("id") or data.get("groupId")
                        if isinstance(data.get("group"), dict):
                            gid = gid or data["group"].get("id")
                        info["group_id"] = gid
        except Exception:
            pass

    return info


async def _auto_discover_groups():
    logger.info("Auto-discovering paid Skool groups...")
    found = []
    checked = set()

    async with aiohttp.ClientSession() as session:
        dorks_to_use = random.sample(DISCOVERY_DORKS, min(2, len(DISCOVERY_DORKS)))

        for dork in dorks_to_use:
            slugs = await _yahoo_search_slugs(session, dork, max_pages=2)

            for slug in slugs:
                if slug in checked:
                    continue
                checked.add(slug)

                info = await _validate_group(session, slug)
                await asyncio.sleep(random.uniform(0.5, 1.0))

                if info["is_paid"] and info["slug"]:
                    found.append(info)
                    logger.info(f"Discovered paid group: {slug} (${info.get('price', '?')})")

                if len(found) >= 20:
                    break
            if len(found) >= 20:
                break

    return found


def _get_saved_groups():
    groups = _load_found_gates()
    groups.sort(key=lambda g: g.get("price") or 999)
    return groups


async def _discover_new_groups(exclude_slugs=None):
    exclude_slugs = exclude_slugs or set()
    try:
        discovered = await _auto_discover_groups()
        new_groups = [
            g for g in discovered
            if g.get("is_paid") and g.get("slug") and g["slug"] not in exclude_slugs
        ]
        new_groups.sort(key=lambda g: g.get("price") or 999)
        if new_groups:
            _save_found_gates(new_groups)
            logger.info(f"Discovered {len(new_groups)} new group(s)")
        return new_groups
    except Exception as e:
        logger.warning(f"Auto-discovery failed: {e}")
        return []


def _get_untried_group(groups, account_email):
    tried = _tried_groups_per_account.get(account_email, set())
    for g in groups:
        if g["slug"] not in tried:
            return g
    return None


def _mark_group_tried(account_email, group_slug):
    if account_email not in _tried_groups_per_account:
        _tried_groups_per_account[account_email] = set()
    _tried_groups_per_account[account_email].add(group_slug)


async def _resolve_group_id(client, group_slug):
    try:
        r = await client.get(f"{SKOOL_API}/groups/{group_slug}", timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            gid = data.get("id") or data.get("groupId") or data.get("group_id")
            if gid:
                return gid
    except Exception:
        pass

    try:
        r = await client.get(f"{SKOOL_API}/groups/{group_slug}/about", timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            gid = data.get("id") or data.get("groupId") or data.get("group_id")
            if not gid and isinstance(data.get("group"), dict):
                gid = data["group"].get("id")
            if gid:
                return gid
    except Exception:
        pass

    return None


async def _leave_group(client, group_slug, gid=None):
    if gid:
        try:
            await client.post(f"{SKOOL_API}/groups/{gid}/cancel-join-group-paid", timeout=15)
        except Exception:
            pass
    try:
        await client.post(f"{SKOOL_API}/groups/{group_slug}/cancel-join", timeout=15)
    except Exception:
        pass
    try:
        await client.post(f"{SKOOL_API}/groups/{group_slug}/leave", timeout=15)
    except Exception:
        pass


async def autoskool_check(cc, mm, yy, cvv, proxy=None, user_id=None, is_admin=False):
    if user_id:
        account, source = await get_next_account_for_user(user_id, is_admin=is_admin)
    else:
        account = await get_next_account()

    if not account:
        return "NO_SKOOL_ACCOUNT"

    account_email = account["email"]

    if "Skool Account Login Error" in account.get("_last_error", ""):
        if user_id:
            fallback = await get_fallback_account_for_user(user_id, account["email"], is_admin=is_admin)
        else:
            fallback = await get_fallback_account(account["email"])
        if fallback:
            account = fallback
            account_email = account["email"]

    saved_groups = _get_saved_groups()

    while True:
        group = _get_untried_group(saved_groups, account_email)
        if not group:
            break

        group_slug = group["slug"]
        group_price = group.get("price")
        price_str = f"${group_price}" if group_price else "paid"

        lock = get_account_lock(account)
        async with lock:
            result = await _check_with_account(cc, mm, yy, cvv, account, group_slug, price_str, user_proxy=proxy)

        if "Skool Account Login Error" in result:
            if user_id:
                fallback = await get_fallback_account_for_user(user_id, account["email"], is_admin=is_admin)
            else:
                fallback = await get_fallback_account(account["email"])
            if fallback:
                account = fallback
                account_email = account["email"]
                continue
            return result

        if "already member" in result.lower():
            _mark_group_tried(account_email, group_slug)
            logger.info(f"Already member of {group_slug}, trying next saved group...")
            continue

        return result

    logger.info(f"All {len(saved_groups)} saved groups tried for {account_email}, discovering new groups...")
    all_known_slugs = {g["slug"] for g in saved_groups}
    tried = _tried_groups_per_account.get(account_email, set())
    all_known_slugs.update(tried)

    new_groups = await _discover_new_groups(exclude_slugs=all_known_slugs)

    if not new_groups:
        return "Error - No untried groups available. All saved groups exhausted and discovery found nothing new."

    random.shuffle(new_groups)

    for g in new_groups:
        group_slug = g["slug"]
        group_price = g.get("price")
        price_str = f"${group_price}" if group_price else "paid"

        lock = get_account_lock(account)
        async with lock:
            result = await _check_with_account(cc, mm, yy, cvv, account, group_slug, price_str, user_proxy=proxy)

        if "already member" in result.lower():
            _mark_group_tried(account_email, group_slug)
            logger.info(f"Already member of discovered {group_slug}, trying next...")
            continue

        return result

    return "Error - All discovered groups also returned 'already member'."


async def _check_with_account(cc, mm, yy, cvv, account, group_slug, price_str, user_proxy=None):
    start = time.time()

    if len(yy) == 2:
        exp_year = f"20{yy}"
    else:
        exp_year = yy
    mm = mm.zfill(2)

    stripe_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://js.stripe.com",
        "Referer": "https://js.stripe.com/",
        "Accept": "application/json",
    }

    for attempt in range(MAX_RETRIES):
        client = None
        joined_group = False
        gid = None
        try:
            force_refresh = attempt > 0
            client = await get_authed_client(account, force_refresh=force_refresh, user_proxy=user_proxy)
            if not client:
                if attempt < MAX_RETRIES - 1:
                    invalidate_session(account)
                    await asyncio.sleep(random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                    continue
                elapsed = round(time.time() - start, 2)
                return f"Error - Skool Account Login Error [{elapsed}s]"

            gid = await _resolve_group_id(client, group_slug)
            if not gid:
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                    continue
                elapsed = round(time.time() - start, 2)
                return f"Error - Could not resolve group '{group_slug}' [{elapsed}s]"

            await _leave_group(client, group_slug, gid)

            r_si = await client.post(
                f"{SKOOL_API}/self/setup-payment-method", json={}, timeout=REQUEST_TIMEOUT
            )
            if r_si.status_code != 200:
                if r_si.status_code in (401, 403) and attempt < MAX_RETRIES - 1:
                    invalidate_session(account)
                    await asyncio.sleep(random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                    continue
                elapsed = round(time.time() - start, 2)
                return f"Error - SetupIntent failed ({r_si.status_code}) [{elapsed}s]"

            si_data = r_si.json()
            client_secret = si_data.get("client_secret")
            setup_intent_id = si_data.get("setup_intent_id")

            if not client_secret or not setup_intent_id:
                if attempt < MAX_RETRIES - 1:
                    invalidate_session(account)
                    await asyncio.sleep(random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                    continue
                elapsed = round(time.time() - start, 2)
                return f"Error - Invalid SetupIntent [{elapsed}s]"

            pm_data = {
                "type": "card",
                "card[number]": cc,
                "card[exp_month]": mm,
                "card[exp_year]": exp_year,
                "card[cvc]": cvv,
                "billing_details[name]": "John Smith",
                "billing_details[address][country]": "US",
                "billing_details[address][postal_code]": str(random.randint(10001, 99999)),
                "guid": _random_guid(),
                "muid": _random_guid(),
                "sid": _random_guid(),
                "payment_user_agent": "stripe.js/a24a2bc0a2; stripe-js-v3/a24a2bc0a2",
                "referrer": "https://www.skool.com",
                "time_on_page": str(random.randint(30000, 120000)),
                "key": BILLING_PK,
            }

            r_pm = await client.post(
                f"{STRIPE_API}/payment_methods", data=pm_data, headers=stripe_headers, timeout=REQUEST_TIMEOUT
            )
            pm_resp = r_pm.json()

            if "error" in pm_resp:
                elapsed = round(time.time() - start, 2)
                err = pm_resp["error"]
                code = err.get("code", "unknown")
                msg = err.get("message", "Unknown error")
                if code == "incorrect_number":
                    return f"Declined - Invalid Card Number [{elapsed}s]"
                if "expiry" in msg.lower():
                    return f"Declined - Invalid Expiry [{elapsed}s]"
                if code == "expired_card":
                    return f"Declined - Expired Card [{elapsed}s]"
                return f"Declined - {code}: {msg[:80]} [{elapsed}s]"

            pm_id = pm_resp.get("id")
            if not pm_id:
                elapsed = round(time.time() - start, 2)
                return f"Declined - PM creation failed [{elapsed}s]"

            card = pm_resp.get("card", {})
            brand = card.get("brand", "unknown").upper()
            last4 = card.get("last4", "????")
            funding = card.get("funding", "unknown").upper()
            country = card.get("country", "??")
            info = f"{brand} {funding} | {country} | {last4}"

            r_confirm = await client.post(
                f"{STRIPE_API}/setup_intents/{setup_intent_id}/confirm",
                data={"payment_method": pm_id, "client_secret": client_secret, "key": BILLING_PK},
                headers=stripe_headers,
                timeout=REQUEST_TIMEOUT,
            )
            confirm_resp = r_confirm.json()
            setup_status = confirm_resp.get("status", "")

            if setup_status == "requires_payment_method":
                elapsed = round(time.time() - start, 2)
                last_error = confirm_resp.get("last_setup_error", {})
                if last_error:
                    code = last_error.get("code", "")
                    decline = last_error.get("decline_code", "")
                    msg = last_error.get("message", "")
                    live_declines = [
                        "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
                        "pickup_card", "restricted_card", "security_violation",
                        "incorrect_cvc", "invalid_cvc", "incorrect_zip",
                        "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
                    ]
                    if decline in live_declines or code in live_declines:
                        return f"Approved - {decline or code} {price_str} [{elapsed}s]"
                    if code == "card_declined":
                        return f"Declined - {decline or 'Card Declined'} {price_str} [{elapsed}s]"
                    if code == "expired_card":
                        return f"Declined - Expired Card {price_str} [{elapsed}s]"
                    return f"Declined - {code}: {msg[:60]} {price_str} [{elapsed}s]"
                return f"Declined - Setup Failed {price_str} [{elapsed}s]"

            try:
                await client.post(
                    f"{SKOOL_API}/self/add-payment-method",
                    json={"pt": pm_id, "sid": setup_intent_id},
                    timeout=REQUEST_TIMEOUT,
                )
            except Exception:
                pass

            await client.post(
                f"{SKOOL_API}/groups/{gid}/init-join-group-paid", json={}, timeout=REQUEST_TIMEOUT
            )

            r_join = await client.post(
                f"{SKOOL_API}/groups/{group_slug}/join-group-paid",
                params={"pm": pm_id, "recurring_interval": "month", "tier": "standard"},
                timeout=REQUEST_TIMEOUT,
            )
            joined_group = True
            elapsed = round(time.time() - start, 2)

            if r_join.status_code == 200:
                join_data = r_join.json()
                cs = join_data.get("clientSecret") or join_data.get("client_secret")
                if cs:
                    pi_id = cs.split("_secret_")[0]
                    r_pi = await client.post(
                        f"{STRIPE_API}/payment_intents/{pi_id}/confirm",
                        data={"payment_method": pm_id, "client_secret": cs, "key": BILLING_PK},
                        headers=stripe_headers,
                        timeout=REQUEST_TIMEOUT,
                    )
                    pi_resp = r_pi.json()
                    pi_status = pi_resp.get("status", "")
                    await _leave_group(client, group_slug, gid)
                    if pi_status == "succeeded":
                        return f"Approved - Charged {price_str} [{elapsed}s]"
                    elif pi_status == "requires_action":
                        return f"Approved - 3DS Required {price_str} [{elapsed}s]"
                    elif pi_status == "requires_payment_method":
                        pi_err = pi_resp.get("last_payment_error", {})
                        decline = pi_err.get("decline_code", "")
                        code = pi_err.get("code", "")
                        live_declines = ["insufficient_funds", "do_not_honor", "lost_card", "stolen_card", "pickup_card", "restricted_card", "incorrect_cvc", "card_velocity_exceeded"]
                        if decline in live_declines or code in live_declines:
                            return f"Approved - {decline or code} {price_str} [{elapsed}s]"
                        return f"Declined - {decline or code or 'charge_failed'} {price_str} [{elapsed}s]"
                    else:
                        return f"Declined - PI Status: {pi_status} {price_str} [{elapsed}s]"
                await _leave_group(client, group_slug, gid)
                return f"Approved - Charged {price_str} [{elapsed}s]"

            elif r_join.status_code == 422:
                await _leave_group(client, group_slug, gid)
                join_data = r_join.json()
                fields = join_data.get("fields", [])
                if fields:
                    err_name = fields[0].get("name", "")
                    err_msg = fields[0].get("error", "")
                    live_declines = ["insufficient_funds", "do_not_honor", "lost_card", "stolen_card", "pickup_card", "restricted_card", "incorrect_cvc", "invalid_cvc", "incorrect_zip", "card_velocity_exceeded", "withdrawal_count_limit_exceeded"]
                    if err_msg in live_declines:
                        return f"Approved - {err_msg} {price_str} [{elapsed}s]"
                    if "declined" in err_name.lower():
                        return f"Declined - {err_msg or 'Card Declined'} {price_str} [{elapsed}s]"
                    if err_msg == "expired_card":
                        return f"Declined - Expired Card {price_str} [{elapsed}s]"
                    return f"Declined - {err_msg or err_name} {price_str} [{elapsed}s]"
                return f"Declined - Charge Failed (422) {price_str} [{elapsed}s]"

            elif r_join.status_code == 400:
                body = r_join.text
                if "already" in body.lower() or "member" in body.lower():
                    await _leave_group(client, group_slug, gid)
                    if attempt < MAX_RETRIES - 1:
                        invalidate_session(account)
                        await asyncio.sleep(random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                        continue
                    return f"Error - Account already member of {group_slug} [{elapsed}s]"
                await _leave_group(client, group_slug, gid)
                return f"Declined - {body[:80]} {price_str} [{elapsed}s]"

            elif r_join.status_code in (401, 403):
                await _leave_group(client, group_slug, gid)
                if attempt < MAX_RETRIES - 1:
                    invalidate_session(account)
                    await asyncio.sleep(random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                    continue
                return f"Error - Join failed ({r_join.status_code}) {price_str} [{elapsed}s]"

            else:
                await _leave_group(client, group_slug, gid)
                return f"Error - Join failed ({r_join.status_code}) {price_str} [{elapsed}s]"

        except (TimeoutError, ConnectionError, OSError) as e:
            if client and joined_group:
                await _leave_group(client, group_slug, gid)
            err_str = str(e)
            is_proxy_err = any(s in err_str for s in ["407", "CONNECT tunnel", "proxy", "Proxy"])
            if is_proxy_err:
                logger.warning(f"Proxy error on attempt {attempt+1}: {err_str[:100]}")
                from gates.skool_accounts import _mark_proxies_dead
                _mark_proxies_dead()
                invalidate_session(account)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(0.5)
                    continue
            else:
                logger.warning(f"Timeout/connection error on attempt {attempt+1}: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                    continue
            elapsed = round(time.time() - start, 2)
            return f"Error - Gateway Timeout [{elapsed}s]"
        except Exception as e:
            if client and joined_group:
                await _leave_group(client, group_slug, gid)
            err_str = str(e)
            is_proxy_err = any(s in err_str for s in ["407", "CONNECT tunnel", "proxy", "Proxy"])
            if is_proxy_err:
                logger.warning(f"Proxy error on attempt {attempt+1}: {err_str[:100]}")
                from gates.skool_accounts import _mark_proxies_dead
                _mark_proxies_dead()
                invalidate_session(account)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(0.5)
                    continue
            else:
                logger.warning(f"Unexpected error on attempt {attempt+1}: {e}")
                if attempt < MAX_RETRIES - 1:
                    invalidate_session(account)
                    await asyncio.sleep(random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                    continue
            elapsed = round(time.time() - start, 2)
            return f"Error - {str(e)[:80]} [{elapsed}s]"

    elapsed = round(time.time() - start, 2)
    return f"Error - Max retries exceeded [{elapsed}s]"
