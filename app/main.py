"""FastAPI-Einstiegspunkt für Kiara."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse

from . import __version__, auth
from .database import SessionLocal, init_db
from .routers import api, web
from .routers import auth as auth_routes

logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).resolve().parent

# Ohne Anmeldung erreichbar: Login/Setup, statische Dateien, Health-Check.
PUBLIC_PATHS = {"/health", "/login", "/setup"}
PUBLIC_PREFIXES = ("/static/",)


class AuthMiddleware(BaseHTTPMiddleware):
    """Schützt alle Seiten und die API hinter dem App-Passwort."""

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        token = request.cookies.get(auth.COOKIE_NAME)
        if token and auth.verify_session_token(token):
            return await call_next(request)

        if path.startswith("/api"):
            return JSONResponse({"detail": "Nicht angemeldet."}, status_code=401)

        with SessionLocal() as db:
            if not auth.password_is_set(db):
                return RedirectResponse("/setup", status_code=303)
        return RedirectResponse("/login", status_code=303)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Kiara – Belegarchiv", version=__version__, lifespan=lifespan)

app.add_middleware(AuthMiddleware)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(auth_routes.router)
app.include_router(web.router)
app.include_router(api.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
