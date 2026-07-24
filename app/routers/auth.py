"""Login-, Setup- und Logout-Routen (Benutzerkonten)."""
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

# Bremst Brute-Force auf Passwörter: max. 5 Versuche pro IP in 5 Minuten.
login_limiter = RateLimiter(max_attempts=5, window_seconds=300)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _login_response(user_id: int, redirect_to: str = "/") -> RedirectResponse:
    response = RedirectResponse(redirect_to, status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.create_session_token(user_id),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=get_settings().secure_cookies,
    )
    return response


@router.get("/setup")
def setup_page(request: Request, db: Session = Depends(get_db)):
    if auth.users_exist(db):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "setup.html", {"error": request.query_params.get("error")}
    )


@router.post("/setup")
def do_setup(
    db: Session = Depends(get_db),
    company: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    if auth.users_exist(db):
        return RedirectResponse("/login", status_code=303)
    if not company.strip():
        return RedirectResponse("/setup?error=Bitte einen Firmennamen angeben.", status_code=303)
    if len(password) < auth.MIN_PASSWORD_LENGTH:
        return RedirectResponse(
            f"/setup?error=Mindestens {auth.MIN_PASSWORD_LENGTH} Zeichen für das Passwort.",
            status_code=303,
        )
    if password != password2:
        return RedirectResponse(
            "/setup?error=Die Passwörter stimmen nicht überein.", status_code=303
        )
    from ..models import Organization

    org = Organization(name=company.strip())
    db.add(org)
    db.commit()
    try:
        user = auth.create_user(
            db, email=email, name=name, password=password,
            is_admin=True, is_owner=True, org_id=org.id,
        )
    except ValueError as exc:
        db.delete(org)
        db.commit()
        return RedirectResponse(f"/setup?error={exc}", status_code=303)
    return _login_response(user.id)


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    if not auth.users_exist(db):
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": request.query_params.get("error")}
    )


@router.post("/login")
def do_login(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
):
    ip = _client_ip(request)
    if not login_limiter.allow(ip):
        return RedirectResponse(
            "/login?error=Zu viele Fehlversuche. Bitte ein paar Minuten warten.",
            status_code=303,
        )
    user = auth.authenticate(db, email, password)
    if user is None:
        return RedirectResponse(
            "/login?error=E-Mail oder Passwort ist falsch.", status_code=303
        )
    login_limiter.reset(ip)
    return _login_response(user.id)


@router.post("/logout")
def do_logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME)
    return response
