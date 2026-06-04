from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import os

logger = logging.getLogger(__name__)


def get_real_ip(request: Request) -> str:
    """Citeste IP-ul real al clientului, inclusiv prin Cloudflare/proxy."""
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=get_real_ip, default_limits=["200/minute"])

ENV = os.getenv("ENVIRONMENT", "development")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(self), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com; "
            "img-src 'self' data: https://*.tile.openstreetmap.org https://nominatim.openstreetmap.org; "
            "connect-src 'self' https://nominatim.openstreetmap.org; "
            "font-src 'self' data:; "
            "frame-ancestors 'none';"
        )
        if ENV == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if response.status_code in (401, 403, 429):
            ip = get_remote_address(request)
            # Maschează token-urile din query string în loguri
            path = request.url.path
            logger.warning(f"[SECURITY] {response.status_code} | {request.method} {path} | IP: {ip}")
        return response


def eroare_rate_limit(request: Request, exc):
    ip = get_remote_address(request)
    logger.warning(f"[RATE LIMIT] IP blocat: {ip} | {request.url.path}")
    return JSONResponse(
        status_code=429,
        content={"detail": "Prea multe cereri. Încearcă din nou peste un minut."}
    )


MAGIC_BYTES = [
    b"%PDF",           # PDF
    b"\xd0\xcf\x11\xe0",  # DOC (OLE2)
    b"PK\x03\x04",    # DOCX (ZIP-based)
]

def verifica_tip_fisier(continut: bytes) -> bool:
    for magic in MAGIC_BYTES:
        if continut.startswith(magic):
            return True
    return False
