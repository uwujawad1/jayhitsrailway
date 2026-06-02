import sys
import os
import json
import asyncio
import re
import aiohttp
from env_config import get_setting

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

CC_PATTERN = re.compile(r'\d{15,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}')
SK_PATTERN = re.compile(r'sk_(?:live|test)_[a-zA-Z0-9]{20,}')

async def scrape_via_bot_api(scrape_type, chat_id, limit, bot_token):
    pattern = CC_PATTERN if scrape_type == "cc" else SK_PATTERN
    results = set()
    total_messages = 0
    base_url = f"https://api.telegram.org/bot{bot_token}"

    try:
        chat_id_val = int(chat_id)
    except ValueError:
        chat_id_val = chat_id

    async with aiohttp.ClientSession() as session:
        offset = 0
        remaining = limit
        batch_size = 100

        while remaining > 0:
            fetch_count = min(batch_size, remaining)

            if offset == 0:
                url = f"{base_url}/getUpdates"
                params = {"chat_id": chat_id_val, "limit": fetch_count, "allowed_updates": ["message"]}
            else:
                break

            try:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    data = await resp.json()
            except Exception as e:
                return {"error": f"Bot API request failed: {str(e)[:200]}"}

            if not data.get("ok"):
                break

            updates = data.get("result", [])
            if not updates:
                break

            for update in updates:
                msg = update.get("message") or update.get("channel_post")
                if not msg:
                    continue
                msg_chat_id = msg.get("chat", {}).get("id")
                if str(msg_chat_id) != str(chat_id_val):
                    continue
                total_messages += 1
                text = msg.get("text", "")
                if text:
                    matches = pattern.findall(text)
                    for match in matches:
                        results.add(match)

            remaining -= len(updates)
            break

    unique_results = list(results)
    return {
        "results": unique_results,
        "total": total_messages,
        "unique": len(unique_results)
    }


async def scrape_via_telethon_user(scrape_type, chat_id, limit, api_id, api_hash):
    from telethon import TelegramClient

    session_path = os.path.join(os.path.dirname(__file__), "scraper_user")

    if not os.path.exists(session_path + ".session"):
        return {"error": "User session not set up. Admin must run the session setup first."}

    client = TelegramClient(session_path, api_id, api_hash)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"error": "User session expired. Admin must re-authenticate."}

        pattern = CC_PATTERN if scrape_type == "cc" else SK_PATTERN

        try:
            chat_entity = int(chat_id)
        except ValueError:
            chat_entity = chat_id

        results = set()
        total_messages = 0

        async for message in client.iter_messages(chat_entity, limit=limit):
            total_messages += 1
            if message.text:
                matches = pattern.findall(message.text)
                for match in matches:
                    results.add(match)

        unique_results = list(results)
        return {
            "results": unique_results,
            "total": total_messages,
            "unique": len(unique_results)
        }

    except Exception as e:
        error_msg = str(e)
        if "GetHistoryRequest" in error_msg or "restricted" in error_msg.lower():
            return {"error": "Cannot read message history. User session required for this operation."}
        return {"error": error_msg[:500]}
    finally:
        await client.disconnect()


async def scrape_via_telethon_bot(scrape_type, chat_id, limit, api_id, api_hash, bot_token):
    from telethon import TelegramClient
    from telethon.tl.functions.messages import SearchRequest
    from telethon.tl.types import InputMessagesFilterEmpty
    import tempfile

    session_path = os.path.join(tempfile.gettempdir(), f"scraper_{os.getpid()}")
    client = TelegramClient(session_path, api_id, api_hash)

    try:
        await client.start(bot_token=bot_token)

        pattern = CC_PATTERN if scrape_type == "cc" else SK_PATTERN

        try:
            chat_entity = int(chat_id)
        except ValueError:
            chat_entity = chat_id

        results = set()
        total_messages = 0

        async for message in client.iter_messages(chat_entity, limit=limit):
            total_messages += 1
            if message.text:
                matches = pattern.findall(message.text)
                for match in matches:
                    results.add(match)

        unique_results = list(results)
        return {
            "results": unique_results,
            "total": total_messages,
            "unique": len(unique_results)
        }

    except Exception as e:
        error_msg = str(e)
        if "GetHistoryRequest" in error_msg or "restricted" in error_msg.lower():
            return None
        return {"error": error_msg[:500]}
    finally:
        await client.disconnect()
        for ext in ("", ".session", ".session-journal"):
            try:
                p = session_path + ext
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


async def scrape_messages(scrape_type, chat_id, limit):
    api_id = int(get_setting("TELEGRAM_API_ID", "0"))
    api_hash = get_setting("TELEGRAM_API_HASH")
    bot_token = get_setting("TELEGRAM_BOT_TOKEN")

    if not api_id or not api_hash or not bot_token:
        return {"error": "Missing Telegram API credentials in environment"}

    user_session = os.path.join(os.path.dirname(__file__), "scraper_user.session")
    if os.path.exists(user_session):
        result = await scrape_via_telethon_user(scrape_type, chat_id, limit, api_id, api_hash)
        if not result.get("error") or "session" not in result.get("error", "").lower():
            return result

    bot_result = await scrape_via_telethon_bot(scrape_type, chat_id, limit, api_id, api_hash, bot_token)
    if bot_result is not None:
        return bot_result

    return {"error": "Bot cannot read message history (GetHistoryRequest restricted). A user session is needed.\n\nTo set up: run 'python3 bot/setup_scraper_session.py' and follow the prompts to authenticate with a Telegram user account."}


async def main():
    if len(sys.argv) < 4:
        print(json.dumps({"error": "Usage: web_scraper.py <type:cc|sk> <chat_id> <limit>"}))
        return

    scrape_type = sys.argv[1].lower()
    chat_id = sys.argv[2]
    try:
        limit = int(sys.argv[3])
    except ValueError:
        limit = 100

    if scrape_type not in ("cc", "sk"):
        print(json.dumps({"error": "Type must be 'cc' or 'sk'"}))
        return

    limit = max(1, limit)

    result = await scrape_messages(scrape_type, chat_id, limit)
    print(json.dumps(result))

if __name__ == "__main__":
    asyncio.run(main())
