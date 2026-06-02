"""
proxy_scraper.py — Fetch and test free proxies from public lists.

Usage (called via subprocess):
    python3 proxy_scraper.py scrape [max_results]
    → prints JSON: {"proxies": [...], "tested": N, "working": N}
"""

import asyncio
import json
import sys
import time
import random
import re

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

import urllib.request
import urllib.error

FREE_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://www.proxyscrape.com/api?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
]

TEST_URLS = [
    "http://httpbin.org/ip",
    "http://ip-api.com/json",
]

PROXY_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}$")
MAX_WORKING = 20
TEST_TIMEOUT = 6
MAX_CONCURRENT = 40


def fetch_source(url: str) -> list[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read().decode("utf-8", errors="ignore")
        proxies = []
        for line in text.splitlines():
            line = line.strip()
            if PROXY_RE.match(line):
                proxies.append(line)
        return proxies
    except Exception:
        return []


def gather_all_proxies() -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for src in FREE_SOURCES:
        for p in fetch_source(src):
            if p not in seen:
                seen.add(p)
                result.append(p)
    random.shuffle(result)
    return result


async def test_proxy_httpx(proxy_str: str, semaphore: asyncio.Semaphore) -> dict | None:
    url = f"http://{proxy_str}"
    async with semaphore:
        t0 = time.time()
        try:
            async with httpx.AsyncClient(
                proxy=url,
                timeout=httpx.Timeout(TEST_TIMEOUT),
                follow_redirects=True,
            ) as client:
                test_url = random.choice(TEST_URLS)
                r = await client.get(test_url)
                if r.status_code == 200:
                    ms = round((time.time() - t0) * 1000)
                    return {"proxy": proxy_str, "ms": ms}
        except Exception:
            pass
    return None


async def test_proxy_urllib(proxy_str: str, semaphore: asyncio.Semaphore) -> dict | None:
    async with semaphore:
        loop = asyncio.get_event_loop()
        t0 = time.time()
        try:
            def _check():
                proxy_url = f"http://{proxy_str}"
                handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
                opener = urllib.request.build_opener(handler)
                req = urllib.request.Request("http://httpbin.org/ip", headers={"User-Agent": "Mozilla/5.0"})
                with opener.open(req, timeout=TEST_TIMEOUT) as resp:
                    resp.read()
            await asyncio.wait_for(loop.run_in_executor(None, _check), timeout=TEST_TIMEOUT + 1)
            ms = round((time.time() - t0) * 1000)
            return {"proxy": proxy_str, "ms": ms}
        except Exception:
            pass
    return None


async def scrape_and_test(max_results: int = 10, progress_cb=None) -> dict:
    if progress_cb:
        progress_cb("Fetching proxy lists...")

    all_proxies = gather_all_proxies()
    total = len(all_proxies)

    if progress_cb:
        progress_cb(f"Found {total} candidates, testing...")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    working: list[dict] = []
    tested = 0

    test_fn = test_proxy_httpx if HAS_HTTPX else test_proxy_urllib

    batch_size = 200
    for i in range(0, min(len(all_proxies), 1000), batch_size):
        if len(working) >= max_results:
            break
        batch = all_proxies[i: i + batch_size]
        tasks = [test_fn(p, semaphore) for p in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, dict) and r:
                working.append(r)
        tested += len(batch)
        if progress_cb:
            progress_cb(f"Tested {tested}/{min(len(all_proxies), 1000)} — {len(working)} working")
        if len(working) >= max_results:
            break

    working.sort(key=lambda x: x["ms"])
    proxy_list = [w["proxy"] for w in working[:max_results]]

    return {
        "proxies": proxy_list,
        "tested": tested,
        "working": len(proxy_list),
        "total_found": total,
    }


async def main():
    args = sys.argv[1:]
    action = args[0] if args else "scrape"
    max_results = int(args[1]) if len(args) > 1 else MAX_WORKING

    if action == "scrape":
        def progress(msg):
            print(json.dumps({"progress": msg}), flush=True)

        result = await scrape_and_test(max_results=max_results, progress_cb=progress)
        print(json.dumps(result), flush=True)
    else:
        print(json.dumps({"error": f"Unknown action: {action}"}))


if __name__ == "__main__":
    asyncio.run(main())
