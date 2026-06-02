import path from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";
import dotenv from "dotenv";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");

dotenv.config({ path: path.join(rootDir, ".env") });
dotenv.config({ path: path.join(rootDir, ".env.local"), override: true });

const client = new pg.Client({
  connectionString: process.env.DATABASE_URL,
  ssl: { rejectUnauthorized: false },
});

const filenames = [
  "users.json",
  "user_proxies.json",
  "saved_bins.json",
  "user_tiers.json",
  "premium.json",
  "skool_accounts.json",
];

await client.connect();
const result = await client.query(
  "select filename, content from bot_json_data where filename = any($1) order by filename",
  [filenames],
);
await client.end();

console.log(JSON.stringify(result.rows));
