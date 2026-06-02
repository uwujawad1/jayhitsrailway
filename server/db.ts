import { drizzle } from "drizzle-orm/node-postgres";
import pg from "pg";
import * as schema from "@shared/schema";
import { createPgPoolConfig } from "./pg-config";

const pool = new pg.Pool(createPgPoolConfig());

export const db = drizzle(pool, { schema });
