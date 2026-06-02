import asyncio
import os
import signal
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(".env")
load_dotenv(".env.local", override=True)

LEGACY_PORT = int(os.getenv("LEGACY_EXPRESS_PORT", "5010"))
LEGACY_URL = f"http://127.0.0.1:{LEGACY_PORT}"
legacy_process: asyncio.subprocess.Process | None = None


async def start_legacy_express() -> asyncio.subprocess.Process:
    env = os.environ.copy()
    env["PORT"] = str(LEGACY_PORT)
    env["NODE_ENV"] = "production"
    return await asyncio.create_subprocess_exec(
        "node",
        "dist/index.cjs",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )


async def stream_legacy_logs(process: asyncio.subprocess.Process):
    if not process.stdout:
        return
    while True:
        line = await process.stdout.readline()
        if not line:
            return
        print(f"[express] {line.decode(errors='replace').rstrip()}", flush=True)


async def wait_for_legacy():
    async with httpx.AsyncClient(timeout=2) as client:
        for _ in range(60):
            try:
                await client.get(f"{LEGACY_URL}/api/healthz")
                return
            except Exception:
                await asyncio.sleep(0.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global legacy_process
    legacy_process = await start_legacy_express()
    asyncio.create_task(stream_legacy_logs(legacy_process))
    await wait_for_legacy()
    yield
    if legacy_process and legacy_process.returncode is None:
        legacy_process.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(legacy_process.wait(), timeout=10)
        except asyncio.TimeoutError:
            legacy_process.kill()


app = FastAPI(title="JayHits Backend", lifespan=lifespan)

allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health")
async def health():
    return {"ok": True, "service": "jayhits-fastapi"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_to_legacy(path: str, request: Request):
    url = f"{LEGACY_URL}/{path}"
    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length"}
    }
    async with httpx.AsyncClient(follow_redirects=False, timeout=None) as client:
        proxied = await client.request(
            request.method,
            url,
            params=request.query_params,
            headers=headers,
            content=body,
        )
    response_headers = {
        key: value
        for key, value in proxied.headers.items()
        if key.lower() not in {"content-encoding", "transfer-encoding", "connection"}
    }
    return Response(
        content=proxied.content,
        status_code=proxied.status_code,
        headers=response_headers,
        media_type=proxied.headers.get("content-type"),
    )
