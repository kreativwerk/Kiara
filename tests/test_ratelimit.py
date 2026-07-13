"""Tests für Rate-Limiting (Unit + Login-Integration)."""
from app.ratelimit import RateLimiter

from tests.conftest import TEST_PASSWORD


def test_limiter_blocks_after_max_attempts():
    limiter = RateLimiter(max_attempts=3, window_seconds=60)
    assert limiter.allow("ip1", now=0.0)
    assert limiter.allow("ip1", now=1.0)
    assert limiter.allow("ip1", now=2.0)
    assert not limiter.allow("ip1", now=3.0)
    # Andere Schlüssel sind unabhängig.
    assert limiter.allow("ip2", now=3.0)


def test_limiter_window_expires():
    limiter = RateLimiter(max_attempts=2, window_seconds=10)
    assert limiter.allow("ip", now=0.0)
    assert limiter.allow("ip", now=1.0)
    assert not limiter.allow("ip", now=5.0)
    # Nach Ablauf des Fensters wieder erlaubt.
    assert limiter.allow("ip", now=20.0)


def test_limiter_reset():
    limiter = RateLimiter(max_attempts=1, window_seconds=60)
    assert limiter.allow("ip", now=0.0)
    assert not limiter.allow("ip", now=1.0)
    limiter.reset("ip")
    assert limiter.allow("ip", now=2.0)


def test_login_rate_limited(client):
    client.cookies.clear()
    # 5 Fehlversuche verbrauchen das Limit ...
    for _ in range(5):
        resp = client.post(
            "/login", data={"password": "falsch"}, follow_redirects=False
        )
        assert "Falsches" in resp.headers["location"]
    # ... der 6. wird geblockt, selbst mit korrektem Passwort.
    resp = client.post(
        "/login", data={"password": TEST_PASSWORD}, follow_redirects=False
    )
    assert "Fehlversuche" in resp.headers["location"]
    assert client.get("/api/stats").status_code == 401
