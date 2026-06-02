import asyncio
import functools
import re
import json
import os

GATEWAY_REGISTRY = {
    "auth": {
        "label": "Auth Gateways",
        "gates": {
            "st": {"name": "Stripe Auth $0", "func": "stripe_auth.stripe_auth_check", "type": "auth"},
            "skl": {"name": "Stripe Auth $0.1", "func": "skool_api.skool_api_check", "type": "auth"},
            "b3": {"name": "Braintree Auth", "func": "braintree_idt.check_card_braintree", "type": "auth"},
            "vbv": {"name": "VBV Lookup", "func": "vbv.vbv_check", "type": "auth"},
            "an": {"name": "Authorize.net Auth", "func": "authnet.authnet_check", "type": "auth"},
            "skb": {"name": "SK Base Auth $0", "func": "sk_checker.sk_base_check", "type": "auth"},
            "adn": {"name": "Adyen Auth", "func": "adyen_auth.adyen_auth_check", "type": "auth"},
            "rbc": {"name": "Stripe Auth $0 (RBC)", "func": "redblue_auth.redblue_auth_check", "type": "auth"},
        }
    },
    "charge": {
        "label": "Charge Gateways",
        "gates": {
            "cw": {"name": "Stripe Charge $6", "func": "charitywater.charitywater_check", "type": "charge"},
            "rz": {"name": "Razorpay Charge", "func": "razorpay.razorpay_check", "type": "charge"},
            "charge": {"name": "Stripe Charge SK", "func": "stripe_charge.stripe_charge_check", "type": "charge"},
            "pp": {"name": "PayPal Charge $0.01", "func": "paypal_gate.paypal_check", "type": "charge"},
            "shp": {"name": "Shopify Native", "func": "shopify_native.shopify_native_check", "type": "charge"},
            "skl1": {"name": "Stripe Charge $1", "func": "skool_charge2.skool_charge2_check", "type": "charge"},
            "skl2": {"name": "Stripe Charge $7", "func": "skool_charge.skool_charge_check", "type": "charge"},
            "b3c": {"name": "Braintree Charge", "func": "b3_charge.b3_charge_check", "type": "charge"},
            "ppn": {"name": "PayPal Charge $1", "func": "ppnormal.ppnormal_check", "type": "charge"},
            "bnc": {"name": "PayPal Charge $1", "func": "binnaclehouse.binnaclehouse_check", "type": "charge"},
            "ch": {"name": "Stripe Charge €5", "func": "donate_ch.donate_ch_check", "type": "charge"},
            "isp": {"name": "Stripe Charge $25", "func": "inspire.inspire_check", "type": "charge"},
            "auto": {"name": "Stripe Random Charge", "func": "skool_autoskool.autoskool_check", "type": "charge"},
            "azz": {"name": "Authorize.net Charge $1", "func": "authnet_azz.authnet_azz_check", "type": "charge"},
            "ppk": {"name": "PayPal Keybase $1", "func": "paypal_key.paypal_key_check", "type": "charge"},
        }
    },
}

_gateway_funcs = {}

# ── Concurrent slots per global pool ─────────────────────────────────────────
FREE_GLOBAL_CONCURRENT  = 15   # max simultaneous checks across all free users
PAID_GLOBAL_CONCURRENT  = 30   # max simultaneous checks across all silver/gold users

# ── Per-user slot limits by tier ─────────────────────────────────────────────
TIER_USER_LIMITS = {
    "free":   2,   # free users: 2 checks at once
    "silver": 5,   # silver:     5 checks at once
    "gold":   10,  # gold:       10 checks at once
}

# ── Semaphore pools ───────────────────────────────────────────────────────────
_free_semaphore  = asyncio.Semaphore(FREE_GLOBAL_CONCURRENT)
_paid_semaphore  = asyncio.Semaphore(PAID_GLOBAL_CONCURRENT)
_user_semaphores: dict = {}
_user_sem_lock   = asyncio.Lock()

async def _get_user_semaphore(user_id, tier: str = "free"):
    limit = TIER_USER_LIMITS.get(tier, TIER_USER_LIMITS["free"])
    key = (user_id, tier)
    async with _user_sem_lock:
        if key not in _user_semaphores:
            _user_semaphores[key] = asyncio.Semaphore(limit)
        return _user_semaphores[key]

_USER_TIERS_FILE = os.path.join(os.path.dirname(__file__), "user_tiers.json")
_PREMIUM_FILE    = os.path.join(os.path.dirname(__file__), "premium.json")

def _get_user_tier_local(user_id: int | str) -> str:
    """Quick tier lookup for semaphore selection — mirrors bot.py get_user_tier()."""
    uid = str(user_id)
    try:
        if os.path.exists(_USER_TIERS_FILE):
            with open(_USER_TIERS_FILE, "r") as f:
                tiers = json.load(f)
            entry = tiers.get(uid)
            if entry and isinstance(entry, dict):
                import time
                exp = entry.get("expires_at")
                if exp and time.time() > exp:
                    return "free"
                return entry.get("tier", "free")
    except Exception:
        pass
    try:
        if os.path.exists(_PREMIUM_FILE):
            with open(_PREMIUM_FILE, "r") as f:
                premium = json.load(f)
            entry = premium.get(uid)
            if entry:
                import time
                exp = entry.get("expires_at")
                if not exp or time.time() <= exp:
                    return "silver"
    except Exception:
        pass
    return "free"

USER_PROXIES_FILE = os.path.join(os.path.dirname(__file__), "user_proxies.json")
_user_proxies_cache = {}
_user_proxies_ts = 0
import threading
_proxy_file_lock = threading.Lock()

def _load_user_proxies():
    global _user_proxies_cache, _user_proxies_ts
    import time
    now = time.time()
    if _user_proxies_cache and (now - _user_proxies_ts) < 30:
        return _user_proxies_cache
    try:
        if os.path.exists(USER_PROXIES_FILE):
            with open(USER_PROXIES_FILE, "r") as f:
                _user_proxies_cache = json.load(f)
        else:
            _user_proxies_cache = {}
    except Exception:
        _user_proxies_cache = {}
    _user_proxies_ts = now
    return _user_proxies_cache

def _save_user_proxies(data):
    global _user_proxies_cache, _user_proxies_ts
    import time
    try:
        with open(USER_PROXIES_FILE, "w") as f:
            json.dump(data, f, indent=2)
        _user_proxies_cache = data
        _user_proxies_ts = time.time()
    except Exception as e:
        print(f"Error saving user proxies: {e}")

def _raw_to_formatted(raw: str) -> str | None:
    parts = raw.split(":")
    if raw.startswith(("http://", "https://", "socks5://", "socks4://")):
        return raw
    if len(parts) == 4:
        host, port, user, pwd = parts
        return f"http://{user}:{pwd}@{host}:{port}"
    elif len(parts) == 2:
        return f"http://{parts[0]}:{parts[1]}"
    return None

def get_user_proxy(user_id):
    formatted, _ = get_user_proxy_with_raw(user_id)
    return formatted

def get_user_proxy_with_raw(user_id):
    """Returns (formatted_proxy, raw_proxy) — raw is needed for removal."""
    with _proxy_file_lock:
        data = _load_user_proxies()
    user_data = data.get(str(user_id))
    if not user_data:
        return None, None
    proxies = user_data.get("proxies", [])
    if not proxies:
        return None, None
    import random
    raw = random.choice(proxies)
    formatted = _raw_to_formatted(raw)
    return formatted, raw

def auto_remove_dead_proxy(user_id, raw_proxy: str) -> bool:
    """Remove a proxy that caused a timeout. Returns True if no proxies remain."""
    if not raw_proxy:
        return False
    with _proxy_file_lock:
        data = _load_user_proxies()
        uid = str(user_id)
        if uid in data and raw_proxy in data[uid].get("proxies", []):
            data[uid]["proxies"].remove(raw_proxy)
            if not data[uid]["proxies"]:
                del data[uid]
                _save_user_proxies(data)
                return True
            _save_user_proxies(data)
    return False

def get_user_proxy_list(user_id):
    with _proxy_file_lock:
        data = _load_user_proxies()
    user_data = data.get(str(user_id))
    if not user_data:
        return []
    return user_data.get("proxies", [])

def add_user_proxy(user_id, proxy_line):
    with _proxy_file_lock:
        data = _load_user_proxies()
        uid = str(user_id)
        if uid not in data:
            data[uid] = {"proxies": []}
        if proxy_line not in data[uid]["proxies"]:
            data[uid]["proxies"].append(proxy_line)
        _save_user_proxies(data)

def remove_user_proxies(user_id):
    with _proxy_file_lock:
        data = _load_user_proxies()
        uid = str(user_id)
        if uid in data:
            del data[uid]
            _save_user_proxies(data)
            return True
        return False

def remove_single_user_proxy(user_id, proxy_line):
    with _proxy_file_lock:
        data = _load_user_proxies()
        uid = str(user_id)
        if uid in data and proxy_line in data[uid].get("proxies", []):
            data[uid]["proxies"].remove(proxy_line)
            if not data[uid]["proxies"]:
                del data[uid]
            _save_user_proxies(data)
            return True
        return False

def _resolve_func(func_path):
    if func_path in _gateway_funcs:
        return _gateway_funcs[func_path]
    module_name, func_name = func_path.rsplit('.', 1)
    try:
        mod = __import__(f'gates.{module_name}', fromlist=[func_name])
        fn = getattr(mod, func_name)
        _gateway_funcs[func_path] = fn
        return fn
    except (ImportError, AttributeError) as e:
        print(f"Failed to load gateway {func_path}: {e}")
        return None

def get_flat_registry():
    flat = {}
    for cat_key, cat_data in GATEWAY_REGISTRY.items():
        for alias, gate_info in cat_data["gates"].items():
            flat[alias] = {
                "name": gate_info["name"],
                "func_path": gate_info["func"],
                "type": gate_info["type"],
                "category": cat_key,
            }
    return flat

BOT_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "bot_settings.json")
_bot_settings_cache = {}
_bot_settings_ts = 0

def _load_bot_settings():
    global _bot_settings_cache, _bot_settings_ts
    import time
    now = time.time()
    if _bot_settings_cache and (now - _bot_settings_ts) < 3:
        return _bot_settings_cache
    try:
        if os.path.exists(BOT_SETTINGS_FILE):
            with open(BOT_SETTINGS_FILE, "r") as f:
                _bot_settings_cache = json.load(f)
        else:
            _bot_settings_cache = {"mass_check_enabled": True, "inline_mass_limit": 10, "file_mass_limit": 300, "gateway_settings": {}, "tool_settings": {}}
    except Exception:
        _bot_settings_cache = {"mass_check_enabled": True, "inline_mass_limit": 10, "file_mass_limit": 300, "gateway_settings": {}, "tool_settings": {}}
    _bot_settings_ts = now
    return _bot_settings_cache

def _save_bot_settings(data):
    global _bot_settings_cache, _bot_settings_ts
    import time
    try:
        with open(BOT_SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        _bot_settings_cache = data
        _bot_settings_ts = time.time()
    except Exception as e:
        print(f"Error saving bot settings: {e}")

def is_gateway_on(alias):
    settings = _load_bot_settings()
    gs = settings.get("gateway_settings", {}).get(alias, {})
    return gs.get("enabled", True)

def set_gateway_status(alias, status):
    settings = _load_bot_settings()
    if "gateway_settings" not in settings:
        settings["gateway_settings"] = {}
    if alias not in settings["gateway_settings"]:
        settings["gateway_settings"][alias] = {}
    settings["gateway_settings"][alias]["enabled"] = status
    _save_bot_settings(settings)

def is_gateway_premium(alias):
    settings = _load_bot_settings()
    gs = settings.get("gateway_settings", {}).get(alias, {})
    return gs.get("premium_only", False)

def is_tool_on(tool_id):
    settings = _load_bot_settings()
    ts = settings.get("tool_settings", {}).get(tool_id, {})
    return ts.get("enabled", True)

def is_tool_premium(tool_id):
    settings = _load_bot_settings()
    ts = settings.get("tool_settings", {}).get(tool_id, {})
    return ts.get("premium_only", False)

def is_mass_check_enabled():
    settings = _load_bot_settings()
    return settings.get("mass_check_enabled", True)

def get_inline_mass_limit():
    settings = _load_bot_settings()
    return settings.get("inline_mass_limit", 10)

def get_file_mass_limit():
    settings = _load_bot_settings()
    return settings.get("file_mass_limit", 300)

def checkLuhn(cardNo):
    nDigits = len(cardNo)
    nSum = 0
    isSecond = False
    for i in range(nDigits - 1, -1, -1):
        d = ord(cardNo[i]) - ord('0')
        if isSecond:
            d = d * 2
        nSum += d // 10
        nSum += d % 10
        isSecond = not isSecond
    return (nSum % 10 == 0)

BANNED_BINS = set()

def is_bin_banned(cc):
    bin6 = cc[:6]
    return bin6 in BANNED_BINS

def parse_card_input(text):
    text = text.strip()
    parts = re.split(r'[|/;:,\s]+', text)
    if len(parts) < 4:
        return None
    cc = parts[0]
    mm = parts[1]
    yy = parts[2]
    cvv = parts[3]
    if not re.match(r'^\d{12,19}$', cc):
        return None
    if not re.match(r'^\d{1,2}$', mm):
        return None
    if not re.match(r'^\d{2,4}$', yy):
        return None
    if not re.match(r'^\d{3,4}$', cvv):
        return None
    if len(yy) == 4:
        yy = yy[2:]
    mm = mm.zfill(2)
    return cc, mm, yy, cvv

_user_cooldowns = {}
COOLDOWN_SECONDS = 15

def check_cooldown(user_id):
    import time
    now = time.time()
    last = _user_cooldowns.get(user_id, 0)
    if now - last < COOLDOWN_SECONDS:
        remaining = round(COOLDOWN_SECONDS - (now - last), 1)
        return False, remaining
    _user_cooldowns[user_id] = now
    return True, 0

async def run_gateway(alias, cc, mm, yy, cvv, user_id=None, use_semaphore=True, is_admin=False):
    flat = get_flat_registry()
    gate_info = flat.get(alias)
    if not gate_info:
        return f"Unknown gateway: {alias}"

    fn = _resolve_func(gate_info["func_path"])
    if fn is None:
        return f"Gateway {alias} is currently unavailable"

    proxy = None
    raw_proxy = None
    if user_id:
        proxy, raw_proxy = get_user_proxy_with_raw(user_id)

    async def _execute():
        try:
            if asyncio.iscoroutinefunction(fn):
                if gate_info["func_path"] == "b3_CCN_charge.B3_CCN":
                    result = await asyncio.wait_for(fn(cc, mm, yy), timeout=60)
                else:
                    import inspect
                    sig = inspect.signature(fn)
                    params = list(sig.parameters.keys())
                    kwargs = {}
                    if "proxy" in params:
                        kwargs["proxy"] = proxy
                    elif "user_proxy" in params:
                        kwargs["user_proxy"] = proxy
                    if "user_id" in params and user_id:
                        kwargs["user_id"] = user_id
                    if "is_admin" in params:
                        kwargs["is_admin"] = is_admin
                    result = await asyncio.wait_for(fn(cc, mm, yy, cvv, **kwargs), timeout=90)
            else:
                loop = asyncio.get_event_loop()
                if gate_info["func_path"] == "b3_CCN_charge.B3_CCN":
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, functools.partial(fn, cc, mm, yy)),
                        timeout=90
                    )
                else:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, functools.partial(fn, cc, mm, yy, cvv)),
                        timeout=90
                    )
            return str(result) if result else "No response from gateway"
        except asyncio.TimeoutError:
            return "Gateway Timeout (90s)"
        except Exception as e:
            err = str(e)[:200]
            error_patterns = [
                "Cannot connect to host", "Connection refused", "TimeoutError",
                "ClientConnectorError", "ServerDisconnectedError", "SSL",
                "Name or service not known", "Temporary failure"
            ]
            if any(p.lower() in err.lower() for p in error_patterns):
                return "Gateway Offline / Unreachable"
            return f"Gateway Error: {err}"

    def _maybe_auto_remove(result: str) -> str:
        """If result looks like a timeout/network/proxy error, remove the dead proxy."""
        if not user_id or not raw_proxy:
            return result
        r_lower = result.lower()
        is_dead = any(k in r_lower for k in (
            "gateway timeout", "paypal timeout", "network error",
            "gateway offline", "connect timeout", "read timeout",
            "timed out", "connection refused", "cannot connect",
            "407", "connect tunnel", "proxy auth", "sslcertverificationerror",
            "max retries exceeded", "remotedisconnected", "connection reset",
        ))
        if is_dead:
            all_dead = auto_remove_dead_proxy(user_id, raw_proxy)
            if all_dead:
                return "Error - Proxy dead: all your proxies were removed. Go to Settings to add working proxies or check without proxy."
            return result + " [Dead proxy removed automatically]"
        return result

    if use_semaphore:
        if is_admin:
            # Admins bypass all semaphores — always instant
            return await _execute()
        if user_id:
            tier = _get_user_tier_local(user_id)
            user_sem   = await _get_user_semaphore(user_id, tier)
            global_sem = _free_semaphore if tier == "free" else _paid_semaphore
            async with global_sem:
                async with user_sem:
                    return _maybe_auto_remove(await _execute())
        else:
            async with _free_semaphore:
                return _maybe_auto_remove(await _execute())
    else:
        return _maybe_auto_remove(await _execute())

def classify_response(response_text):
    resp_lower = response_text.lower()

    if resp_lower.startswith("charged"):
        return "CHARGED"

    if resp_lower.startswith("approved"):
        if any(k in resp_lower for k in ["charged", "payment successful", "payment succeeded",
                                          "thank you", "order placed", "subscription created"]):
            return "CHARGED"
        return "APPROVED"

    if resp_lower.startswith("declined"):
        return "DECLINED"

    if resp_lower.startswith("error"):
        return "DECLINED"

    vbv_keywords = ["vbv/3ds required", "vbv/3ds recommended", "vbv/3ds optional",
                    "challenge required", "(vbv enrolled)", "3ds required",
                    "lookup enrolled", "lookup_enrolled", "3ds rejected",
                    "frictionless failed",
                    "3d passed", "not enrolled (no vbv)", "not_supported",
                    "frictionless (no vbv)", "attempt successful (no vbv)",
                    "bypassed (no vbv)", "bypassed", "lookup_not_enrolled",
                    "lookup_bypassed", "(no vbv)"]
    if any(k in resp_lower for k in vbv_keywords):
        return "APPROVED"

    charged_keywords = ["charged", "payment successful", "payment succeeded",
                        "thank you", "order placed", "subscription created",
                        "successfully added", "transaction successful",
                        "processing (3ds bypassed)", "processing (likely charged)",
                        "processing (3ds cancelled)"]
    approved_keywords = ["3ds", "3d_auth", "3ds_authentication", "3d_authentication",
                         "invalid_cvv", "incorrect_cvv", "insufficient_funds",
                         "approved", "success", "invalid_cvc", "incorrect_cvc",
                         "incorrect_zip", "insufficient funds", "card approved",
                         "transaction approved",
                         "lost_card", "stolen_card", "pickup_card",
                         "risk", "review", "fraudulent",
                         "rate_limit", "rate limit", "live key"]
    declined_keywords = ["declined", "decline", "generic_decline", "card_declined",
                         "expired_card", "not_permitted", "invalid_account",
                         "card not supported", "invalid card", "dead",
                         "revoked", "api_key_expired", "test mode",
                         "do_not_honor", "do not honor",
                         "existing_account_restricted", "restricted",
                         "timeout", "timed out", "network error",
                         "invalid_billing_address", "billing address"]
    if any(k in resp_lower for k in charged_keywords):
        return "CHARGED"
    if any(k in resp_lower for k in approved_keywords):
        return "APPROVED"
    if any(k in resp_lower for k in declined_keywords):
        return "DECLINED"
    return "UNKNOWN"
