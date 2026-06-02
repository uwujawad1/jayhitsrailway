import asyncio
import time
import random
import string
import json
import re
import os
import logging
from gates.skool_accounts import (
    get_next_account, get_authed_client, invalidate_session,
    get_account_lock, get_fallback_account, get_last_login_error,
    get_next_account_for_user, get_fallback_account_for_user,
)

logger = logging.getLogger("skool_api")

SKOOL_API = "https://api2.skool.com"
STRIPE_API = "https://api.stripe.com/v1"

STRIPE_PK = "pk_live_51IMiS6KvLOXsN9xSfc0bsCmz4p06QORdboo8MvJtjVBv2pnTKbysGEMu331uhK1cw2RRGMiLgAGCPfjDVJs30aLn00ui4Q8VEn"
BILLING_PK = "pk_live_51Msq2SK2xk1aF7GmLfdnbGQwTp0k2kt23vSuMyDBouKfriqp9W52yocwbPK72oXs5LtVsFYqiJ0oMfXouhXZMFSu00T7SlnP47"

MAX_RETRIES = 3
RETRY_DELAY_MIN = 0.5
RETRY_DELAY_MAX = 1.5
REQUEST_TIMEOUT = 15


def _random_guid():
    return "".join(random.choices(string.hexdigits.lower(), k=32))


async def skool_api_check(cc, mm, yy, cvv, proxy=None, user_id=None, is_admin=False):
    if user_id:
        account, source = await get_next_account_for_user(user_id, is_admin=is_admin)
    else:
        account = await get_next_account()

    if not account:
        return "NO_SKOOL_ACCOUNT"

    lock = get_account_lock(account)
    async with lock:
        result = await _check_with_account(cc, mm, yy, cvv, account, user_proxy=proxy)

    if "Skool Account Login Error" in result:
        if user_id:
            fallback = await get_fallback_account_for_user(user_id, account["email"], is_admin=is_admin)
        else:
            fallback = await get_fallback_account(account["email"])
        if fallback:
            lock2 = get_account_lock(fallback)
            async with lock2:
                result = await _check_with_account(cc, mm, yy, cvv, fallback, user_proxy=proxy)

    return result


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
        try:
            force_refresh = attempt > 0
            client = await get_authed_client(account, force_refresh=force_refresh, user_proxy=user_proxy)
            if not client:
                if attempt < MAX_RETRIES - 1:
                    invalidate_session(account)
                    await asyncio.sleep(random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                    continue
                elapsed = round(time.time() - start, 2)
                last_err = get_last_login_error(account)
                reason = f" ({last_err})" if last_err else ""
                return f"Error - Skool Account Login Error{reason} [{elapsed}s]"

            r_si = await client.post(
                f"{SKOOL_API}/self/setup-payment-method", json={}, timeout=REQUEST_TIMEOUT
            )
            if r_si.status_code != 200:
                if r_si.status_code in (401, 403) and attempt < MAX_RETRIES - 1:
                    invalidate_session(account)
                    await asyncio.sleep(random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                    continue
                elapsed = round(time.time() - start, 2)
                return f"Error - SetupIntent creation failed ({r_si.status_code}) [{elapsed}s]"

            si_data = r_si.json()
            client_secret = si_data.get("client_secret")
            setup_intent_id = si_data.get("setup_intent_id")

            if not client_secret or not setup_intent_id:
                if attempt < MAX_RETRIES - 1:
                    invalidate_session(account)
                    await asyncio.sleep(random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX))
                    continue
                elapsed = round(time.time() - start, 2)
                return f"Error - Invalid SetupIntent response [{elapsed}s]"

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
                f"{STRIPE_API}/payment_methods",
                data=pm_data,
                headers=stripe_headers,
                timeout=REQUEST_TIMEOUT,
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

            confirm_data = {
                "payment_method": pm_id,
                "client_secret": client_secret,
                "key": BILLING_PK,
            }

            r_confirm = await client.post(
                f"{STRIPE_API}/setup_intents/{setup_intent_id}/confirm",
                data=confirm_data,
                headers=stripe_headers,
                timeout=REQUEST_TIMEOUT,
            )
            confirm_resp = r_confirm.json()
            elapsed = round(time.time() - start, 2)

            status = confirm_resp.get("status", "")

            if status == "succeeded":
                try:
                    await client.post(
                        f"{SKOOL_API}/self/add-payment-method",
                        json={"pt": pm_id, "sid": setup_intent_id},
                        timeout=REQUEST_TIMEOUT,
                    )
                except Exception:
                    pass
                return f"Approved - Charged | {info} [{elapsed}s]"

            if status == "requires_action":
                next_action = confirm_resp.get("next_action", {})
                action_type = next_action.get("type", "")
                if action_type == "use_stripe_sdk":
                    return f"Approved - 3DS Required | {info} [{elapsed}s]"
                return f"Approved - Action Required ({action_type}) | {info} [{elapsed}s]"

            if status == "requires_payment_method":
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
                        if decline:
                            return f"Declined - {decline} | {info} [{elapsed}s]"
                        return f"Declined - Card Declined | {info} [{elapsed}s]"
                    if code == "expired_card":
                        return f"Declined - Expired Card | {info} [{elapsed}s]"
                    if code == "processing_error":
                        return f"Declined - Processing Error | {info} [{elapsed}s]"
                    return f"Declined - {code}: {msg[:60]} | {info} [{elapsed}s]"
                return f"Declined - Setup Failed | {info} [{elapsed}s]"

            return f"Declined - Status: {status} | {info} [{elapsed}s]"

        except (TimeoutError, ConnectionError, OSError) as e:
            err_str = str(e)
            is_proxy_err = any(s in err_str for s in ["407", "CONNECT tunnel", "proxy", "Proxy"])
            if is_proxy_err:
                logger.warning(f"Proxy error on attempt {attempt+1}: {err_str[:100]}, will retry without proxy")
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
