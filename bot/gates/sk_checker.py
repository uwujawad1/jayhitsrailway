import httpx
import asyncio
import time
import random
import string
import json
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')
logger = logging.getLogger("sk_checker")

STRIPE_API = "https://api.stripe.com/v1"

SK_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skpk.json")


def _get_sk():
    sk = os.environ.get("SK_STRIPE_KEY", "")
    if sk:
        return sk
    try:
        with open(SK_FILE) as f:
            data = json.load(f)
            return data.get("sk", data.get("key", ""))
    except (FileNotFoundError, json.JSONDecodeError):
        return ""


def _random_email():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "@gmail.com"


LIVE_DECLINE_CODES = [
    "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
    "pickup_card", "restricted_card", "security_violation",
    "incorrect_cvc", "invalid_cvc", "incorrect_zip",
    "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
    "try_again_later", "not_permitted", "generic_decline",
    "transaction_not_allowed", "card_not_supported",
]


async def sk_base_check(cc, mm, yy, cvv, proxy=None):
    sk = _get_sk()
    if not sk:
        return "Error - No SK key configured (set SK_STRIPE_KEY env or bot/skpk.json)"

    start = time.time()

    if len(yy) == 2:
        exp_year = f"20{yy}"
    else:
        exp_year = yy

    client_kwargs = {"timeout": httpx.Timeout(25), "follow_redirects": True}
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        pm_data = {
            "type": "card",
            "card[number]": cc,
            "card[exp_month]": mm.zfill(2),
            "card[exp_year]": exp_year,
            "card[cvc]": cvv,
        }

        try:
            resp1 = await client.post(
                f"{STRIPE_API}/payment_methods",
                data=pm_data,
                auth=(sk, ""),
                timeout=15,
            )
            result1 = resp1.json()
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - PM request failed: {str(e)[:50]} [{elapsed}s]"

        if "error" in result1:
            err = result1["error"]
            code = err.get("code", "")
            msg = err.get("message", "")
            elapsed = round(time.time() - start, 2)

            if code == "rate_limit":
                return f"Error - Rate Limited [{elapsed}s]"
            if code == "api_key_expired":
                return f"Error - SK Key Expired [{elapsed}s]"
            if "testmode_charges_only" in msg or code == "testmode_charges_only":
                return f"Error - Test Mode Key [{elapsed}s]"
            if code == "incorrect_number":
                return f"Declined - Incorrect Card Number [{elapsed}s]"
            if code == "invalid_expiry_year" or code == "invalid_expiry_month":
                return f"Declined - Invalid Expiry [{elapsed}s]"
            if code == "expired_card":
                return f"Declined - Card Expired [{elapsed}s]"
            if code == "card_not_supported":
                return f"Declined - Card Not Supported [{elapsed}s]"

            return f"Declined - {code}: {msg[:60]} [{elapsed}s]"

        pm_id = result1.get("id")
        if not pm_id:
            elapsed = round(time.time() - start, 2)
            return f"Error - No PM ID [{elapsed}s]"

        si_data = {
            "payment_method_types[]": "card",
            "payment_method": pm_id,
            "confirm": "true",
            "usage": "off_session",
        }

        try:
            resp2 = await client.post(
                f"{STRIPE_API}/setup_intents",
                data=si_data,
                auth=(sk, ""),
                timeout=20,
            )
            result2 = resp2.json()
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - SI request failed: {str(e)[:50]} [{elapsed}s]"

        elapsed = round(time.time() - start, 2)
        status = result2.get("status", "")

        if status == "succeeded":
            return f"Approved - Auth Passed $0 [{elapsed}s]"

        if status == "requires_action":
            return f"Approved - 3DS Required (Live) [{elapsed}s]"

        if "error" in result2:
            err = result2["error"]
            code = err.get("code", "")
            decline = err.get("decline_code", "")
            msg = err.get("message", "")

            if code == "rate_limit":
                return f"Error - Rate Limited [{elapsed}s]"

            if decline in LIVE_DECLINE_CODES or code in LIVE_DECLINE_CODES:
                return f"Approved - {decline or code} (Live Declined) [{elapsed}s]"

            if code == "card_declined" and decline == "fraudulent":
                return f"Declined - Fraudulent [{elapsed}s]"

            if code == "card_declined":
                return f"Declined - {decline or 'card_declined'} [{elapsed}s]"

            if code == "expired_card":
                return f"Declined - Card Expired [{elapsed}s]"

            if code == "setup_intent_authentication_failure":
                return f"Approved - Auth Failed (Live) [{elapsed}s]"

            if code == "authentication_required":
                return f"Approved - 3DS Required (Live) [{elapsed}s]"

            if "currency_not_supported" in msg or code == "currency_not_supported":
                return f"Declined - Currency Not Supported [{elapsed}s]"

            return f"Declined - {code}: {msg[:50]} [{elapsed}s]"

        if status:
            return f"Declined - Status: {status} [{elapsed}s]"

        return f"Declined - Unknown [{elapsed}s]"


async def sk_key_check(sk):
    start = time.time()

    async with httpx.AsyncClient(timeout=httpx.Timeout(20)) as client:
        try:
            bal_resp = await client.get(
                f"{STRIPE_API}/balance",
                auth=(sk, ""),
                timeout=15,
            )
            bal_data = bal_resp.json()
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return {
                "status": "error",
                "message": f"Request failed: {str(e)[:50]}",
                "elapsed": elapsed,
            }

        if "error" in bal_data:
            err = bal_data["error"]
            code = err.get("code", "")
            msg = err.get("message", "")
            elapsed = round(time.time() - start, 2)

            if code == "api_key_expired" or "Invalid API Key" in msg:
                return {"status": "dead", "message": "SK Key Revoked/Expired", "elapsed": elapsed}
            return {"status": "dead", "message": f"{code}: {msg[:50]}", "elapsed": elapsed}

        try:
            available = bal_data["available"][0]
            pending = bal_data["pending"][0]
            currency = available.get("currency", "unknown").upper()
            avl_amount = available.get("amount", 0)
            pnd_amount = pending.get("amount", 0)
        except (KeyError, IndexError):
            elapsed = round(time.time() - start, 2)
            return {"status": "dead", "message": "Invalid balance response", "elapsed": elapsed}

        try:
            acc_resp = await client.get(
                f"{STRIPE_API}/account",
                auth=(sk, ""),
                timeout=15,
            )
            acc_data = acc_resp.json()
        except Exception:
            acc_data = {}

        test_cc = random.choice([
            "4242424242424242|12|2029|123",
            "5555555555554444|06|2028|321",
            "4000056655665556|03|2027|456",
        ])
        parts = test_cc.split("|")

        try:
            tok_resp = await client.post(
                f"{STRIPE_API}/tokens",
                data={
                    "card[number]": parts[0],
                    "card[exp_month]": parts[1],
                    "card[exp_year]": parts[2],
                    "card[cvc]": parts[3],
                },
                auth=(sk, ""),
                timeout=15,
            )
            tok_data = tok_resp.json()
        except Exception:
            tok_data = {}

        elapsed = round(time.time() - start, 2)

        if "id" in tok_data and tok_data["id"].startswith("tok_"):
            key_status = "live"
        elif "testmode_charges_only" in json.dumps(tok_data) or "test_mode_live_card" in json.dumps(tok_data):
            key_status = "dead"
            return {"status": "dead", "message": "Test Mode Only", "elapsed": elapsed}
        elif "rate_limit" in json.dumps(tok_data):
            key_status = "live"
        elif "api_key_expired" in json.dumps(tok_data):
            return {"status": "dead", "message": "SK Key Expired", "elapsed": elapsed}
        else:
            key_status = "dead"
            return {"status": "dead", "message": "Token creation failed", "elapsed": elapsed}

        CURRENCY_INFO = {
            "USD": ("$", "US"),
            "EUR": ("E", "EU"),
            "GBP": ("P", "UK"),
            "CAD": ("$", "CA"),
            "AUD": ("A$", "AU"),
            "INR": ("R", "IN"),
            "JPY": ("Y", "JP"),
            "SGD": ("S$", "SG"),
            "NZD": ("$", "NZ"),
            "AED": ("AED", "AE"),
            "BRL": ("R$", "BR"),
            "MXN": ("$", "MX"),
            "CHF": ("CHF", "CH"),
        }

        cur_info = CURRENCY_INFO.get(currency, ("?", "??"))
        avl_fmt = avl_amount / 100 if currency != "JPY" else avl_amount
        pnd_fmt = pnd_amount / 100 if currency != "JPY" else pnd_amount

        acc_id = acc_data.get("id", "N/A")
        charges_enabled = acc_data.get("charges_enabled", False)
        card_payments = acc_data.get("capabilities", {}).get("card_payments", "N/A")
        business_url = acc_data.get("business_profile", {}).get("url", "N/A")
        business_name = acc_data.get("business_profile", {}).get("name") or acc_data.get("settings", {}).get("dashboard", {}).get("display_name", "N/A")

        return {
            "status": key_status,
            "message": "Live Key" if key_status == "live" else "Dead Key",
            "elapsed": elapsed,
            "currency": currency,
            "country": cur_info[1],
            "available": f"{cur_info[0]}{avl_fmt:.2f}",
            "pending": f"{cur_info[0]}{pnd_fmt:.2f}",
            "account_id": acc_id,
            "charges_enabled": charges_enabled,
            "card_payments": card_payments,
            "business_url": business_url,
            "business_name": business_name,
        }
