def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_stats_empty(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["accounts"] == 0
    assert data["attachments"] == 0


def test_create_and_list_account(client):
    resp = client.post(
        "/api/accounts",
        json={
            "name": "Buchhaltung GMX",
            "provider": "gmx",
            "username": "konto@gmx.de",
            "password": "geheim",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["host"] == "imap.gmx.net"  # Provider-Preset angewandt
    assert body["port"] == 993
    assert "password" not in body

    listing = client.get("/api/accounts").json()
    assert len(listing) == 1
    assert listing[0]["name"] == "Buchhaltung GMX"


def test_dashboard_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Übersicht" in resp.text


def test_reconcile_endpoint(client):
    resp = client.post("/api/reconcile")
    assert resp.status_code == 200
    assert "Zuordnungen" in resp.json()["message"]
