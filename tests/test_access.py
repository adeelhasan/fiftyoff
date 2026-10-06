"""Cloudflare Access (D37): token verification with locally generated keys, roles, and the gate.
No network: the key fetch is a stub (the socket guard stays on)."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from fiftyoff.access import HEADER, REFETCH_SECONDS, RETRY_SECONDS, AccessVerifier, user_change
from fiftyoff.api import create_app
from tests.test_api import gone_rows, rows, status_stub

TEAM, AUD = "fiftyoff-test", "aud-123"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk(key, kid):
    return {**jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True), "kid": kid, "alg": "RS256"}


class Certs:
    def __init__(self, *keys):
        self.keys, self.calls = list(keys), 0

    def __call__(self, team):
        assert team == TEAM
        self.calls += 1
        return {"keys": self.keys}


def token(email="Pat@Example.com", key=KEY, kid="k1", aud=AUD, iss=f"https://{TEAM}.cloudflareaccess.com", exp=3600):
    now = datetime.now(timezone.utc)
    claims = {"aud": [aud], "iss": iss, "iat": now, "exp": now + timedelta(seconds=exp)}
    if email:
        claims["email"] = email
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def test_verify_accepts_a_valid_token_and_lowercases_the_email():
    assert AccessVerifier(TEAM, AUD, fetch=Certs(jwk(KEY, "k1"))).verify(token()) == "pat@example.com"


@pytest.mark.parametrize("bad", [
    token(aud="someone-else"),                                   # another Access application
    token(exp=-120),                                             # expired (beyond the 30 s leeway)
    token(iss="https://evil.cloudflareaccess.com"),             # another team
    token(key=OTHER),                                            # right key id, wrong signature
    token(kid="unknown"),                                        # a key the team never published
    token(email=None),                                           # a service token: not a person
    "not-a-jwt", "", None,
])
def test_verify_rejects_bad_tokens(bad):
    assert AccessVerifier(TEAM, AUD, fetch=Certs(jwk(KEY, "k1"))).verify(bad) is None


def test_unknown_key_refetches_at_most_every_five_minutes():
    t = [1000.0]
    certs = Certs(jwk(KEY, "k1"))
    v = AccessVerifier(TEAM, AUD, fetch=certs, clock=lambda: t[0])
    assert v.verify(token()) and certs.calls == 1
    assert v.verify(token(kid="k2", key=OTHER)) is None and certs.calls == 1     # within 5 min: no refetch
    certs.keys.append(jwk(OTHER, "k2"))                                        # Cloudflare rotates keys
    t[0] += REFETCH_SECONDS
    assert v.verify(token(kid="k2", key=OTHER)) == "pat@example.com" and certs.calls == 2


def test_keys_unreachable_fails_closed_and_retries_soon():
    t, up = [1000.0], [False]
    good = Certs(jwk(KEY, "k1"))

    def flaky(team):
        if not up[0]:
            raise OSError("no route")
        return good(team)
    v = AccessVerifier(TEAM, AUD, fetch=flaky, clock=lambda: t[0])
    assert v.verify(token()) is None                    # fail closed
    up[0] = True
    assert v.verify(token()) is None                    # within the retry backoff: no hammering
    t[0] += RETRY_SECONDS
    assert v.verify(token()) == "pat@example.com"       # not locked out for the 5-minute refetch window


def test_user_change_rules():
    new, log = user_change(None, {"role": "admin", "note": "co-founder"}, False)   # set up before first sign-in
    assert new == {"role": "admin", "active": True, "note": "co-founder"}
    assert log == [("role", None, "admin"), ("active", None, "true"), ("note", None, "co-founder")]
    assert user_change(None, {"role": "viewer"}, False)[1] == [("role", None, "viewer"), ("active", None, "true")]
    assert user_change(new, {"active": False}, False)[1] == [("active", "true", "false")]
    assert user_change(None, {"note": "me"}, True)[0]["role"] == "admin"            # an owner with no row yet
    for bad, owner in (({"role": "root"}, False), ({"active": "no"}, False), ({}, False), ({"email": "x"}, False),
                       ({"role": "viewer"}, True), ({"active": False}, True), ({"note": "x" * 501}, False)):
        with pytest.raises(ValueError):
            user_change({"role": "admin", "active": True, "note": None}, bad, owner)


# ---------------------------------------------------------------- the gate


def users_stub(*users):
    base = {"first_seen": None, "last_seen": None, "note": None, "updated_at": None, "updated_by": None}
    return lambda: [{**base, **u} for u in users]


def client(users=(), touched=None, set_user=None, password="s3cret", admin_password="adm1n"):
    return TestClient(create_app(
        fetch=rows, fetch_gone=gone_rows, fetch_status=status_stub, fetch_review=lambda: [], fetch_curated=lambda: [],
        fetch_seen=lambda: [], fetch_nodes=lambda: [],
        fetch_users=users_stub(*users), touch_user=lambda e, o: (touched if touched is not None else []).append((e, o)),
        set_user=set_user or (lambda *a: {"changed": []}), password=password, admin_password=admin_password,
        verifier=AccessVerifier(TEAM, AUD, fetch=Certs(jwk(KEY, "k1"))), admin_emails="Owner@Example.com"))


def h(email):
    return {HEADER: token(email)}


def test_a_signed_in_viewer_sees_the_preview_but_not_admin():
    touched = []
    c = client(touched=touched)
    assert c.get("/api/feed", headers=h("new@example.com")).status_code == 200      # no password popup
    assert c.get("/closed-preview/status", headers=h("new@example.com")).status_code == 200
    r = c.get("/admin/", headers=h("new@example.com"))
    assert r.status_code == 403 and "www-authenticate" not in r.headers
    assert touched == [("new@example.com", False)]                                   # throttled: once


def test_admins_owners_and_deactivated_people():
    users = [{"email": "ann@example.com", "role": "admin", "active": True},
             {"email": "gone@example.com", "role": "admin", "active": False}]
    c = client(users=users)
    assert c.get("/admin/", headers=h("ann@example.com")).status_code == 200
    assert c.get("/admin/", headers=h("owner@example.com")).status_code == 200       # ADMIN_EMAILS, no row needed
    me = c.get("/admin/api/me", headers=h("owner@example.com")).json()
    assert me["email"] == "owner@example.com" and me["owner"] and me["admin"] == "owner@example.com"
    for path in ("/api/feed", "/admin/"):
        assert c.get(path, headers=h("gone@example.com")).status_code == 403         # deactivated: nothing at all


def test_without_a_token_the_passwords_still_work_until_cutover():
    import base64
    basic = lambda u, p: {"authorization": "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()}  # noqa: E731
    c = client()
    assert c.get("/api/feed").status_code == 401
    assert c.get("/api/feed", headers=basic("fiftyoff", "s3cret")).status_code == 200
    assert c.get("/admin/", headers=basic("admin", "adm1n")).status_code == 200
    assert c.get("/api/feed", headers={HEADER: token(aud="other")}).status_code == 401   # a bad token is no token
    assert c.get("/api/health").status_code == 200
    # after cutover (passwords removed from .env) only Access gets in
    c2 = client(password="", admin_password="")
    assert c2.get("/admin/").status_code == 401 and c2.get("/admin/", headers=h("owner@example.com")).status_code == 200


def test_people_tab_changes_roles_and_records_who():
    calls = []

    def set_user(email, change, owner, by):
        new, log = user_change(None, change, owner)
        calls.append((email, owner, by))
        return {**new, "changed": [f for f, _, _ in log]}

    c = client(users=[{"email": "pat@example.com", "role": "viewer", "active": True}], set_user=set_user)
    hdr = h("owner@example.com")
    r = c.post("/admin/api/people/Pat@Example.com", json={"role": "admin"}, headers=hdr)
    assert r.status_code == 200 and r.json()["role"] == "admin" and calls == [("pat@example.com", False, "owner@example.com")]
    assert c.post("/admin/api/people/owner@example.com", json={"active": False}, headers=hdr).status_code == 400
    assert c.post("/admin/api/people/not-an-email", json={"role": "admin"}, headers=hdr).status_code == 400
    assert c.post("/admin/api/people/pat@example.com", json={"role": "admin"}, headers=h("pat@example.com")).status_code == 403
    people = c.get("/admin/api/people", headers=hdr).json()
    assert [p["email"] for p in people["items"]] == ["pat@example.com"] and people["owners"] == ["owner@example.com"]
