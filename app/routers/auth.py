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
# "Passwort vergessen": max. 5 Mails pro IP in 15 Minuten.
forgot_limiter = RateLimiter(max_attempts=5, window_seconds=900)


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
        request,
        "login.html",
        {
            "error": request.query_params.get("error"),
            "msg": request.query_params.get("msg"),
        },
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


# ---------------------------------------------------------------------------
# Passwort vergessen (öffentlich, per E-Mail-Link)
# ---------------------------------------------------------------------------

# Immer dieselbe Antwort, egal ob die E-Mail existiert – so lässt sich nicht
# erraten, welche Adressen ein Konto haben.
_FORGOT_OK = (
    "Wenn es ein Konto mit dieser E-Mail-Adresse gibt, wurde soeben eine "
    "Nachricht mit einem Zurücksetz-Link verschickt (auch den Spam-Ordner prüfen)."
)


@router.get("/forgot")
def forgot_page(request: Request, db: Session = Depends(get_db)):
    from ..services import mailer

    return templates.TemplateResponse(
        request,
        "forgot.html",
        {
            "error": request.query_params.get("error"),
            "msg": request.query_params.get("msg"),
            "mail_ready": mailer.is_configured(db),
        },
    )


@router.post("/forgot")
def do_forgot(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
):
    from sqlalchemy import select

    from ..models import User
    from ..services import mailer

    if not forgot_limiter.allow(_client_ip(request)):
        return RedirectResponse(
            "/forgot?error=Zu viele Anfragen. Bitte ein paar Minuten warten.",
            status_code=303,
        )
    if not mailer.is_configured(db):
        return RedirectResponse(
            "/forgot?error=Der E-Mail-Versand ist noch nicht eingerichtet. "
            "Bitte wende dich an deinen Administrator.",
            status_code=303,
        )

    user = db.execute(
        select(User).where(User.email == auth.normalize_email(email))
    ).scalar_one_or_none()
    if user is not None and user.active and "@" in user.email:
        token = auth.create_reset_token(user)
        link = f"{str(request.base_url).rstrip('/')}/reset?token={token}"
        body = (
            f"Hallo {user.name},\n\n"
            "für dein Kiara-Konto wurde das Zurücksetzen des Passworts angefordert.\n"
            "Klicke auf diesen Link, um ein neues Passwort zu setzen "
            "(gültig für 1 Stunde):\n\n"
            f"{link}\n\n"
            "Wenn du das nicht warst, kannst du diese Nachricht ignorieren – "
            "dein Passwort bleibt unverändert.\n\n"
            "Kiara – Belegarchiv & Buchhaltungs-Gegenkontrolle"
        )
        try:
            mailer.send_mail(db, user.email, "Kiara: Passwort zurücksetzen", body)
        except RuntimeError:
            # Absichtlich dieselbe Antwort: kein Rückschluss auf Konten möglich.
            # Der eigentliche Fehler steht im Server-Log für den Administrator.
            pass
    return RedirectResponse(f"/forgot?msg={_FORGOT_OK}", status_code=303)


@router.get("/reset")
def reset_page(request: Request, db: Session = Depends(get_db), token: str = ""):
    user = auth.verify_reset_token(db, token)
    if user is None:
        return RedirectResponse(
            "/login?error=Der Zurücksetz-Link ist ungültig oder abgelaufen. "
            "Bitte unter 'Passwort vergessen?' einen neuen anfordern.",
            status_code=303,
        )
    return templates.TemplateResponse(
        request,
        "reset.html",
        {"token": token, "user": user, "error": request.query_params.get("error")},
    )


@router.post("/reset")
def do_reset(
    request: Request,
    db: Session = Depends(get_db),
    token: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    from urllib.parse import quote

    user = auth.verify_reset_token(db, token)
    if user is None:
        return RedirectResponse(
            "/login?error=Der Zurücksetz-Link ist ungültig oder abgelaufen. "
            "Bitte unter 'Passwort vergessen?' einen neuen anfordern.",
            status_code=303,
        )
    if len(password) < auth.MIN_PASSWORD_LENGTH:
        return RedirectResponse(
            f"/reset?token={quote(token)}&error=Mindestens "
            f"{auth.MIN_PASSWORD_LENGTH} Zeichen für das Passwort.",
            status_code=303,
        )
    if password != password2:
        return RedirectResponse(
            f"/reset?token={quote(token)}&error=Die Passwörter stimmen nicht überein.",
            status_code=303,
        )
    auth.set_password_for(db, user, password)
    return RedirectResponse(
        "/login?msg=Passwort geändert – du kannst dich jetzt anmelden.",
        status_code=303,
    )


@router.post("/logout")
def do_logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME)
    return response
