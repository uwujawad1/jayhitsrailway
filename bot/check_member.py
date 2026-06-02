import sys
import json
import requests
import os
from env_config import get_setting

def check_chat_member(bot_token, chat_id, user_id):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
        try:
            parsed_chat_id = int(chat_id)
        except (ValueError, TypeError):
            parsed_chat_id = chat_id
        resp = requests.post(url, json={
            "chat_id": parsed_chat_id,
            "user_id": int(user_id)
        }, timeout=10)
        data = resp.json()
        if data.get("ok"):
            status = data["result"].get("status", "")
            if status in ("member", "administrator", "creator", "restricted"):
                return True
            if status in ("left", "kicked"):
                return False
            return True
        err_desc = data.get("description", "").lower()
        if "user not found" in err_desc or "user_not_participant" in err_desc:
            return False
        if "participant_id_invalid" in err_desc:
            return False
        if "chat not found" in err_desc or "chat_not_found" in err_desc:
            return True
        return True
    except:
        return True

def check_member(user_id):
    bot_token = get_setting("TELEGRAM_BOT_TOKEN")
    group_id = get_setting("TELEGRAM_GROUP_ID")
    channel_id = get_setting("TELEGRAM_CHANNEL_ID")

    if not bot_token or not group_id:
        return {"ok": False, "member": False, "error": "No bot token or group ID"}

    in_group = check_chat_member(bot_token, group_id, user_id)

    in_channel = True
    if channel_id:
        in_channel = check_chat_member(bot_token, channel_id, user_id)

    is_member = in_group and in_channel

    if not in_group and not in_channel:
        status = "not_in_group_or_channel"
    elif not in_group:
        status = "not_in_group"
    elif not in_channel:
        status = "not_in_channel"
    else:
        status = "member"

    return {"ok": True, "member": is_member, "status": status}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "member": False, "error": "Usage: check_member.py <user_id>"}))
        sys.exit(1)
    result = check_member(sys.argv[1])
    print(json.dumps(result))
