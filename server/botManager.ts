import { spawn, ChildProcess } from "child_process";
import * as fs from "fs";
import * as path from "path";
import { log } from "./index";
import { saveAllJsonFiles } from "./json-persistence";
import { getConfigValue, readRuntimeSettings, updateRuntimeSettings } from "./env-config";

interface BotLog {
  timestamp: string;
  message: string;
  type: "stdout" | "stderr" | "system";
}

const MAX_LOGS = 500;

class BotManager {
  private process: ChildProcess | null = null;
  private logs: BotLog[] = [];
  private startedAt: Date | null = null;
  private botDir: string;
  private botScript: string;
  private autoRestart: boolean = true;
  private restartCount: number = 0;
  private lastRestartTime: number = 0;
  private maxRestartsPerMinute: number = 3;
  private manualStop: boolean = false;

  constructor() {
    this.botDir = path.resolve(process.cwd(), "bot");
    this.botScript = path.join(this.botDir, "bot.py");
  }

  private addLog(message: string, type: BotLog["type"]) {
    this.logs.push({
      timestamp: new Date().toISOString(),
      message: message.trim(),
      type,
    });
    if (this.logs.length > MAX_LOGS) {
      this.logs = this.logs.slice(-MAX_LOGS);
    }
  }

  isRunning(): boolean {
    return this.process !== null && this.process.exitCode === null;
  }

  getStatus() {
    const running = this.isRunning();
    const { botToken, apiId, apiHash } = this.getBotEnvConfig();
    const webhookOnlyMode = !!botToken && !apiId && !apiHash;
    return {
      running,
      pid: running ? this.process?.pid ?? null : null,
      uptime: running && this.startedAt
        ? (Date.now() - this.startedAt.getTime()) / 1000
        : null,
      startedAt: this.startedAt?.toISOString() ?? null,
      webhookOnlyMode,
    };
  }

  getLogs(): BotLog[] {
    return [...this.logs];
  }

  clearLogs() {
    this.logs = [];
  }

  async start(): Promise<{ success: boolean; message: string }> {
    if (this.isRunning()) {
      return { success: false, message: "Bot is already running" };
    }

    if (!fs.existsSync(this.botScript)) {
      return { success: false, message: "Bot script not found at " + this.botScript };
    }

    const { botToken, apiId, apiHash } = this.getBotEnvConfig();
    if (botToken && !apiId && !apiHash) {
      const message =
        "Webhook mode is enabled. The legacy Python Telegram client does not need to run.";
      this.addLog(message, "system");
      return { success: false, message };
    }

    try {
      this.manualStop = false;
      this.addLog("Starting bot process...", "system");

      this.process = spawn("python3", ["-u", this.botScript], {
        cwd: this.botDir,
        env: this.getBotProcessEnv(),
        stdio: ["ignore", "pipe", "pipe"],
      });

      this.startedAt = new Date();

      this.process.stdout?.on("data", (data: Buffer) => {
        const lines = data.toString().split("\n").filter((l) => l.trim());
        for (const line of lines) {
          this.addLog(line, "stdout");
        }
      });

      this.process.stderr?.on("data", (data: Buffer) => {
        const lines = data.toString().split("\n").filter((l) => l.trim());
        for (const line of lines) {
          this.addLog(line, "stderr");
        }
      });

      this.process.on("exit", (code, signal) => {
        this.addLog(
          `Bot process exited with code ${code}${signal ? `, signal ${signal}` : ""}`,
          "system"
        );
        this.process = null;
        this.startedAt = null;

        if (!this.manualStop && this.autoRestart) {
          const now = Date.now();
          if (now - this.lastRestartTime > 120000) {
            this.restartCount = 0;
          }

          if (this.restartCount < this.maxRestartsPerMinute) {
            this.restartCount++;
            this.lastRestartTime = now;
            const delay = Math.min(5000 * this.restartCount, 30000);
            this.addLog(
              `Auto-restarting bot in ${delay / 1000}s (attempt ${this.restartCount})...`,
              "system"
            );
            setTimeout(() => {
              if (!this.isRunning() && !this.manualStop) {
                this.start().then((result) => {
                  if (result.success) {
                    this.restartCount = 0;
                  }
                  this.addLog(
                    `Auto-restart: ${result.message}`,
                    "system"
                  );
                });
              }
            }, delay);
          } else {
            this.addLog(
              "Auto-restart limit reached. Waiting 2 minutes before allowing retries...",
              "system"
            );
            setTimeout(() => {
              this.restartCount = 0;
              if (!this.isRunning() && !this.manualStop) {
                this.addLog("Retry window reset. Attempting restart...", "system");
                this.start().then((result) => {
                  this.addLog(`Auto-restart: ${result.message}`, "system");
                });
              }
            }, 120000);
          }
        }
      });

      this.process.on("error", (err) => {
        this.addLog(`Bot process error: ${err.message}`, "system");
        this.process = null;
      });

      log("Bot process started with PID: " + this.process.pid, "bot-manager");
      return { success: true, message: "Bot started successfully" };
    } catch (err: any) {
      this.addLog(`Failed to start bot: ${err.message}`, "system");
      return { success: false, message: err.message };
    }
  }

  async stop(): Promise<{ success: boolean; message: string }> {
    if (!this.isRunning() || !this.process) {
      return { success: false, message: "Bot is not running" };
    }

    try {
      this.manualStop = true;
      this.addLog("Stopping bot process...", "system");
      this.process.kill("SIGTERM");

      await new Promise<void>((resolve) => {
        const timeout = setTimeout(() => {
          if (this.process && this.process.exitCode === null) {
            this.process.kill("SIGKILL");
          }
          resolve();
        }, 5000);

        this.process?.on("exit", () => {
          clearTimeout(timeout);
          resolve();
        });
      });

      this.process = null;
      this.startedAt = null;
      log("Bot process stopped", "bot-manager");
      return { success: true, message: "Bot stopped successfully" };
    } catch (err: any) {
      return { success: false, message: err.message };
    }
  }

  async restart(): Promise<{ success: boolean; message: string }> {
    if (this.isRunning()) {
      await this.stop();
    }
    await new Promise((r) => setTimeout(r, 1000));
    return this.start();
  }

  async getUsers() {
    const usersData = this.loadJsonFile("users.json");
    const premiumData = this.loadJsonFile("premium.json");
    const bannedData = this.loadJsonFile("banned_users.json");
    const tiersData = this.loadJsonFile("user_tiers.json");

    const allUserIds = new Set<string>();
    Object.keys(usersData).forEach((id) => allUserIds.add(id));
    Object.keys(premiumData).forEach((id) => allUserIds.add(id));
    Object.keys(bannedData).forEach((id) => allUserIds.add(id));
    Object.keys(tiersData).forEach((id) => allUserIds.add(id));

    const users = Array.from(allUserIds).map((id) => {
      const userData = usersData[id] || {};
      const premiumInfo = premiumData[id] || null;
      const bannedInfo = bannedData[id] || null;
      const tierInfo = tiersData[id] || null;

      let hasActivePremium = false;
      if (premiumInfo) {
        const expiry = new Date(premiumInfo.expiry);
        hasActivePremium = expiry > new Date();
      }

      let activeTier = "free";
      if (this.isAdminId(id)) {
        activeTier = "gold";
      } else if (tierInfo?.tier) {
        const expiry = tierInfo.expiresAt ? new Date(tierInfo.expiresAt).getTime() : null;
        if (!expiry || Date.now() <= expiry) {
          activeTier = tierInfo.tier;
        }
      }

      const isPremium = hasActivePremium || activeTier !== "free";

      return {
        id,
        joinedAt: userData.joined_at || tierInfo?.assignedAt || premiumInfo?.added_at || null,
        isPremium,
        premiumExpiry: premiumInfo?.expiry || null,
        premiumDays: premiumInfo?.days || null,
        isBanned: !!bannedInfo,
        bannedAt: bannedInfo?.banned_at || null,
        bannedBy: bannedInfo?.banned_by || null,
      };
    });

    return users;
  }

  async getStats() {
    const users = await this.getUsers();
    return {
      totalUsers: users.length,
      premiumUsers: users.filter((u) => u.isPremium).length,
      freeUsers: users.filter((u) => !u.isPremium && !u.isBanned).length,
      bannedUsers: users.filter((u) => u.isBanned).length,
      totalGateways: this.getGateways().length,
      botRunning: this.isRunning(),
    };
  }

  private static GATEWAY_REGISTRY: Record<string, { label: string; gates: Record<string, { name: string; type: string }> }> = {
    auth: {
      label: "Auth Gateways",
      gates: {
        st: { name: "Stripe Auth $0", type: "auth" },
        skl: { name: "Stripe Auth $0.1", type: "auth" },
        b3: { name: "Braintree Auth", type: "auth" },
        vbv: { name: "VBV Lookup", type: "auth" },
        an: { name: "Authorize.net Auth", type: "auth" },
        skb: { name: "SK Base Auth $0", type: "auth" },
        adn: { name: "Adyen Auth", type: "auth" },
        rbc: { name: "Stripe Auth $0 (RBC)", type: "auth" },
      },
    },
    charge: {
      label: "Charge Gateways",
      gates: {
        cw: { name: "Stripe Charge $6", type: "charge" },
        rz: { name: "Razorpay Charge", type: "charge" },
        charge: { name: "Stripe Charge SK", type: "charge" },
        pp: { name: "PayPal Charge $0.01", type: "charge" },
        shp: { name: "Shopify Native", type: "charge" },
        skl1: { name: "Stripe Charge $1", type: "charge" },
        skl2: { name: "Stripe Charge $7", type: "charge" },
        b3c: { name: "Braintree Charge", type: "charge" },
        ppn: { name: "PayPal Charge $1", type: "charge" },
        bnc: { name: "PayPal Charge $1 (BNC)", type: "charge" },
        ch: { name: "Stripe Charge €5", type: "charge" },
        isp: { name: "Stripe Charge $25", type: "charge" },
        auto: { name: "Stripe Random Charge", type: "charge" },
        azz: { name: "Authorize.net Charge $1", type: "charge" },
        ppk: { name: "PayPal Keybase $1", type: "charge" },
      },
    },
  };

  private static TOOL_REGISTRY: Record<string, { name: string; category: string }> = {
    gen: { name: "CC Generator", category: "tools" },
    bin: { name: "BIN Lookup", category: "tools" },
    sk: { name: "SK Key Checker", category: "tools" },
    skc: { name: "SK Charge Checker", category: "tools" },
    rand: { name: "Fake Address Generator", category: "tools" },
    id: { name: "User ID Lookup", category: "tools" },
    findsite: { name: "Site Finder", category: "tools" },
    co: { name: "Shopify Checker", category: "tools" },
    chk: { name: "Card Checker", category: "tools" },
    fl: { name: "Card Filter", category: "tools" },
    acc_crunchyroll: { name: "Crunchyroll Checker", category: "account_checkers" },
    acc_xbox: { name: "Xbox Checker", category: "account_checkers" },
    acc_cyberghost: { name: "CyberGhost Checker", category: "account_checkers" },
    acc_duolingo: { name: "Duolingo Checker", category: "account_checkers" },
    acc_hoichoi: { name: "Hoichoi Checker", category: "account_checkers" },
    sk_scraper_checker: { name: "SK Scraper Checker", category: "tools" },
  };

  getGateways() {
    const settings = this.getBotSettings();
    const gateways: any[] = [];
    for (const [catKey, catData] of Object.entries(BotManager.GATEWAY_REGISTRY)) {
      for (const [alias, gate] of Object.entries(catData.gates)) {
        const gs = settings.gateway_settings?.[alias];
        gateways.push({
          id: alias,
          name: gate.name,
          type: gate.type,
          category: catKey,
          enabled: gs?.enabled !== undefined ? gs.enabled : true,
          premiumOnly: gs?.premium_only !== undefined ? gs.premium_only : false,
        });
      }
    }
    return gateways;
  }

  getTools() {
    const settings = this.getBotSettings();
    const tools: any[] = [];
    for (const [id, tool] of Object.entries(BotManager.TOOL_REGISTRY)) {
      const ts = settings.tool_settings?.[id];
      tools.push({
        id,
        name: tool.name,
        category: tool.category,
        enabled: ts?.enabled !== undefined ? ts.enabled : true,
        premiumOnly: ts?.premium_only !== undefined ? ts.premium_only : false,
      });
    }
    return tools;
  }

  getBotSettings(): Record<string, any> {
    const settingsPath = path.join(this.botDir, "bot_settings.json");
    try {
      if (!fs.existsSync(settingsPath)) return { mass_check_enabled: true, inline_mass_limit: 10, file_mass_limit: 300, gateway_settings: {}, tool_settings: {} };
      const content = fs.readFileSync(settingsPath, "utf-8");
      if (!content.trim()) return { mass_check_enabled: true, inline_mass_limit: 10, file_mass_limit: 300, gateway_settings: {}, tool_settings: {} };
      return JSON.parse(content);
    } catch {
      return { mass_check_enabled: true, inline_mass_limit: 10, file_mass_limit: 300, gateway_settings: {}, tool_settings: {} };
    }
  }

  saveBotSettings(settings: Record<string, any>) {
    const settingsPath = path.join(this.botDir, "bot_settings.json");
    fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2), "utf-8");
    saveAllJsonFiles().catch(() => {});
  }

  updateGatewaySettings(gatewayId: string, updates: { enabled?: boolean; premium_only?: boolean }) {
    const settings = this.getBotSettings();
    if (!settings.gateway_settings) settings.gateway_settings = {};
    if (!settings.gateway_settings[gatewayId]) settings.gateway_settings[gatewayId] = {};
    if (updates.enabled !== undefined) settings.gateway_settings[gatewayId].enabled = updates.enabled;
    if (updates.premium_only !== undefined) settings.gateway_settings[gatewayId].premium_only = updates.premium_only;
    this.saveBotSettings(settings);
  }

  updateToolSettings(toolId: string, updates: { enabled?: boolean; premium_only?: boolean }) {
    const settings = this.getBotSettings();
    if (!settings.tool_settings) settings.tool_settings = {};
    if (!settings.tool_settings[toolId]) settings.tool_settings[toolId] = {};
    if (updates.enabled !== undefined) settings.tool_settings[toolId].enabled = updates.enabled;
    if (updates.premium_only !== undefined) settings.tool_settings[toolId].premium_only = updates.premium_only;
    this.saveBotSettings(settings);
  }

  getConfig(): Record<string, string> {
    return readRuntimeSettings();
  }

  saveConfig(config: Record<string, string>) {
    updateRuntimeSettings(config);
    saveAllJsonFiles().catch(() => {});
  }

  getBotEnvConfig() {
    return {
      botToken: getConfigValue("TELEGRAM_BOT_TOKEN"),
      apiId: getConfigValue("TELEGRAM_API_ID"),
      apiHash: getConfigValue("TELEGRAM_API_HASH"),
      adminId: getConfigValue("TELEGRAM_ADMIN_ID"),
      groupId: getConfigValue("TELEGRAM_GROUP_ID"),
      groupLink: getConfigValue("TELEGRAM_GROUP_LINK"),
      channelLink: getConfigValue("TELEGRAM_CHANNEL_LINK"),
    };
  }

  updateBotEnvConfig(updates: Record<string, string>) {
    const config = this.getConfig();
    for (const [key, value] of Object.entries(updates)) {
      if (value !== undefined && value !== null) {
        config[key] = value;
      }
    }
    this.saveConfig(config);
  }

  private getBotProcessEnv(): Record<string, string> {
    return {
      ...process.env as Record<string, string>,
      PYTHONUNBUFFERED: "1",
      TELEGRAM_BOT_TOKEN: getConfigValue("TELEGRAM_BOT_TOKEN"),
      TELEGRAM_API_ID: getConfigValue("TELEGRAM_API_ID"),
      TELEGRAM_API_HASH: getConfigValue("TELEGRAM_API_HASH"),
      TELEGRAM_ADMIN_ID: getConfigValue("TELEGRAM_ADMIN_ID"),
      TELEGRAM_GROUP_ID: getConfigValue("TELEGRAM_GROUP_ID"),
      TELEGRAM_GROUP_LINK: getConfigValue("TELEGRAM_GROUP_LINK"),
      TELEGRAM_CHANNEL_LINK: getConfigValue("TELEGRAM_CHANNEL_LINK"),
    };
  }

  private loadJsonFile(filename: string): Record<string, any> {
    const filepath = path.join(this.botDir, filename);
    try {
      if (!fs.existsSync(filepath)) return {};
      const content = fs.readFileSync(filepath, "utf-8");
      if (!content.trim()) return {};
      return JSON.parse(content);
    } catch {
      return {};
    }
  }

  private isAdminId(userId: string): boolean {
    const adminIds = (this.getBotEnvConfig().adminId || "")
      .split(",")
      .map((id) => id.trim())
      .filter(Boolean);
    return adminIds.includes(userId);
  }
}

export const botManager = new BotManager();
