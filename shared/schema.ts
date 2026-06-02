import { pgTable, text, varchar, boolean, integer, timestamp } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod";
import { sql } from "drizzle-orm";

export const users = pgTable("users", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  username: text("username").notNull().unique(),
  password: text("password").notNull(),
});

export const insertUserSchema = createInsertSchema(users).pick({
  username: true,
  password: true,
});

export type InsertUser = z.infer<typeof insertUserSchema>;
export type User = typeof users.$inferSelect;

export const botUserSchema = z.object({
  id: z.string(),
  joinedAt: z.string().nullable(),
  isPremium: z.boolean(),
  premiumExpiry: z.string().nullable(),
  premiumDays: z.number().nullable(),
  isBanned: z.boolean(),
  bannedAt: z.string().nullable(),
  bannedBy: z.string().nullable(),
});

export type BotUser = z.infer<typeof botUserSchema>;

export const botStatusSchema = z.object({
  running: z.boolean(),
  pid: z.number().nullable(),
  uptime: z.number().nullable(),
  startedAt: z.string().nullable(),
});

export type BotStatus = z.infer<typeof botStatusSchema>;

export const botStatsSchema = z.object({
  totalUsers: z.number(),
  premiumUsers: z.number(),
  freeUsers: z.number(),
  bannedUsers: z.number(),
  totalGateways: z.number(),
  botRunning: z.boolean(),
});

export type BotStats = z.infer<typeof botStatsSchema>;

export const gatewaySchema = z.object({
  id: z.string(),
  name: z.string(),
  type: z.string(),
  category: z.string(),
  enabled: z.boolean(),
  premiumOnly: z.boolean(),
});

export type Gateway = z.infer<typeof gatewaySchema>;

export const botSettingsSchema = z.object({
  mass_check_enabled: z.boolean(),
  inline_mass_limit: z.number(),
  file_mass_limit: z.number(),
  gateway_settings: z.record(z.string(), z.object({
    enabled: z.boolean().optional(),
    premium_only: z.boolean().optional(),
  })).optional(),
  tool_settings: z.record(z.string(), z.object({
    enabled: z.boolean().optional(),
    premium_only: z.boolean().optional(),
  })).optional(),
});

export type BotSettings = z.infer<typeof botSettingsSchema>;

export const botLogSchema = z.object({
  timestamp: z.string(),
  message: z.string(),
  type: z.enum(["stdout", "stderr", "system"]),
});

export type BotLog = z.infer<typeof botLogSchema>;
