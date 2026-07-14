"""Login-, Setup- und Logout-Routen."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import auth
from ..config import get_settings
from ..database import get_db
from ..ratelimit import RateLimiter
from ..templating import templates

router = APIRouter()

# Bremst Brute-Force auf das App-Passwort: max. 5 Versuche pro IP in 5 Minuten.
login_limiter = RateLimiter(max_attempts=5, window_seconds=300)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _login_response(redirect_to: str = "/") -> RedirectResponse:
    response = RedirectResponse(redirect_to, status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.create_session_token(),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=get_settings().secure_cookies,
    )
    return response


@router.get("/setup")
def setup_page(request: Request, db: Session = Depends(get_db)):
    if auth.password_is_set(db):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "setup.html", {"error": request.query_params.get("error")}
    )


@router.post("/setup")
def do_setup(
    db: Session = Depends(get_db),
    password: str = Form(...),
    password2: str = Form(...),
):
    if auth.password_is_set(db):
        return RedirectResponse("/login", status_code=303)
    if len(password) < auth.MIN_PASSWORD_LENGTH:
        return RedirectResponse(
            f"/setup?error=Mindestens {auth.MIN_PASSWORD_LENGTH} Zeichen.", status_code=303
        )
    if password != password2:
        return RedirectResponse(
            "/setup?error=Die Passwörter stimmen nicht überein.", status_code=303
        )
    auth.set_password(db, password)
    return _login_response("/")


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    if not auth.password_is_set(db):
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": request.query_params.get("error")}
    )


@router.post("/login")
def do_login(request: Request, db: Session = Depends(get_db), password: str = Form(...)):
    ip = _client_ip(request)
    if not login_limiter.allow(ip):
        return RedirectResponse(
            "/login?error=Zu viele Fehlversuche. Bitte ein paar Minuten warten.",
            status_code=303,
        )
    if not auth.check_password(db, password):
        return RedirectResponse("/login?error=Falsches Passwort.", status_code=303)
    login_limiter.reset(ip)
    return _login_response("/")


@router.post("/logout")
def do_logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME)
    return response
