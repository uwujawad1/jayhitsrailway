/**
 * OGM Checker — Data Export Script
 * Run this on your CURRENT Replit to export all bot data.
 *
 * Usage:
 *   node scripts/export_data.js
 *
 * Output:
 *   data_snapshot.json  (in project root)
 */

const { Pool } = require("pg");
const fs = require("fs");
const path = require("path");

const BOT_DIR = path.resolve(__dirname, "../bot");

const ALL_FILES = [
  "admin_sites.json",
  "banned_users.json",
  "bot_settings.json",
  "charged_ccs.json",
  "config.json",
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
  "user_hitter_prefs.json",
  "user_proxies.json",
  "user_sites.json",
  "user_skool_accounts.json",
  "user_tiers.json",
  "users.json",
];

async function main() {
  console.log("=== OGM Checker Data Export ===\n");

  const snapshot = {
    exported_at: new Date().toISOString(),
    source: "OGM Checker Bot Dashboard",
    files: {},
  };

  let dbFiles = {};
  let dbUsed = false;

  // Try loading from PostgreSQL first (most up-to-date)
  if (process.env.DATABASE_URL) {
    const pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 2 });
    try {
      const result = await pool.query("SELECT filename, content FROM bot_json_data");
      for (const row of result.rows) {
        dbFiles[row.filename] = row.content;
      }
      console.log(`✓ Loaded ${result.rows.length} files from PostgreSQL database`);
      dbUsed = true;
    } catch (e) {
      console.log("⚠ Could not read database:", e.message);
    } finally {
      await pool.end();
    }
  } else {
    console.log("⚠ No DATABASE_URL — will read local files only");
  }

  // Build snapshot: prefer DB content, fall back to local file
  let localCount = 0;
  let dbCount = 0;
  let missing = 0;

  for (const filename of ALL_FILES) {
    const filePath = path.join(BOT_DIR, filename);
    const inDb = dbFiles[filename];
    const onDisk = fs.existsSync(filePath) ? fs.readFileSync(filePath, "utf-8").trim() : null;

    // Pick whichever has more content (DB = live production, disk = possibly stale)
    let chosen = null;
    let source = "";

    if (inDb && onDisk) {
      chosen = inDb.length >= onDisk.length ? inDb : onDisk;
      source = inDb.length >= onDisk.length ? "db" : "disk";
    } else if (inDb) {
      chosen = inDb;
      source = "db";
    } else if (onDisk) {
      chosen = onDisk;
      source = "disk";
    }

    if (chosen) {
      try {
        snapshot.files[filename] = JSON.parse(chosen);
        if (source === "db") dbCount++; else localCount++;
      } catch {
        snapshot.files[filename] = chosen;
        if (source === "db") dbCount++; else localCount++;
      }
    } else {
      snapshot.files[filename] = null;
      missing++;
    }
  }

  const outPath = path.resolve(__dirname, "../data_snapshot.json");
  fs.writeFileSync(outPath, JSON.stringify(snapshot, null, 2), "utf-8");

  console.log(`\n✓ Export complete!`);
  console.log(`  From database: ${dbCount} files`);
  console.log(`  From local:    ${localCount} files`);
  console.log(`  Empty/missing: ${missing} files`);
  console.log(`\n📦 Saved to: data_snapshot.json`);
  console.log(`\n→ Copy data_snapshot.json to your new Replit project`);
  console.log(`→ Then run: node scripts/import_data.js`);
}

main().catch((e) => {
  console.error("Export failed:", e.message);
  process.exit(1);
});
