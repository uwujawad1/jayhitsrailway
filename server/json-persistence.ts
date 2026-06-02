import pg from "pg";
import fs from "fs";
import path from "path";
import { createPgPoolConfig } from "./pg-config";

const BOT_DIR = path.resolve(process.cwd(), "bot");

const JSON_FILES = [
  "admin_sites.json",
  "banned_users.json",
  "bot_settings.json",
  "charged_ccs.json",
  "runtime-settings.json",
  "daily_usage.json",
  "found_gates.json",
  "free_users.json",
  "gateway_status.json",
  "hitter_history.json",
  "keys.json",
  "pk_config.json",
  "premium.json",
  "razorpay_config.json",
  "referrals.json",
  "saved_bins.json",
  "skool_accounts.json",
  "skool_status.json",
  "pending_stealer.json",
  "user_hitter_prefs.json",
  "user_proxies.json",
  "user_sk_keys.json",
  "user_sites.json",
  "user_skool_accounts.json",
  "user_tiers.json",
  "users.json",
];

const DEFAULT_JSON_CONTENT: Record<string, unknown> = {
  "admin_sites.json": [],
  "banned_users.json": {},
  "bot_settings.json": {
    mass_check_enabled: true,
    inline_mass_limit: 10,
    file_mass_limit: 300,
    gateway_settings: {},
    tool_settings: {},
  },
  "charged_ccs.json": [],
  "runtime-settings.json": {},
  "daily_usage.json": {},
  "found_gates.json": {},
  "free_users.json": {},
  "gateway_status.json": {},
  "hitter_history.json": {},
  "keys.json": {},
  "pk_config.json": {},
  "premium.json": {},
  "razorpay_config.json": {},
  "referrals.json": { users: {} },
  "saved_bins.json": {},
  "skool_accounts.json": [],
  "skool_status.json": {},
  "pending_stealer.json": {},
  "user_hitter_prefs.json": {},
  "user_proxies.json": {},
  "user_sk_keys.json": {},
  "user_sites.json": {},
  "user_skool_accounts.json": {},
  "user_tiers.json": {},
  "users.json": {},
};

function normalizeJsonData(filename: string, data: unknown): unknown {
  switch (filename) {
    case "skool_accounts.json":
      return Array.isArray(data) ? data : [];
    case "referrals.json":
      if (data && typeof data === "object" && !Array.isArray(data)) {
        const typed = data as Record<string, unknown>;
        return {
          users: typed.users && typeof typed.users === "object" && !Array.isArray(typed.users) ? typed.users : {},
          usedBy: typed.usedBy && typeof typed.usedBy === "object" && !Array.isArray(typed.usedBy) ? typed.usedBy : {},
          ipUsed: typed.ipUsed && typeof typed.ipUsed === "object" && !Array.isArray(typed.ipUsed) ? typed.ipUsed : {},
        };
      }
      return { users: {}, usedBy: {}, ipUsed: {} };
    default:
      return data ?? DEFAULT_JSON_CONTENT[filename] ?? {};
  }
}

function normalizeJsonContent(filename: string, content: string): string {
  const trimmed = content.trim();
  if (!trimmed) {
    return JSON.stringify(DEFAULT_JSON_CONTENT[filename] ?? {}, null, 2);
  }

  try {
    const parsed = JSON.parse(trimmed);
    return JSON.stringify(normalizeJsonData(filename, parsed), null, 2);
  } catch {
    return JSON.stringify(DEFAULT_JSON_CONTENT[filename] ?? {}, null, 2);
  }
}

let pool: pg.Pool | null = null;
let saveInterval: ReturnType<typeof setInterval> | null = null;

function getBootstrapMode(): "empty" | "local" {
  const mode = (process.env.JSON_DB_BOOTSTRAP_MODE || "empty").toLowerCase();
  return mode === "local" ? "local" : "empty";
}

function initializeLocalJsonFilesFromDefaults() {
  for (const filename of JSON_FILES) {
    const filePath = path.join(BOT_DIR, filename);
    const defaultContent = DEFAULT_JSON_CONTENT[filename];
    if (defaultContent === undefined) continue;
    fs.writeFileSync(filePath, JSON.stringify(defaultContent, null, 2), "utf-8");
  }
}

function normalizeLocalJsonFilesOnDisk() {
  for (const filename of JSON_FILES) {
    const filePath = path.join(BOT_DIR, filename);
    if (!fs.existsSync(filePath)) {
      const fallback = JSON.stringify(DEFAULT_JSON_CONTENT[filename] ?? {}, null, 2);
      fs.writeFileSync(filePath, fallback, "utf-8");
      continue;
    }
    try {
      const raw = fs.readFileSync(filePath, "utf-8");
      const normalized = normalizeJsonContent(filename, raw);
      if (raw.trim() !== normalized.trim()) {
        fs.writeFileSync(filePath, normalized, "utf-8");
      }
    } catch {
      const fallback = JSON.stringify(DEFAULT_JSON_CONTENT[filename] ?? {}, null, 2);
      fs.writeFileSync(filePath, fallback, "utf-8");
    }
  }
}

function getPool(): pg.Pool | null {
  if (!process.env.DATABASE_URL) return null;
  if (!pool) {
    pool = new pg.Pool(createPgPoolConfig({
      max: 3,
    }));
    pool.on("error", (err) => {
      console.error("[json-persistence] Pool error:", err.message);
    });
  }
  return pool;
}

async function ensureTable(): Promise<boolean> {
  const p = getPool();
  if (!p) return false;
  try {
    await p.query(`
      CREATE TABLE IF NOT EXISTS bot_json_data (
        filename TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT NOW()
      )
    `);
    return true;
  } catch (err: any) {
    console.error("[json-persistence] Failed to create table:", err.message);
    return false;
  }
}

export async function restoreJsonFiles(): Promise<void> {
  const ready = await ensureTable();
  if (!ready) {
    if (process.env.DATABASE_URL && getBootstrapMode() === "empty") {
      initializeLocalJsonFilesFromDefaults();
      console.log("[json-persistence] Database unavailable; initialized local JSON files with empty defaults.");
      return;
    }
    console.log("[json-persistence] No database available, skipping restore.");
    return;
  }
  const p = getPool()!;
  try {
    const result = await p.query("SELECT filename, content FROM bot_json_data");
    if (result.rows.length === 0) {
      if (getBootstrapMode() === "local") {
        console.log("[json-persistence] No saved data in database, seeding from local files.");
      } else {
      initializeLocalJsonFilesFromDefaults();
      console.log("[json-persistence] No saved data in database, initializing empty defaults.");
      }
      await saveAllJsonFiles();
      return;
    }

    let restored = 0;
    for (const row of result.rows) {
      const filePath = path.join(BOT_DIR, row.filename);
      const dbContent = normalizeJsonContent(row.filename, row.content);
      if (!dbContent) continue;

      const localExists = fs.existsSync(filePath);
      const localContent = localExists ? normalizeJsonContent(row.filename, fs.readFileSync(filePath, "utf-8")) : "";

      // Pick whichever version has more data — the DB holds the last-persisted
      // production state; local files from the git repo are stale defaults after
      // a fresh deployment. But if local has MORE content than DB (new writes since
      // the last periodic save), keep local.
      const useDb = !localExists || dbContent.length > localContent.length;
      if (useDb && dbContent !== localContent) {
        fs.writeFileSync(filePath, dbContent, "utf-8");
        restored++;
      }
    }
    console.log(`[json-persistence] Restored ${restored} JSON files from database.`);
    normalizeLocalJsonFilesOnDisk();
  } catch (err: any) {
    console.error("[json-persistence] Restore failed:", err.message);
  }
}

export async function saveAllJsonFiles(): Promise<void> {
  const ready = await ensureTable();
  if (!ready) return;
  const p = getPool()!;

  let saved = 0;
  for (const filename of JSON_FILES) {
    const filePath = path.join(BOT_DIR, filename);
    if (!fs.existsSync(filePath)) continue;

    try {
      const content = fs.readFileSync(filePath, "utf-8").trim();
      if (!content) continue;
      const normalized = normalizeJsonContent(filename, content);

      await p.query(
        `INSERT INTO bot_json_data (filename, content, updated_at)
         VALUES ($1, $2, NOW())
         ON CONFLICT (filename)
         DO UPDATE SET content = $2, updated_at = NOW()`,
        [filename, normalized]
      );
      saved++;
    } catch (err: any) {
      console.error(`[json-persistence] Failed to save ${filename}:`, err.message);
    }
  }
  if (saved > 0) {
    console.log(`[json-persistence] Saved ${saved} JSON files to database.`);
  }
}

/** Immediately persist a single file to the database without waiting for the periodic save. */
export async function saveJsonFile(filename: string): Promise<void> {
  const p = getPool();
  if (!p) return;
  const ready = await ensureTable();
  if (!ready) return;

  const filePath = path.join(BOT_DIR, filename);
  if (!fs.existsSync(filePath)) return;

  try {
    const content = fs.readFileSync(filePath, "utf-8").trim();
    if (!content) return;
    const normalized = normalizeJsonContent(filename, content);
    await p.query(
      `INSERT INTO bot_json_data (filename, content, updated_at)
       VALUES ($1, $2, NOW())
       ON CONFLICT (filename)
       DO UPDATE SET content = $2, updated_at = NOW()`,
      [filename, normalized]
    );
  } catch (err: any) {
    console.error(`[json-persistence] Failed to save ${filename}:`, err.message);
  }
}

export function startPeriodicSave(intervalMs = 5 * 60 * 1000): void {
  if (saveInterval) return;
  saveInterval = setInterval(async () => {
    try {
      await saveAllJsonFiles();
    } catch (err: any) {
      console.error("[json-persistence] Periodic save failed:", err.message);
    }
  }, intervalMs);
  console.log(`[json-persistence] Auto-save every ${intervalMs / 1000}s enabled.`);
}

export function stopPeriodicSave(): void {
  if (saveInterval) {
    clearInterval(saveInterval);
    saveInterval = null;
  }
}
