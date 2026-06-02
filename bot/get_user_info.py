import sys
import json
import os
import requests
from env_config import get_setting

def get_bot_token():
    return get_setting("TELEGRAM_BOT_TOKEN")

def download_profile_photo(token, user_id):
    """
    Fetch the user's Telegram profile photo and save it locally to
    bot/avatars/<user_id>.jpg.  Returns True on success, False otherwise.
    The raw Telegram URL (containing the bot token) is never exposed outside
    this script.
    """
    avatars_dir = os.path.join(os.path.dirname(__file__), "avatars")
    os.makedirs(avatars_dir, exist_ok=True)
    save_path = os.path.join(avatars_dir, f"{user_id}.jpg")

    try:
        # Step 1 — get file_id of the best (largest) available photo
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUserProfilePhotos",
            params={"user_id": user_id, "limit": 1},
            timeout=10,
        )
        data = r.json()
        if not data.get("ok") or data["result"].get("total_count", 0) == 0:
            return False

        photos = data["result"]["photos"]
        if not photos:
            return False
        best = photos[0][-1]   # last entry = highest resolution
        file_id = best["file_id"]

        # Step 2 — resolve file_id → temporary server-side file path
        fr = requests.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id},
            timeout=10,
        )
        fdata = fr.json()
        if not fdata.get("ok"):
            return False
        file_path = fdata["result"]["file_path"]

        # Step 3 — download the raw bytes (token stays server-side, never returned)
        img_r = requests.get(
            f"https://api.telegram.org/file/bot{token}/{file_path}",
            timeout=15,
            stream=True,
        )
        if img_r.status_code != 200:
            return False

        with open(save_path, "wb") as f:
            for chunk in img_r.iter_content(chunk_size=8192):
                f.write(chunk)
        return True

    except Exception:
        return False

def get_user_info(user_id):
    token = get_bot_token()
    if not token:
        return {"user_id": user_id, "first_name": "", "last_name": "", "username": "", "photo_saved": False}

    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": user_id},
            timeout=10,
        )
        data = r.json()
        if data.get("ok"):
            result = data["result"]
            photo_saved = download_profile_photo(token, user_id)
            return {
                "user_id": user_id,
                "first_name": result.get("first_name", ""),
                "last_name": result.get("last_name", ""),
                "username": result.get("username", ""),
                "photo_saved": photo_saved,
            }
    except Exception:
        pass

    return {"user_id": user_id, "first_name": "", "last_name": "", "username": "", "photo_saved": False}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: get_user_info.py <user_id>"}))
        sys.exit(1)
    info = get_user_info(sys.argv[1])
    print(json.dumps(info))
