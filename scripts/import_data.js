/**
 * OGM Checker — Data Import Script
 * Run this on your NEW Replit BEFORE starting the app.
 *
 * Usage:
 *   node scripts/import_data.js
 *
 * Requirements:
 *   - data_snapshot.json must be in the project root
 *   - DATABASE_URL env var must be set (auto-configured by Replit)
 */

const { Pool } = require("pg");
const fs = require("fs");
const path = require("path");

const BOT_DIR = path.resolve(__dirname, "../bot");
const SNAPSHOT_PATH = path.resolve(__dirname, "../data_snapshot.json");

async function main() {
  console.log("=== OGM Checker Data Import ===\n");

  // Check snapshot file exists
  if (!fs.existsSync(SNAPSHOT_PATH)) {
    console.error("✗ data_snapshot.json not found in project root.");
    console.error("  Copy it from your old Replit first, then re-run this script.");
    process.exit(1);
  }

  const snapshot = JSON.parse(fs.readFileSync(SNAPSHOT_PATH, "utf-8"));
  console.log(`✓ Snapshot loaded — exported at: ${snapshot.exported_at}`);
  console.log(`  Files in snapshot: ${Object.keys(snapshot.files).length}\n`);

  const files = snapshot.files;

  // 1. Write all JSON files to the bot/ directory
  console.log("Writing local JSON files...");
  let written = 0;
  for (const [filename, data] of Object.entries(files)) {
    if (data === null || data === undefined) continue;
    const filePath = path.join(BOT_DIR, filename);
    const content = typeof data === "string" ? data : JSON.stringify(data, null, 2);
    fs.writeFileSync(filePath, content, "utf-8");
    written++;
  }
  console.log(`✓ Wrote ${written} files to bot/\n`);

  // 2. Populate PostgreSQL database
  if (!process.env.DATABASE_URL) {
    console.log("⚠ No DATABASE_URL — skipping database import.");
    console.log("  Local files have been written. The app will save them to DB on first start.");
  } else {
    const pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 2 });
    try {
      // Ensure table exists
      await pool.query(`
        CREATE TABLE IF NOT EXISTS bot_json_data (
          filename TEXT PRIMARY KEY,
          content TEXT NOT NULL,
          updated_at TIMESTAMP DEFAULT NOW()
        )
      `);

      console.log("Saving to PostgreSQL database...");
      let saved = 0;
      for (const [filename, data] of Object.entries(files)) {
        if (data === null || data === undefined) continue;
        const content = typeof data === "string" ? data : JSON.stringify(data, null, 2);
        await pool.query(
          `INSERT INTO bot_json_data (filename, content, updated_at)
           VALUES ($1, $2, NOW())
           ON CONFLICT (filename)
           DO UPDATE SET content = $2, updated_at = NOW()`,
          [filename, content]
        );
        saved++;
      }
      console.log(`✓ Saved ${saved} files to database`);
    } catch (e) {
      console.error("✗ Database import failed:", e.message);
      console.log("  Local files were still written. App will auto-save them on first start.");
    } finally {
      await pool.end();
    }
  }

  console.log("\n=== Import Complete ===");
  console.log("✓ You can now start the application normally.");
  console.log("  All your users, keys, tiers, and settings have been restored.\n");
}

main().catch((e) => {
  console.error("Import failed:", e.message);
  process.exit(1);
});
