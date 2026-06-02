import pg from "pg";

function shouldUseSsl(connectionString: string): boolean {
  try {
    const parsed = new URL(connectionString);
    const host = parsed.hostname.toLowerCase();
    if (host === "localhost" || host === "127.0.0.1") return false;
  } catch {
    return true;
  }
  return process.env.PGSSLMODE !== "disable";
}

export function createPgPoolConfig(overrides: Partial<pg.PoolConfig> = {}): pg.PoolConfig {
  const connectionString = process.env.DATABASE_URL || "";
  const ssl = shouldUseSsl(connectionString) ? { rejectUnauthorized: false } : undefined;

  return {
    connectionString,
    ...(ssl ? { ssl } : {}),
    ...overrides,
  };
}
