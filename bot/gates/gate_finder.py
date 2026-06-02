import asyncio
import aiohttp
import re
import time
import random
import json
import os
import logging
from urllib.parse import quote_plus, urlparse, parse_qs
from bs4 import BeautifulSoup

logger = logging.getLogger("gate_finder")

YAHOO_SEARCH_URL = "https://search.yahoo.com/search"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
]

SKOOL_DORKS = [
    'site:skool.com "join" "per month"',
    'site:skool.com "join" "$" "month"',
    'site:skool.com "per month" "community"',
    'site:skool.com "monthly" "join" "membership"',
    'site:skool.com "$7" "join"',
    'site:skool.com "$1" "join" "month"',
    'site:skool.com "$5" "join"',
    'site:skool.com "$9" "join"',
    'site:skool.com "$10" "join"',
    'site:skool.com "$29" "join"',
    'site:skool.com "$49" "join"',
    'site:skool.com "$99" "join"',
    'site:skool.com "paid" "community" "join"',
    'site:skool.com "subscribe" "monthly"',
    'site:skool.com "membership" "price"',
    'site:skool.com "checkout" "join"',
    'site:skool.com "join group" "per month"',
    'site:skool.com inurl:about "per month"',
]

BLOCKED_KEYWORDS = [
    "blog", "article", "review", "tutorial", "guide", "how-to", "help",
    "docs", "documentation", "support", "forum", "reddit", "youtube",
    "twitter", "facebook", "instagram", "linkedin", "tiktok",
]

RESULTS_FILE = os.path.join(os.path.dirname(__file__), "..", "found_gates.json")

SKOOL_API = "https://api2.skool.com"


def _random_ua():
    return random.choice(USER_AGENTS)


def _extract_yahoo_urls(html):
    urls = []
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        if "skool.com" in href:
            clean = href
            if "/RU=" in clean:
                match = re.search(r'/RU=([^/]+)/', clean)
                if match:
                    from urllib.parse import unquote
                    clean = unquote(match.group(1))
            if "skool.com" in clean and clean.startswith("http"):
                parsed = urlparse(clean)
                path = parsed.path.strip("/")
                parts = path.split("/")
                if parts and parts[0] and parts[0] not in ("blog", "games", "search"):
                    group_slug = parts[0]
                    if not any(kw in clean.lower() for kw in BLOCKED_KEYWORDS):
                        final_url = f"https://www.skool.com/{group_slug}"
                        if final_url not in urls:
                            urls.append(final_url)
    return urls


async def _yahoo_search(session, query, max_pages=3):
    all_urls = []
    for page in range(max_pages):
        params = {
            "p": query,
            "b": str(page * 10 + 1),
        }
        headers = {
            "User-Agent": _random_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            async with session.get(YAHOO_SEARCH_URL, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"Yahoo returned {resp.status} for query: {query}")
                    break
                html = await resp.text()
                if "captcha" in html.lower() or "robot" in html.lower():
                    logger.warning("Yahoo CAPTCHA detected, stopping search")
                    break
                urls = _extract_yahoo_urls(html)
                new_count = 0
                for u in urls:
                    if u not in all_urls:
                        all_urls.append(u)
                        new_count += 1
                if new_count == 0:
                    break
        except Exception as e:
            logger.warning(f"Yahoo search error: {e}")
            break
        await asyncio.sleep(random.uniform(2.0, 4.0))
    return all_urls


async def _validate_skool_group(session, group_slug):
    info = {
        "slug": group_slug,
        "name": None,
        "group_id": None,
        "price": None,
        "currency": None,
        "is_paid": False,
        "member_count": None,
        "status": "unknown",
    }
    headers = {
        "User-Agent": _random_ua(),
        "Accept": "application/json",
    }
    try:
        async with session.get(f"{SKOOL_API}/groups/{group_slug}", headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                data = await resp.json()
                info["name"] = data.get("name", group_slug)
                info["group_id"] = data.get("id") or data.get("groupId")
                info["member_count"] = data.get("memberCount") or data.get("member_count")

                price_data = data.get("price") or data.get("subscription") or {}
                if isinstance(price_data, dict):
                    amount = price_data.get("amount") or price_data.get("price")
                    if amount:
                        info["price"] = amount
                        info["currency"] = price_data.get("currency", "usd")
                        info["is_paid"] = True

                if not info["is_paid"]:
                    raw = json.dumps(data).lower()
                    price_match = re.search(r'\$(\d+(?:\.\d{2})?)\s*(?:/\s*)?(?:per\s+)?month', raw)
                    if price_match:
                        info["price"] = float(price_match.group(1))
                        info["is_paid"] = True
                    elif "free" in raw and "paid" not in raw:
                        info["is_paid"] = False
                        info["status"] = "free"
                    elif any(k in raw for k in ['"price"', '"amount"', '"subscription"', "per month", "monthly"]):
                        info["is_paid"] = True

                info["status"] = "paid" if info["is_paid"] else "free"
            elif resp.status == 404:
                info["status"] = "not_found"
            else:
                info["status"] = f"error_{resp.status}"
    except Exception as e:
        info["status"] = f"error: {str(e)[:50]}"

    if not info["is_paid"] and info["status"] not in ("not_found",):
        try:
            async with session.get(f"{SKOOL_API}/groups/{group_slug}/about", headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    raw = json.dumps(data).lower()
                    if any(k in raw for k in ['"price"', '"amount"', "per month", "monthly", "subscription"]):
                        info["is_paid"] = True
                        info["status"] = "paid"
                        price_match = re.search(r'\$(\d+(?:\.\d{2})?)', raw)
                        if price_match:
                            info["price"] = float(price_match.group(1))
                    if not info["group_id"]:
                        gid = data.get("id") or data.get("groupId")
                        if isinstance(data.get("group"), dict):
                            gid = gid or data["group"].get("id")
                        info["group_id"] = gid
        except Exception:
            pass

    return info


async def find_gates(progress_callback=None, max_dorks=None):
    found_groups = []
    checked_slugs = set()
    total_urls = 0
    paid_count = 0
    free_count = 0

    dorks = SKOOL_DORKS[:max_dorks] if max_dorks else SKOOL_DORKS

    async with aiohttp.ClientSession() as session:
        for i, dork in enumerate(dorks):
            if progress_callback:
                await progress_callback(
                    f"Searching ({i+1}/{len(dorks)}): `{dork[:50]}...`\n"
                    f"Found: {paid_count} paid | {free_count} free | {total_urls} URLs checked"
                )

            urls = await _yahoo_search(session, dork, max_pages=2)
            total_urls += len(urls)

            for url in urls:
                slug = url.replace("https://www.skool.com/", "").strip("/")
                if slug in checked_slugs or not slug:
                    continue
                checked_slugs.add(slug)

                info = await _validate_skool_group(session, slug)
                await asyncio.sleep(random.uniform(0.5, 1.5))

                if info["status"] == "not_found":
                    continue

                if info["is_paid"]:
                    paid_count += 1
                    found_groups.append(info)
                    if progress_callback:
                        price_str = f"${info['price']}" if info['price'] else "paid"
                        await progress_callback(
                            f"FOUND PAID: **{info['name'] or slug}** ({price_str}/mo)\n"
                            f"Searching ({i+1}/{len(dorks)})...\n"
                            f"Found: {paid_count} paid | {free_count} free | {total_urls} URLs checked"
                        )
                else:
                    free_count += 1

    try:
        existing = []
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE, "r") as f:
                existing = json.load(f)
        existing_slugs = {g["slug"] for g in existing}
        for g in found_groups:
            if g["slug"] not in existing_slugs:
                existing.append(g)
        with open(RESULTS_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        logger.warning(f"Error saving results: {e}")

    return {
        "paid_groups": found_groups,
        "total_urls": total_urls,
        "paid_count": paid_count,
        "free_count": free_count,
        "checked": len(checked_slugs),
    }


def get_saved_gates():
    try:
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def get_best_gate(exclude_slugs=None):
    gates = get_saved_gates()
    exclude = set(exclude_slugs or [])
    paid = [g for g in gates if g.get("is_paid") and g["slug"] not in exclude]
    paid.sort(key=lambda g: (g.get("price") or 999, -(g.get("member_count") or 0)))
    return paid[0] if paid else None
