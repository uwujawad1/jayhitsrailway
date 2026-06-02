type VercelRequest = {
  method?: string;
  headers: Record<string, string | string[] | undefined>;
  query: Record<string, string | string[] | undefined>;
  body?: unknown;
};

type VercelResponse = {
  status: (statusCode: number) => VercelResponse;
  json: (body: unknown) => void;
  setHeader: (name: string, value: string) => void;
  send: (body: Buffer) => void;
};

const configuredBackendUrl = (
  process.env.BACKEND_API_URL ||
  process.env.VITE_API_URL ||
  ""
).replace(/\/$/, "");

const isPlaceholderBackendUrl = /your-.*backend|example\.com/i.test(configuredBackendUrl);

function getBackendUrl() {
  if (!configuredBackendUrl || isPlaceholderBackendUrl) return null;
  return configuredBackendUrl;
}

function getForwardPath(path: string | string[] | undefined) {
  const parts = Array.isArray(path) ? path : path ? path.split("/") : [];
  return parts.map((part) => encodeURIComponent(part)).join("/");
}

function getRequestBody(req: VercelRequest) {
  if (req.method === "GET" || req.method === "HEAD") return undefined;
  if (req.body === undefined || req.body === null) return undefined;
  if (Buffer.isBuffer(req.body)) return req.body;
  if (typeof req.body === "string") return req.body;
  return JSON.stringify(req.body);
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const backendUrl = getBackendUrl();
  if (!backendUrl) {
    return res.status(502).json({
      error: "Backend API URL is not configured. Set BACKEND_API_URL or VITE_API_URL in Vercel.",
    });
  }

  const forwardPath = getForwardPath(req.query.path as string | string[] | undefined);
  const url = new URL(`/api/${forwardPath}`, backendUrl);

  for (const [key, value] of Object.entries(req.query)) {
    if (key === "path") continue;
    if (Array.isArray(value)) {
      for (const item of value) url.searchParams.append(key, item);
    } else if (value !== undefined) {
      url.searchParams.set(key, value);
    }
  }

  const headers = new Headers();
  for (const [key, value] of Object.entries(req.headers)) {
    if (!value) continue;
    const lower = key.toLowerCase();
    if (["host", "content-length", "connection", "accept-encoding"].includes(lower)) continue;
    headers.set(key, Array.isArray(value) ? value.join(",") : value);
  }

  const response = await fetch(url, {
    method: req.method,
    headers,
    body: getRequestBody(req),
    redirect: "manual",
  });

  res.status(response.status);
  response.headers.forEach((value, key) => {
    if (["content-encoding", "content-length"].includes(key.toLowerCase())) return;
    res.setHeader(key, value);
  });

  const body = Buffer.from(await response.arrayBuffer());
  return res.send(body);
}
