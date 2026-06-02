import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from gates.sk_checker import sk_key_check

async def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: web_sk_checker.py <sk_key>"}))
        return

    sk = sys.argv[1].strip()
    if not sk.startswith(("sk_live_", "sk_test_", "rk_live_", "rk_test_")):
        print(json.dumps({"error": "Invalid SK format"}))
        return

    try:
        result = await sk_key_check(sk)
        result["sk"] = sk
        print(json.dumps(result, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)[:200]}))

if __name__ == "__main__":
    asyncio.run(main())
