from app import settings_store as store


def test_value_roundtrip(db):
    store.set_value(db, "foo", "bar")
    assert store.get(db, "foo") == "bar"
    assert store.get(db, "missing", "default") == "default"


def test_bool_roundtrip(db):
    store.set_bool(db, "flag", True)
    assert store.get_bool(db, "flag") is True
    store.set_bool(db, "flag", False)
    assert store.get_bool(db, "flag") is False
    assert store.get_bool(db, "unknown", default=True) is True


def test_secret_is_encrypted(db):
    store.set_secret(db, "token", "s3cr3t")
    # Roundtrip liefert Klartext ...
    assert store.get_secret(db, "token") == "s3cr3t"
    # ... aber der Rohwert in der DB ist verschlüsselt.
    raw = store.get(db, "token")
    assert raw is not None and raw != "s3cr3t"


def test_delete(db):
    store.set_value(db, "temp", "x")
    store.delete(db, "temp")
    assert store.get(db, "temp") is None
