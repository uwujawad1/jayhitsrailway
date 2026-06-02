import express, { type Request, Response, NextFunction } from "express";
import session from "express-session";
import connectPgSimple from "connect-pg-simple";
import MemoryStoreFactory from "memorystore";
import compression from "compression";
import pg from "pg";
import * as crypto from "crypto";
import dotenv from "dotenv";
import { registerRoutes } from "./routes";
import { serveStatic } from "./static";
import { createServer } from "http";
import { restoreJsonFiles, saveAllJsonFiles, startPeriodicSave } from "./json-persistence";
import { createPgPoolConfig } from "./pg-config";

dotenv.config({ path: ".env" });
dotenv.config({ path: ".env.local", override: true });

declare module "express-session" {
  interface SessionData {
    userId?: string;
    isAdmin?: boolean;
    adminPinVerified?: boolean;
    loggedInAt?: number;
    firstName?: string;
    lastName?: string;
    username?: string;
    photoUrl?: string;
  }
}

const app = express();
const httpServer = createServer(app);

declare module "http" {
  interface IncomingMessage {
    rawBody: unknown;
  }
}

app.use(compression());

app.use(
  express.json({
    verify: (req, _res, buf) => {
      req.rawBody = buf;
    },
  }),
);

app.use(express.urlencoded({ extended: false }));

const isProduction = process.env.NODE_ENV === "production";
app.set("trust proxy", 1);

const MemoryStore = MemoryStoreFactory(session);

async function createSessionStore(): Promise<session.Store> {
  if (!process.env.DATABASE_URL) {
    console.log("No DATABASE_URL set, using in-memory session store.");
    return new MemoryStore({ checkPeriod: 86400000 });
  }
  try {
    const testPool = new pg.Pool(createPgPoolConfig({
      connectionTimeoutMillis: 5000,
      max: 1,
    }));
    const client = await testPool.connect();
    client.release();
    await testPool.end();

    const PgSession = connectPgSimple(session);
    const sessionPool = new pg.Pool(createPgPoolConfig({
      connectionTimeoutMillis: 10000,
      max: 5,
    }));
    sessionPool.on("error", (err: any) => {
      console.error("Database pool error:", err.message);
    });
    console.log("Using PostgreSQL session store.");
    return new PgSession({
      pool: sessionPool,
      tableName: "user_sessions",
      createTableIfMissing: true,
    });
  } catch (err: any) {
    console.warn("Database unavailable, using in-memory session store:", err.message);
    return new MemoryStore({ checkPeriod: 86400000 });
  }
}

export function log(message: string, source = "express") {
  const formattedTime = new Date().toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });

  console.log(`${formattedTime} [${source}] ${message}`);
}

app.use((req, res, next) => {
  const start = Date.now();
  const path = req.path;
  let capturedJsonResponse: Record<string, any> | undefined = undefined;

  const originalResJson = res.json;
  res.json = function (bodyJson, ...args) {
    capturedJsonResponse = bodyJson;
    return originalResJson.apply(res, [bodyJson, ...args]);
  };

  res.on("finish", () => {
    const duration = Date.now() - start;
    if (path.startsWith("/api")) {
      let logLine = `${req.method} ${path} ${res.statusCode} in ${duration}ms`;
      if (capturedJsonResponse) {
        logLine += ` :: ${JSON.stringify(capturedJsonResponse)}`;
      }

      log(logLine);
    }
  });

  next();
});

(async () => {
  await restoreJsonFiles();
  startPeriodicSave(5 * 60 * 1000);

  const sessionStore = await createSessionStore();
  app.use(
    session({
      store: sessionStore,
      secret: process.env.SESSION_SECRET || (() => {
        const fallback = crypto.randomBytes(32).toString("hex");
        console.warn("WARNING: No SESSION_SECRET set. Using random secret (sessions won't persist across restarts).");
        return fallback;
      })(),
      resave: false,
      saveUninitialized: false,
      cookie: {
        secure: isProduction && process.env.DISABLE_SECURE_COOKIE !== "true",
        httpOnly: true,
        sameSite: "lax",
        maxAge: 7 * 24 * 60 * 60 * 1000,
      },
    }),
  );

  await registerRoutes(httpServer, app);

  app.use((err: any, _req: Request, res: Response, next: NextFunction) => {
    const status = err.status || err.statusCode || 500;
    const message = err.message || "Internal Server Error";

    console.error("Internal Server Error:", err);

    if (res.headersSent) {
      return next(err);
    }

    return res.status(status).json({ message });
  });

  // importantly only setup vite in development and after
  // setting up all the other routes so the catch-all route
  // doesn't interfere with the other routes
  if (process.env.NODE_ENV === "production") {
    serveStatic(app);
  } else {
    const { setupVite } = await import("./vite");
    await setupVite(httpServer, app);
  }

  const port = parseInt(process.env.PORT || "5000", 10);

  httpServer.on("error", (err: any) => {
    if (err.code === "EADDRINUSE") {
      log(`Port ${port} is in use, retrying in 3 seconds...`);
      setTimeout(() => {
        httpServer.close();
        httpServer.listen({ port, host: "0.0.0.0" }, () => {
          log(`serving on port ${port}`);
        });
      }, 3000);
    } else {
      console.error("Server error:", err);
      process.exit(1);
    }
  });

  process.on("SIGTERM", async () => {
    console.log("[server] SIGTERM received, saving data before shutdown...");
    await saveAllJsonFiles();
    process.exit(0);
  });
  process.on("SIGINT", async () => {
    console.log("[server] SIGINT received, saving data before shutdown...");
    await saveAllJsonFiles();
    process.exit(0);
  });

  if (typeof (globalThis as any).PhusionPassenger !== "undefined") {
    httpServer.listen("passenger", () => {
      log("serving via Passenger");
    });
  } else {
    httpServer.listen(
      {
        port,
        host: "0.0.0.0",
      },
      () => {
        log(`serving on port ${port}`);
      },
    );
  }
})();
