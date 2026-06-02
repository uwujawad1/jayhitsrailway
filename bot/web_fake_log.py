import sys
import json
import os
import asyncio
import random
import string

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from gates.stripe_co import _fetch_checkout_info
import httpx
import requests
from env_config import get_setting

def generate_fake_card():
    prefixes = ["4", "5", "37", "6"]
    prefix = random.choice(prefixes)
    remaining = 16 - len(prefix) if prefix != "37" else 15 - len(prefix)
    num = prefix + "".join(random.choices(string.digits, k=remaining))
    digits = [int(d) for d in num]
    odd_sum = sum(digits[-1::-2])
    even_digits = [d * 2 for d in digits[-2::-2]]
    even_sum = sum(d - 9 if d > 9 else d for d in even_digits)
    check = (10 - (odd_sum + even_sum) % 10) % 10
    num = num[:-1] + str(check)
    mm = str(random.randint(1, 12)).zfill(2)
    yy = str(random.randint(26, 30))
    cvv = "".join(random.choices(string.digits, k=4 if prefix == "37" else 3))
    return f"{num}|{mm}|{yy}|{cvv}"


async def fetch_checkout_details(checkout_url):
    async with httpx.AsyncClient(verify=False) as client:
        info, err = await _fetch_checkout_info(client, checkout_url)
        if err or not info:
            return None, err or "Failed to fetch checkout info"
        return info, None


def send_fake_hit(user_name, user_id, card, site, amount, gateway_display="Stripe Checkout Hitter"):
    bot_token = get_setting("TELEGRAM_BOT_TOKEN")
    group_id = get_setting("TELEGRAM_GROUP_ID")
    if not bot_token or not group_id:
        return {"sent": False, "error": "No bot token or group ID"}

    def escape_md(s):
        for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
            s = s.replace(ch, '\\' + ch)
        return s

    try:
        resp = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=5)
        data = resp.json()
        bot_username = data["result"].get("username", "HitBot") if data.get("ok") else "HitBot"
    except:
        bot_username = "HitBot"

    response_msg = "Charged Successfully"
    display_name = user_name or user_id

    code_lines = [
        f"\U0001f525 HIT DETECTED \u26a1",
        f"\U0001f464 {display_name}",
        f"\u2194\ufe0f Gateway: {gateway_display}",
        f"\u2705 Response: {response_msg}",
    ]
    if site:
        code_lines.append(f"\U0001f310 Site: {site}")
    if amount:
        code_lines.append(f"\U0001f4b0 Amount: {amount}")
    code_block = "\n".join(code_lines)
    text = f"```\n{escape_md(code_block)}\n```\n[Open JayHits](https://t.me/{bot_username}/web)"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": int(group_id),
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }, timeout=10)
        result = resp.json()
        return {"sent": result.get("ok", False)}
    except Exception as e:
        return {"sent": False, "error": str(e)}


async def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: web_fake_log.py <mode> [args...]"}))
        return

    mode = sys.argv[1]

    if mode == "fetch":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Missing checkout URL"}))
            return
        checkout_url = sys.argv[2]
        info, err = await fetch_checkout_details(checkout_url)
        if err:
            print(json.dumps({"error": err}))
            return
        result = {
            "merchant": info.get("merchant", ""),
            "amount": info.get("amount", ""),
            "currency": info.get("currency", ""),
        }
        print(json.dumps(result))

    elif mode == "send":
        if len(sys.argv) < 7:
            print(json.dumps({"error": "Usage: web_fake_log.py send <user_name> <user_id> <card> <site> <amount>"}))
            return
        user_name = sys.argv[2]
        user_id = sys.argv[3]
        card = sys.argv[4]
        site = sys.argv[5]
        amount = sys.argv[6]
        result = send_fake_hit(user_name, user_id, card, site, amount)
        print(json.dumps(result))

    elif mode == "generate_card":
        card = generate_fake_card()
        print(json.dumps({"card": card}))


if __name__ == "__main__":
    asyncio.run(main())
