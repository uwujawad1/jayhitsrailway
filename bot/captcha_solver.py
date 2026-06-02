import aiohttp
import asyncio
import os
import re
import json
import logging
from urllib.parse import urlparse, urljoin
from env_config import get_setting

logger = logging.getLogger(__name__)

NOPECHA_SUBMIT = "https://api.nopecha.com/token"
NOPECHA_RESULT = "https://api.nopecha.com/token"

CAPTCHAAI_IN = "https://ocr.captchaai.com/in.php"
CAPTCHAAI_RES = "https://ocr.captchaai.com/res.php"

TWOCAPTCHA_IN  = "https://2captcha.com/in.php"
TWOCAPTCHA_RES = "https://2captcha.com/res.php"

CAPSOLVER_URL = "https://api.capsolver.com/createTask"
CAPSOLVER_RES = "https://api.capsolver.com/getTaskResult"

MAX_POLL_ATTEMPTS = 40
POLL_INTERVAL = 5

def _get_config_key(key: str, env_var: str) -> str:
    """Read captcha keys from environment/runtime settings."""
    return get_setting(env_var) or get_setting(key)

def get_nopecha_key() -> str:
    key = _get_config_key("nopecha_api_key", "NOPECHA_API_KEY")
    if key and key.startswith("sub_"):
        logger.warning("nopecha_api_key looks like a Stripe subscription ID, not a NopeCHA key — skipping")
        return ""
    return key

def get_captchaai_key() -> str:
    return _get_config_key("captchaai_api_key", "CAPTCHAAI_API_KEY")

def get_twocaptcha_key() -> str:
    return _get_config_key("twocaptcha_api_key", "TWOCAPTCHA_API_KEY")

def get_capsolver_key() -> str:
    return _get_config_key("capsolver_api_key", "CAPSOLVER_API_KEY")

def has_any_solver_key() -> bool:
    return bool(get_nopecha_key() or get_captchaai_key() or get_twocaptcha_key() or get_capsolver_key())

NOPECHA_KEY = os.environ.get("NOPECHA_API_KEY", "")
CAPTCHAAI_KEY = os.environ.get("CAPTCHAAI_API_KEY", "")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


async def _nopecha_solve(task_type, sitekey, pageurl, session=None, extra=None):
    key = get_nopecha_key()
    if not key:
        return None
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        payload = {
            "type": task_type,
            "sitekey": sitekey,
            "url": pageurl,
            "key": key,
        }
        if extra:
            payload.update(extra)
        logger.info(f"NopeCHA submit: type={task_type}, sitekey={sitekey[:20]}..., url={pageurl[:60]}")
        async with session.post(NOPECHA_SUBMIT, json=payload) as resp:
            result = await resp.json(content_type=None)
            if "error" in result:
                logger.warning(f"NopeCHA submit error {result.get('error')}: {result.get('message', '')}")
                return None
            task_id = result.get("data")
            if not task_id:
                logger.warning(f"NopeCHA: no task_id in response: {result}")
                return None
            logger.info(f"NopeCHA task created: {task_id}")

        await asyncio.sleep(10)

        for attempt in range(MAX_POLL_ATTEMPTS):
            params = {"id": task_id, "key": key}
            async with session.get(NOPECHA_RESULT, params=params) as resp:
                result = await resp.json(content_type=None)
                if "error" in result:
                    err = result["error"]
                    err_msg = result.get("message", "")
                    if err in (9, 14) or err == "Incomplete" or "Incomplete" in str(err_msg):
                        pass
                    else:
                        logger.warning(f"NopeCHA poll error {err}: {err_msg}")
                        return None
                else:
                    data = result.get("data")
                    token = data[0] if isinstance(data, list) and data else data
                    if token and isinstance(token, str) and len(token) > 20:
                        logger.info(f"NopeCHA solved! Token: {str(token)[:30]}...")
                        return token
            await asyncio.sleep(POLL_INTERVAL)

        logger.warning("NopeCHA timeout - max poll attempts reached")
        return None
    except Exception as e:
        logger.error(f"NopeCHA solve error: {e}")
        return None
    finally:
        if own_session:
            await session.close()


async def _captchaai_solve(method, sitekey, pageurl, session=None, extra=None):
    key = get_captchaai_key()
    if not key:
        return None
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        submit_data = {
            "key": key,
            "method": method,
            "sitekey": sitekey,
            "pageurl": pageurl,
            "json": "1",
        }
        if extra:
            submit_data.update(extra)
        logger.info(f"CaptchaAI submit: method={method}, sitekey={sitekey[:20]}..., url={pageurl[:60]}")
        async with session.post(CAPTCHAAI_IN, data=submit_data) as resp:
            result = await resp.json(content_type=None)
            if result.get("status") != 1:
                logger.warning(f"CaptchaAI submit failed: {result}")
                return None
            task_id = result["request"]
            logger.info(f"CaptchaAI task created: {task_id}")

        await asyncio.sleep(10)

        for attempt in range(MAX_POLL_ATTEMPTS):
            params = {"key": key, "action": "get", "id": task_id, "json": "1"}
            async with session.get(CAPTCHAAI_RES, params=params) as resp:
                result = await resp.json(content_type=None)
                if result.get("status") == 1:
                    token = result["request"]
                    logger.info(f"CaptchaAI solved! Token: {token[:30]}...")
                    return token
                if result.get("request") != "CAPCHA_NOT_READY":
                    logger.warning(f"CaptchaAI error: {result}")
                    return None
            await asyncio.sleep(POLL_INTERVAL)

        logger.warning("CaptchaAI timeout")
        return None
    except Exception as e:
        logger.error(f"CaptchaAI solve error: {e}")
        return None
    finally:
        if own_session:
            await session.close()


async def _twocaptcha_solve(method, sitekey, pageurl, session=None, extra=None):
    """2captcha / Anti-Captcha compatible solving (same API)."""
    key = get_twocaptcha_key()
    if not key:
        return None
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        submit_data = {
            "key": key,
            "method": method,
            "sitekey": sitekey,
            "pageurl": pageurl,
            "json": "1",
        }
        if extra:
            submit_data.update(extra)
        logger.info(f"2captcha submit: method={method}, sitekey={sitekey[:20]}..., url={pageurl[:60]}")
        async with session.post(TWOCAPTCHA_IN, data=submit_data) as resp:
            result = await resp.json(content_type=None)
            if result.get("status") != 1:
                logger.warning(f"2captcha submit failed: {result}")
                return None
            task_id = result["request"]
            logger.info(f"2captcha task created: {task_id}")

        await asyncio.sleep(15)

        for attempt in range(MAX_POLL_ATTEMPTS):
            params = {"key": key, "action": "get", "id": task_id, "json": "1"}
            async with session.get(TWOCAPTCHA_RES, params=params) as resp:
                result = await resp.json(content_type=None)
                if result.get("status") == 1:
                    token = result["request"]
                    logger.info(f"2captcha solved! Token: {token[:30]}...")
                    return token
                if result.get("request") not in ("CAPCHA_NOT_READY", "CAPTCHA_NOT_READY"):
                    logger.warning(f"2captcha error: {result}")
                    return None
            await asyncio.sleep(POLL_INTERVAL)

        logger.warning("2captcha timeout")
        return None
    except Exception as e:
        logger.error(f"2captcha solve error: {e}")
        return None
    finally:
        if own_session:
            await session.close()


async def _capsolver_solve(task_type, sitekey, pageurl, session=None, extra=None):
    """CapSolver API — great hCaptcha support, no image grid required."""
    key = get_capsolver_key()
    if not key:
        return None
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        task = {
            "type": task_type,
            "websiteURL": pageurl,
            "websiteKey": sitekey,
        }
        if extra:
            task.update(extra)
        payload = {"clientKey": key, "task": task}
        logger.info(f"CapSolver submit: type={task_type}, sitekey={sitekey[:20]}..., url={pageurl[:60]}")
        async with session.post(CAPSOLVER_URL, json=payload) as resp:
            result = await resp.json(content_type=None)
            if result.get("errorId") != 0:
                logger.warning(f"CapSolver submit error: {result.get('errorCode')} {result.get('errorDescription')}")
                return None
            task_id = result.get("taskId")
            if not task_id:
                logger.warning(f"CapSolver: no taskId in response: {result}")
                return None
            logger.info(f"CapSolver task created: {task_id}")

        await asyncio.sleep(5)

        for attempt in range(MAX_POLL_ATTEMPTS):
            poll_payload = {"clientKey": key, "taskId": task_id}
            async with session.post(CAPSOLVER_RES, json=poll_payload) as resp:
                result = await resp.json(content_type=None)
                if result.get("errorId") != 0:
                    logger.warning(f"CapSolver poll error: {result.get('errorCode')}")
                    return None
                status = result.get("status")
                if status == "ready":
                    solution = result.get("solution", {})
                    token = solution.get("gRecaptchaResponse") or solution.get("token") or solution.get("userAgent")
                    if token:
                        logger.info(f"CapSolver solved! Token: {str(token)[:30]}...")
                        return token
                    logger.warning(f"CapSolver ready but no token in solution: {solution}")
                    return None
                elif status != "processing":
                    logger.warning(f"CapSolver unknown status: {status}")
                    return None
            await asyncio.sleep(POLL_INTERVAL)

        logger.warning("CapSolver timeout")
        return None
    except Exception as e:
        logger.error(f"CapSolver solve error: {e}")
        return None
    finally:
        if own_session:
            await session.close()


async def solve_hcaptcha(sitekey, pageurl, session=None):
    if get_nopecha_key():
        token = await _nopecha_solve("hcaptcha", sitekey, pageurl, session)
        if token:
            return token
        logger.info("NopeCHA hCaptcha failed, trying next solver...")
    if get_captchaai_key():
        token = await _captchaai_solve("hcaptcha", sitekey, pageurl, session)
        if token:
            return token
        logger.info("CaptchaAI hCaptcha failed, trying 2captcha...")
    if get_twocaptcha_key():
        token = await _twocaptcha_solve("hcaptcha", sitekey, pageurl, session)
        if token:
            return token
        logger.info("2captcha hCaptcha failed, trying CapSolver...")
    return await _capsolver_solve("HCaptchaTaskProxyless", sitekey, pageurl, session)


async def solve_hcaptcha_enterprise(sitekey, pageurl, rqdata=None, session=None):
    extra_cs = {}
    if rqdata:
        extra_cs["enterprisePayload"] = {"rqdata": rqdata}

    if get_nopecha_key():
        nopecha_extra = {}
        if rqdata:
            nopecha_extra["rqdata"] = rqdata
        token = await _nopecha_solve("hcaptcha", sitekey, pageurl, session, extra=nopecha_extra or None)
        if token:
            return token
        logger.info("NopeCHA hCaptcha enterprise failed, trying next solver...")
    if get_captchaai_key():
        captchaai_extra = {}
        if rqdata:
            captchaai_extra["data"] = rqdata
        token = await _captchaai_solve("hcaptcha", sitekey, pageurl, session, extra=captchaai_extra or None)
        if token:
            return token
        logger.info("CaptchaAI enterprise failed, trying 2captcha...")
    if get_twocaptcha_key():
        extra_2c = {"enterprise": "1"}
        if rqdata:
            extra_2c["data"] = rqdata
        token = await _twocaptcha_solve("hcaptcha", sitekey, pageurl, session, extra=extra_2c)
        if token:
            return token
        logger.info("2captcha enterprise failed, trying CapSolver...")
    return await _capsolver_solve("HCaptchaEnterpriseTaskProxyless", sitekey, pageurl, session, extra=extra_cs or None)


async def solve_recaptcha_v2(sitekey, pageurl, session=None):
    if get_nopecha_key():
        token = await _nopecha_solve("recaptcha2", sitekey, pageurl, session)
        if token:
            return token
        logger.info("NopeCHA reCaptcha v2 failed, trying next solver...")
    if get_captchaai_key():
        token = await _captchaai_solve("userrecaptcha", sitekey, pageurl, session)
        if token:
            return token
        logger.info("CaptchaAI reCaptcha failed, trying 2captcha...")
    if get_twocaptcha_key():
        token = await _twocaptcha_solve("userrecaptcha", sitekey, pageurl, session)
        if token:
            return token
        logger.info("2captcha reCaptcha failed, trying CapSolver...")
    return await _capsolver_solve("ReCaptchaV2TaskProxyless", sitekey, pageurl, session)


async def solve_turnstile(sitekey, pageurl, session=None, action=None, cdata=None):
    if get_nopecha_key():
        extra = {}
        if action:
            extra["action"] = action
        if cdata:
            extra["cdata"] = cdata
        token = await _nopecha_solve("turnstile", sitekey, pageurl, session, extra)
        if token:
            return token
        logger.info("NopeCHA Turnstile failed, trying CaptchaAI...")
    if get_captchaai_key():
        extra = {}
        if action:
            extra["action"] = action
        if cdata:
            extra["data"] = cdata
        token = await _captchaai_solve("turnstile", sitekey, pageurl, session, extra)
        if token:
            return token
        logger.info("CaptchaAI Turnstile failed, trying 2captcha...")
    if get_twocaptcha_key():
        extra = {}
        if action:
            extra["action"] = action
        if cdata:
            extra["data"] = cdata
        token = await _twocaptcha_solve("turnstile", sitekey, pageurl, session, extra)
        if token:
            return token
        logger.info("2captcha Turnstile failed, trying CapSolver...")
    cs_extra = {}
    if action:
        cs_extra["action"] = action
    return await _capsolver_solve("AntiTurnstileTaskProxyless", sitekey, pageurl, session, extra=cs_extra or None)


def _extract_hcaptcha_sitekey(html):
    patterns = [
        r'data-sitekey=["\']([a-f0-9\-]{36})["\']',
        r'"sitekey"\s*:\s*"([a-f0-9\-]{36})"',
        r"'sitekey'\s*:\s*'([a-f0-9\-]{36})'",
        r'hcaptcha\.com[^"\']*sitekey=([a-f0-9\-]{36})',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _extract_recaptcha_sitekey(html):
    patterns = [
        r'data-sitekey=["\']([A-Za-z0-9_\-]{20,})["\']',
        r'"sitekey"\s*:\s*"([A-Za-z0-9_\-]{20,})"',
        r'grecaptcha\.render\([^,]*,\s*\{[^}]*["\']sitekey["\']\s*:\s*["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _extract_turnstile_params(html):
    params = {'sitekey': None, 'action': None, 'cdata': None}

    sitekey_patterns = [
        r'class=["\'][^"\']*cf-turnstile[^"\']*["\'][^>]*data-sitekey=["\']([^"\']+)["\']',
        r'data-sitekey=["\']([^"\']+)["\'][^>]*class=["\'][^"\']*cf-turnstile',
        r'challenges\.cloudflare\.com/turnstile[^"\']*sitekey=([^&"\'&amp;]+)',
        r'data-sitekey=["\']([0-9a-zA-Z_x-]+)["\']',
        r'sitekey[\s"\'=:]+["\']?(0x[0-9a-zA-Z_-]+)',
        r'"sitekey"\s*:\s*"([^"]+)"',
        r"'sitekey'\s*:\s*'([^']+)'",
        r'siteKey["\s:=]+["\']([^"\']+)["\']',
    ]
    for pat in sitekey_patterns:
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m and len(m.group(1)) > 10:
            params['sitekey'] = m.group(1)
            break

    turnstile_block = re.search(r'(<[^>]*cf-turnstile[^>]*>)', html, re.IGNORECASE | re.DOTALL)
    if turnstile_block:
        block = turnstile_block.group(1)
        action_m = re.search(r'data-action=["\']([^"\']+)["\']', block, re.IGNORECASE)
        if action_m:
            params['action'] = action_m.group(1)
        cdata_m = re.search(r'data-cdata=["\']([^"\']+)["\']', block, re.IGNORECASE)
        if cdata_m:
            params['cdata'] = cdata_m.group(1)

    if not params['action']:
        action_m = re.search(r'data-action=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if action_m:
            params['action'] = action_m.group(1)
    if not params['cdata']:
        cdata_m = re.search(r'data-cdata=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if cdata_m:
            params['cdata'] = cdata_m.group(1)

    js_action = re.search(r'["\']action["\']\s*:\s*["\']([^"\']+)["\']', html)
    if js_action and not params['action']:
        params['action'] = js_action.group(1)
    js_cdata = re.search(r'["\']cData["\']\s*:\s*["\']([^"\']+)["\']', html)
    if js_cdata and not params['cdata']:
        params['cdata'] = js_cdata.group(1)

    return params


def _detect_captcha_type(html):
    html_lower = html.lower()
    if 'cf-turnstile' in html_lower or 'challenges.cloudflare.com/turnstile' in html_lower:
        return 'turnstile'
    if 'hcaptcha' in html_lower or 'h-captcha' in html_lower:
        return 'hcaptcha'
    if 'turnstile' in html_lower:
        return 'turnstile'
    if 'recaptcha' in html_lower or 'g-recaptcha' in html_lower:
        return 'recaptcha'
    return 'turnstile'


def _extract_form_data(html):
    data = {}

    auth_patterns = [
        r'name=["\']authenticity_token["\'][^>]*value=["\']([^"\']+)["\']',
        r'value=["\']([^"\']+)["\'][^>]*name=["\']authenticity_token["\']',
        r'"authenticity_token"\s*:\s*"([^"]+)"',
    ]
    for pat in auth_patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            data['authenticity_token'] = m.group(1)
            break

    hidden_inputs = re.findall(
        r'<input[^>]+type=["\']hidden["\'][^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']',
        html, re.IGNORECASE
    )
    hidden_inputs2 = re.findall(
        r'<input[^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\'][^>]*type=["\']hidden["\']',
        html, re.IGNORECASE
    )
    for name, value in hidden_inputs + hidden_inputs2:
        if name not in data:
            data[name] = value

    return data


def _extract_form_action(html, page_url):
    action_match = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if action_match:
        action_url = action_match.group(1)
        if action_url.startswith("http"):
            return action_url
        parsed = urlparse(page_url)
        if action_url.startswith("/"):
            return f"{parsed.scheme}://{parsed.netloc}{action_url}"
        return urljoin(page_url, action_url)
    return page_url


async def solve_captcha_on_page(html, page_url, session=None):
    captcha_type = _detect_captcha_type(html)
    logger.info(f"solve_captcha_on_page: detected={captcha_type}, url={page_url[:60]}")

    token = None
    if captcha_type == "hcaptcha":
        sitekey = _extract_hcaptcha_sitekey(html)
        if not sitekey:
            logger.warning("hCaptcha detected but no sitekey found")
            return None
        token = await solve_hcaptcha(sitekey, page_url, session)
    elif captcha_type == "recaptcha":
        sitekey = _extract_recaptcha_sitekey(html)
        if not sitekey:
            logger.warning("reCaptcha detected but no sitekey found")
            return None
        token = await solve_recaptcha_v2(sitekey, page_url, session)
    elif captcha_type == "turnstile":
        params = _extract_turnstile_params(html)
        if not params['sitekey']:
            logger.warning("Turnstile detected but no sitekey found")
            return None
        token = await solve_turnstile(params['sitekey'], page_url, session, params['action'], params['cdata'])

    return token


async def submit_captcha_token(session, page_url, token, captcha_type, html):
    try:
        form_action = _extract_form_action(html, page_url)
        form_data = _extract_form_data(html)

        if captcha_type == "hcaptcha":
            form_data["h-captcha-response"] = token
            form_data["g-recaptcha-response"] = token
        elif captcha_type == "recaptcha":
            form_data["g-recaptcha-response"] = token
        elif captcha_type == "turnstile":
            form_data["cf-turnstile-response"] = token
        else:
            form_data["cf-turnstile-response"] = token
            form_data["h-captcha-response"] = token
            form_data["g-recaptcha-response"] = token

        headers = {
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': page_url,
            'Origin': f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}",
        }

        logger.info(f"Submitting captcha token to: {form_action[:80]}, fields: {list(form_data.keys())}")

        async with session.post(
            form_action,
            data=form_data,
            headers=headers,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            final_url = str(resp.url)
            status = resp.status
            text = await resp.text()
            logger.info(f"Captcha submit response: status={status}, final_url={final_url[:80]}")

            if "checkpoint" not in final_url.lower() and "captcha" not in final_url.lower():
                logger.info("Captcha solved - redirected away from checkpoint")
                return final_url, text, True

            if "checkpoint" not in text.lower() and "captcha" not in text.lower():
                logger.info("Captcha solved - no more captcha content on page")
                return final_url, text, True

            logger.warning(f"Captcha submission did not clear checkpoint. Status: {status}")
            return final_url, text, False

    except Exception as e:
        logger.error(f"submit_captcha_token error: {e}", exc_info=True)
        return page_url, "", False


async def solve_checkpoint(checkpoint_url, http_session):
    if not get_nopecha_key() and not get_captchaai_key():
        logger.warning("No captcha API key set, cannot solve checkpoint")
        return None

    try:
        headers = {
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        logger.info(f"Fetching checkpoint URL: {checkpoint_url[:80]}")
        async with http_session.get(
            checkpoint_url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=20),
            allow_redirects=True,
        ) as resp:
            html = await resp.text()
            page_url = str(resp.url)
            status = resp.status
            logger.info(f"Checkpoint page status: {status}, url: {page_url[:80]}, html_len: {len(html)}")

        if not html or len(html) < 50:
            logger.warning(f"Checkpoint page empty or too short ({len(html)} chars)")
            return None

        captcha_type = _detect_captcha_type(html)
        token = await solve_captcha_on_page(html, page_url, http_session)

        if not token:
            logger.warning("Failed to solve captcha - no token received")
            return None

        logger.info(f"Got captcha token, submitting to checkpoint...")
        _, _, success = await submit_captcha_token(http_session, page_url, token, captcha_type, html)
        return success or None

    except Exception as e:
        logger.error(f"solve_checkpoint error: {e}", exc_info=True)
        return None
