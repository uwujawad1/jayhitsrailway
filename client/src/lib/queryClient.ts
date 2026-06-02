import { QueryClient, QueryFunction } from "@tanstack/react-query";

const configuredApiBaseUrl = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
const isPlaceholderApiBaseUrl = /your-.*backend|example\.com/i.test(configuredApiBaseUrl);
const useDirectApiBaseUrl = import.meta.env.VITE_API_DIRECT === "true";

function isLocalHostname(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function getApiBaseUrl(): string {
  if (typeof window !== "undefined" && isLocalHostname(window.location.hostname)) {
    return "";
  }

  if (isPlaceholderApiBaseUrl) {
    return "";
  }

  return useDirectApiBaseUrl ? configuredApiBaseUrl : "";
}

export function apiUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  const apiBaseUrl = getApiBaseUrl();
  return `${apiBaseUrl}${url.startsWith("/") ? url : `/${url}`}`;
}

async function readResponseError(res: Response) {
  const contentType = res.headers.get("content-type") || "";
  const fallback = res.statusText || "Request failed";

  if (contentType.includes("application/json")) {
    try {
      const data = await res.json();
      return data.error || data.message || JSON.stringify(data);
    } catch {
      return fallback;
    }
  }

  const text = await res.text();
  return text || fallback;
}

export async function getResponseErrorMessage(res: Response) {
  return readResponseError(res);
}

export async function throwIfResNotOk(res: Response) {
  if (!res.ok) {
    const text = await readResponseError(res);
    throw new Error(`${res.status}: ${text}`);
  }
}

export async function parseJsonResponse<T = any>(res: Response): Promise<T> {
  await throwIfResNotOk(res);
  return res.json();
}

export async function apiRequest(
  method: string,
  url: string,
  data?: unknown | undefined,
  signal?: AbortSignal,
): Promise<Response> {
  const res = await fetch(apiUrl(url), {
    method,
    headers: data ? { "Content-Type": "application/json" } : {},
    body: data ? JSON.stringify(data) : undefined,
    credentials: "include",
    signal,
  });

  await throwIfResNotOk(res);
  return res;
}

type UnauthorizedBehavior = "returnNull" | "throw";
export const getQueryFn: <T>(options: {
  on401: UnauthorizedBehavior;
}) => QueryFunction<T> =
  ({ on401: unauthorizedBehavior }) =>
  async ({ queryKey }) => {
    const res = await fetch(apiUrl(queryKey.join("/") as string), {
      credentials: "include",
    });

    if (unauthorizedBehavior === "returnNull" && res.status === 401) {
      return null;
    }

    await throwIfResNotOk(res);
    return await res.json();
  };

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      queryFn: getQueryFn({ on401: "throw" }),
      refetchInterval: false,
      refetchOnWindowFocus: false,
      staleTime: 0,
      retry: false,
    },
    mutations: {
      retry: false,
    },
  },
});
