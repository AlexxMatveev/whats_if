import os
import secrets
from urllib.parse import urlparse
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


API_KEY = os.getenv("API_KEY", "").strip()


def _ensure_key():
    global API_KEY
    if not API_KEY:
        API_KEY = secrets.token_urlsafe(24)
        print(f"[auth] No API_KEY set. Generated dev key: {API_KEY}")


_ensure_key()


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow GET, OPTIONS, static files, docs
        if (
            request.method in ("GET", "OPTIONS")
            or path.startswith("/static/")
            or path.startswith("/docs")
            or path.startswith("/openapi.json")
            or path == "/"
        ):
            return await call_next(request)

        # Allow same-origin requests from the browser UI
        origin = request.headers.get("Origin", "")
        referer = request.headers.get("Referer", "")
        server_host = f"{request.url.scheme}://{request.url.netloc}"
        if origin == server_host or referer.startswith(server_host + "/"):
            return await call_next(request)

        # Require API key for external/programmatic requests
        key = request.headers.get("X-API-Key", "")
        if key != API_KEY:
            raise HTTPException(status_code=403, detail="Forbidden: invalid or missing API key")

        return await call_next(request)
