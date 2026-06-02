import sys
import json
import asyncio
import os

sys.path.insert(0, os.path.dirname(__file__))

from gates.site_analyzer import analyze_site

async def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: web_site_analyzer.py <url>"}))
        return

    url = sys.argv[1]
    try:
        data = await asyncio.wait_for(analyze_site(url), timeout=30)
        print(json.dumps(data, default=str))
    except asyncio.TimeoutError:
        print(json.dumps({"error": "Analysis timeout (30s)"}))
    except Exception as e:
        print(json.dumps({"error": str(e)[:200]}))

if __name__ == "__main__":
    asyncio.run(main())
