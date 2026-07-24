"""FastAPI-Einstiegspunkt für Kiara."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse

from . import __version__, auth, autosync
from .database import SessionLocal, init_db
from .routers import api, web
from .routers import auth as auth_routes

logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).resolve().parent

# Ohne Anmeldung erreichbar: Login/Setup, statische Dateien, Health-Check.
PUBLIC_PATHS = {"/health", "/login", "/setup"}
PUBLIC_PREFIXES = ("/static/",)


class AuthMiddleware(BaseHTTPMiddleware):
    """Schützt alle Seiten und die API; prüft das Benutzerkonto pro Anfrage."""

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        token = request.cookies.get(auth.COOKIE_NAME)
        user_id = auth.verify_session_token(token) if token else None
        if user_id is not None:
            from .models import User

            with SessionLocal() as db:
                user = db.get(User, user_id)
                if user is not None and user.active:
                    request.state.user_id = user.id
                    request.state.user_name = user.name
                    request.state.is_admin = user.is_admin
                    return await call_next(request)

        if path.startswith("/api"):
            return JSONResponse({"detail": "Nicht angemeldet."}, status_code=401)

        with SessionLocal() as db:
            if not auth.users_exist(db):
                return RedirectResponse("/setup", status_code=303)
        return RedirectResponse("/login", status_code=303)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Alt-Installationen: Einzel-Passwort wird zum Benutzer "admin".
    with SessionLocal() as db:
        auth.migrate_legacy_password(db)
    stop_autosync = threading.Event()
    autosync.start(stop_autosync)
    yield
    stop_autosync.set()


app = FastAPI(title="Kiara – Belegarchiv", version=__version__, lifespan=lifespan)

app.add_middleware(AuthMiddleware)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(auth_routes.router)
app.include_router(web.router)
app.include_router(api.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
