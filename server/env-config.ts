import fs from "fs";
import path from "path";

export const BOT_DIR = path.resolve(process.cwd(), "bot");
export const RUNTIME_SETTINGS_PATH = path.join(BOT_DIR, "runtime-settings.json");

const SECRET_KEYS = new Set([
  "TELEGRAM_BOT_TOKEN",
  "TELEGRAM_API_ID",
  "TELEGRAM_API_HASH",
  "TELEGRAM_ADMIN_ID",
  "TELEGRAM_GROUP_ID",
  "TELEGRAM_CHANNEL_ID",
  "TELEGRAM_GROUP_LINK",
  "TELEGRAM_CHANNEL_LINK",
  "NOPECHA_API_KEY",
  "CAPTCHAAI_API_KEY",
  "TWOCAPTCHA_API_KEY",
  "CAPSOLVER_API_KEY",
  "CHARGE_SK",
  "ADMIN_PIN",
  "SESSION_SECRET",
  "DATABASE_URL",
]);

const ENV_ONLY_KEYS = new Set([
  ...SECRET_KEYS,
  "TELEGRAM_GROUP_ID",
  "TELEGRAM_CHANNEL_ID",
  "TELEGRAM_GROUP_LINK",
  "TELEGRAM_CHANNEL_LINK",
  "LOGS_GROUP_ID",
  "CHARGE_AMOUNT",
  "ALLOWED_ORIGINS",
  "VITE_API_URL",
]);

export function readRuntimeSettings(): Record<string, any> {
  try {
    if (!fs.existsSync(RUNTIME_SETTINGS_PATH)) return {};
    const content = fs.readFileSync(RUNTIME_SETTINGS_PATH, "utf-8");
    return content.trim() ? JSON.parse(content) : {};
  } catch {
    return {};
  }
}

export function writeRuntimeSettings(settings: Record<string, any>) {
  fs.writeFileSync(RUNTIME_SETTINGS_PATH, JSON.stringify(settings, null, 2), "utf-8");
}

export function getConfigValue(key: string, fallback = ""): string {
  const envValue = process.env[key];
  if (envValue !== undefined && envValue !== "") return envValue;

  if (ENV_ONLY_KEYS.has(key)) return fallback;

  const runtimeValue = readRuntimeSettings()[key];
  if (runtimeValue !== undefined && runtimeValue !== null && runtimeValue !== "") {
    return String(runtimeValue);
  }

  return fallback;
}

export function getBooleanConfig(key: string, fallback: boolean): boolean {
  const value = getConfigValue(key);
  if (!value) return fallback;
  return !["false", "0", "no", "off"].includes(value.toLowerCase());
}

export function updateRuntimeSettings(updates: Record<string, any>) {
  const settings = readRuntimeSettings();
  for (const [key, value] of Object.entries(updates)) {
    if (SECRET_KEYS.has(key)) continue;
    if (value !== undefined && value !== null) settings[key] = value;
  }
  writeRuntimeSettings(settings);
}
