import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from gates.stripe_co import stripe_co_check, parse_checkout_url

async def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: web_stripe_co.py <checkout_url> <cc|mm|yy|cvv>"}))
        return

    checkout_url = sys.argv[1]
    card_str = sys.argv[2]

    session_ref = parse_checkout_url(checkout_url)
    if not session_ref:
        print(json.dumps({"error": "Invalid Stripe checkout URL"}))
        return

    parts = card_str.split("|")
    if len(parts) != 4:
        print(json.dumps({"error": "Invalid card format. Use cc|mm|yy|cvv"}))
        return

    cc, mm, yy, cvv = parts
    if len(yy) == 4:
        yy = yy[2:]
    mm = mm.zfill(2)

    session_cache_str = None
    if len(sys.argv) >= 4 and sys.argv[3] != "null":
        try:
            session_cache_str = json.loads(sys.argv[3])
        except:
            pass

    proxy = "NONE"
    if len(sys.argv) >= 5 and sys.argv[4] != "null":
        raw_proxy = sys.argv[4].strip()
        if raw_proxy:
            parts = raw_proxy.split(":")
            if len(parts) == 4:
                host, port, user, pwd = parts
                proxy = f"http://{user}:{pwd}@{host}:{port}"
            elif len(parts) == 2:
                proxy = f"http://{parts[0]}:{parts[1]}"
            elif raw_proxy.startswith("http"):
                proxy = raw_proxy

    try:
        status, msg, card_info, elapsed, cached = await stripe_co_check(
            cc, mm, yy, cvv, checkout_url,
            session_cache=session_cache_str,
            proxy=proxy
        )
        result = {
            "status": status,
            "message": msg,
            "card_info": card_info,
            "elapsed": elapsed,
        }
        if cached:
            safe_cache = {}
            for k in ["pk", "session_id", "merchant", "amount", "currency",
                       "success_url", "stripe_js_version", "billing_required", "customer_email"]:
                if k in cached:
                    safe_cache[k] = cached[k]
            result["session_cache"] = safe_cache
        print(json.dumps(result, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)[:200]}))

if __name__ == "__main__":
    asyncio.run(main())
