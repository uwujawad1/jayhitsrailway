import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from gates.site_finder import find_sites, SUPPORTED_GATEWAYS

async def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: web_findsite.py <gateway> [count]"}))
        return

    gateway = sys.argv[1].lower()
    count = 10
    if len(sys.argv) >= 3:
        try:
            count = min(max(int(sys.argv[2]), 1), 25)
        except ValueError:
            pass

    if gateway not in [g.lower() for g in SUPPORTED_GATEWAYS]:
        print(json.dumps({"error": f"Unknown gateway: {gateway}", "supported": SUPPORTED_GATEWAYS}))
        return

    async def progress(text):
        print(json.dumps({"progress": text}), flush=True)

    try:
        data = await find_sites(gateway, max_results=count, progress_callback=progress)
        print(json.dumps(data, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))

if __name__ == "__main__":
    asyncio.run(main())
