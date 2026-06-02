import sys
import json
import requests
import os
import datetime
from env_config import get_setting

def get_bot_token():
    return get_setting("TELEGRAM_BOT_TOKEN")

def get_group_id():
    return get_setting("TELEGRAM_GROUP_ID")

def send_invoice(user_id, plan, days, key):
    bot_token = get_bot_token()
    if not bot_token:
        return {"ok": False, "error": "No bot token configured"}

    plan_emoji = "\u2b50" if plan == "silver" else "\U0001f451"
    plan_name = plan.capitalize()
    days_int = int(days)
    if days_int == 7:
        price = "$5" if plan == "silver" else "$7"
    else:
        rate = 5/7 if plan == "silver" else 7/7
        price = f"${rate * days_int:.0f}" if rate * days_int == int(rate * days_int) else f"${rate * days_int:.2f}"
    now = datetime.datetime.now()
    expiry = (now + datetime.timedelta(days=int(days))).strftime("%B %d, %Y")
    activated = now.strftime("%B %d, %Y at %I:%M %p")

    text = (
        f"\U0001f9fe **Payment Invoice**\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"{plan_emoji} **Plan:** {plan_name}\n"
        f"\U0001f4b0 **Price:** {price}\n"
        f"\U0001f4c5 **Duration:** {days} day(s)\n"
        f"\U0001f4c6 **Activated:** {activated}\n"
        f"\u23f3 **Expires:** {expiry}\n"
        f"\U0001f511 **Key:** `{key}`\n\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\u2705 Your {plan_name} plan is now active!\n"
        f"Enjoy your premium features {plan_emoji}\n\n"
        f"\U0001f310 JayHits"
    )

    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": int(user_id),
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return {"ok": True}
        else:
            return {"ok": False, "error": data.get("description", "Unknown error")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def send_plan_log(user_id, user_name, plan, days):
    bot_token = get_bot_token()
    group_id = get_group_id()
    if not bot_token or not group_id:
        return {"ok": False, "error": "No bot token or group ID"}

    plan_emoji = "\u2b50" if plan == "silver" else "\U0001f451"
    plan_name = plan.capitalize()
    name = user_name or str(user_id)

    text = (
        f"{plan_emoji} **Plan Activated**\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f464 **User:** {name}\n"
        f"\U0001f194 **ID:** `{user_id}`\n"
        f"\U0001f4e6 **Plan:** {plan_name}\n"
        f"\U0001f4c5 **Duration:** {days} day(s)\n\n"
        f"User bought {days} days {plan_name} plan \u2705\n\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
    )

    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": int(group_id),
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return {"ok": True}
        else:
            return {"ok": False, "error": data.get("description", "Unknown error")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "Usage: send_invoice.py <action> <args...>"}))
        sys.exit(1)

    action = sys.argv[1]

    if action == "invoice":
        if len(sys.argv) < 6:
            print(json.dumps({"ok": False, "error": "Usage: send_invoice.py invoice <user_id> <plan> <days> <key>"}))
            sys.exit(1)
        result = send_invoice(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
        print(json.dumps(result))

    elif action == "log":
        if len(sys.argv) < 6:
            print(json.dumps({"ok": False, "error": "Usage: send_invoice.py log <user_id> <user_name> <plan> <days>"}))
            sys.exit(1)
        result = send_plan_log(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
        print(json.dumps(result))

    else:
        print(json.dumps({"ok": False, "error": f"Unknown action: {action}"}))
