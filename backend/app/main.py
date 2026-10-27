from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from .api import router
from .auth import router as auth_router
from .config import get_settings
from .resilience import rate_limit_retry_after


settings = get_settings()
frontend_dist = Path(__file__).resolve().parents[2] / "dist"
logger = logging.getLogger("vision_ai")

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' https://cdn.jsdelivr.net",
    "worker-src 'self' blob:",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob: https://res.cloudinary.com",
    "media-src 'self' blob:",
    "connect-src 'self' https://cdn.jsdelivr.net https://tfhub.dev https://www.kaggle.com https://storage.googleapis.com",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def error_response(request: Request, status_code: int, detail: object, code: str, headers: dict | None = None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "code": code, "request_id": request_id},
        headers={**(headers or {}), "X-Request-ID": request_id},
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.1.0",
    description="Backend lưu lịch sử, bộ sưu tập và phản hồi cho ứng dụng Vision AI.",
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
app.include_router(router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return error_response(request, exc.status_code, exc.detail, f"http_{exc.status_code}", dict(exc.headers or {}))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(request, 422, exc.errors(), "validation_error")


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception("Database failure request_id=%s", getattr(request.state, "request_id", "unknown"), exc_info=exc)
    return error_response(request, 503, "Cơ sở dữ liệu tạm thời không phản hồi. Vui lòng thử lại.", "database_unavailable", {"Retry-After": "10"})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled failure request_id=%s", getattr(request.state, "request_id", "unknown"), exc_info=exc)
    return error_response(request, 500, "Máy chủ gặp lỗi ngoài dự kiến.", "internal_error")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    request.state.request_id = uuid4().hex
    retry_after = rate_limit_retry_after(request)
    if retry_after is not None:
        return error_response(
            request, 429, "Hệ thống đang nhận quá nhiều yêu cầu. Vui lòng thử lại sau.",
            "rate_limited", {"Retry-After": str(retry_after)},
        )
    method = request.method.upper()
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        session_cookie = request.cookies.get(settings.session_cookie_name)
        auth_header = request.headers.get("authorization", "")
        if session_cookie and not auth_header.startswith("Bearer "):
            exempt_paths = {
                f"{settings.api_prefix}/auth/login",
                f"{settings.api_prefix}/auth/register",
                f"{settings.api_prefix}/auth/forgot-password",
                f"{settings.api_prefix}/auth/reset-password",
                f"{settings.api_prefix}/auth/verify-email",
            }
            if request.url.path not in exempt_paths:
                cookie_csrf = request.cookies.get(settings.csrf_cookie_name)
                header_csrf = request.headers.get(settings.csrf_header_name) or request.headers.get("x-csrf-token")
                if not cookie_csrf or not header_csrf or not secrets.compare_digest(cookie_csrf, header_csrf):
                    return error_response(
                        request, 403, "CSRF token không hợp lệ hoặc bị thiếu. Vui lòng làm mới trang.",
                        "csrf_invalid",
                    )
    try:
        response = await asyncio.wait_for(call_next(request), timeout=settings.api_timeout_seconds)
    except TimeoutError:
        return error_response(
            request, 504, "Máy chủ xử lý quá thời gian cho phép. Vui lòng thử lại.",
            "request_timeout", {"Retry-After": "5"},
        )
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=()"
    if request.url.path.startswith(f"{settings.api_prefix}/auth"):
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path.endswith((".onnx", ".wasm")):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.url.path.startswith("/vendor/"):
        response.headers["Cache-Control"] = "public, max-age=2592000"
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").startswith("https"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if method == "GET" and settings.csrf_cookie_name not in request.cookies:
        response.set_cookie(
            key=settings.csrf_cookie_name,
            value=secrets.token_urlsafe(32),
            httponly=False,
            secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").startswith("https"),
            samesite="lax",
            path="/",
        )
    return response

if (frontend_dist.is_dir()):
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="frontend-assets")
    if (frontend_dist / "vendor").is_dir():
        app.mount("/vendor", StaticFiles(directory=frontend_dist / "vendor"), name="frontend-vendor")


@app.get("/style.css", include_in_schema=False)
def frontend_styles() -> FileResponse:
    return FileResponse(frontend_dist / "style.css", media_type="text/css")


@app.get("/script.js", include_in_schema=False)
def frontend_script() -> FileResponse:
    return FileResponse(frontend_dist / "script.js", media_type="application/javascript")


@app.get("/yolo-runtime.js", include_in_schema=False)
def frontend_yolo_runtime() -> FileResponse:
    return FileResponse(frontend_dist / "yolo-runtime.js", media_type="application/javascript")


@app.get("/manifest.webmanifest", include_in_schema=False)
def frontend_manifest() -> FileResponse:
    return FileResponse(frontend_dist / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def frontend_service_worker() -> FileResponse:
    return FileResponse(
        frontend_dist / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/favicon.ico", include_in_schema=False)
def frontend_favicon() -> FileResponse:
    return FileResponse(frontend_dist / "assets" / "icons" / "icon-192.png", media_type="image/png")


@app.get("/", include_in_schema=False)
def root():
    index = frontend_dist / "index.html"
    if index.is_file():
        return FileResponse(index, media_type="text/html")
    return {"name": settings.app_name, "docs": "/docs", "health": f"{settings.api_prefix}/health"}
