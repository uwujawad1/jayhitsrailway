import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

BOT_DIR = Path(__file__).resolve().parent
APP_DIR = BOT_DIR.parent
RUNTIME_SETTINGS_PATH = BOT_DIR / "runtime-settings.json"
ENV_ONLY_KEYS = {
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_ADMIN_ID",
    "TELEGRAM_GROUP_ID",
    "TELEGRAM_CHANNEL_ID",
    "TELEGRAM_GROUP_LINK",
    "TELEGRAM_CHANNEL_LINK",
    "LOGS_GROUP_ID",
    "NOPECHA_API_KEY",
    "CAPTCHAAI_API_KEY",
    "TWOCAPTCHA_API_KEY",
    "CAPSOLVER_API_KEY",
    "CHARGE_SK",
    "CHARGE_AMOUNT",
    "ADMIN_PIN",
    "SESSION_SECRET",
    "DATABASE_URL",
}

if load_dotenv:
    load_dotenv(APP_DIR / ".env")
    load_dotenv(APP_DIR / ".env.local", override=True)
    load_dotenv(BOT_DIR / ".env")
    load_dotenv(BOT_DIR / ".env.local", override=True)


def _runtime_settings() -> dict:
    try:
        if RUNTIME_SETTINGS_PATH.exists():
            return json.loads(RUNTIME_SETTINGS_PATH.read_text(encoding="utf-8") or "{}")
    except Exception:
        pass
    return {}


def get_setting(key: str, default: str = "") -> str:
    value = os.environ.get(key)
    if value not in (None, ""):
        return str(value)
    if key in ENV_ONLY_KEYS:
        return default
    value = _runtime_settings().get(key)
    if value not in (None, ""):
        return str(value)
    return default


def get_bool_setting(key: str, default: bool = False) -> bool:
    value = get_setting(key)
    if not value:
        return default
    return str(value).lower() not in ("0", "false", "no", "off")


def write_runtime_setting(key: str, value):
    settings = _runtime_settings()
    settings[key] = value
    RUNTIME_SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
