"""Xero OAuth scope tests.

Three layers of protection around the minimal scope set:

1. Route contract — ``/xero_connect`` and ``/xero_reconnect`` must request
   exactly ``EXPECTED_SCOPES`` (no more, no less, and identical to each other).

2. Exercise — every real Xero HTTP helper in this app (Organisation, Accounts,
   Contacts read+create, Invoices, BankTransactions, BankTransfers, attachment
   upload, token refresh, id_token claims) is driven against a fake Xero API
   that ENFORCES per-endpoint scope rules: a call whose required scope is not
   in the granted set gets a 403, exactly like the real API. The granted set is
   parsed from the live ``/xero_connect`` redirect, so trimming a needed scope
   from the route makes these calls fail. A negative-control test proves the
   harness actually rejects missing scopes (i.e. the test can tell working
   from broken).

3. Drift scan — every Xero endpoint referenced anywhere in this repo AND the
   sibling ``billing_backend`` (which reuses the token issued here) must map to
   a granted scope, and every granted functional scope must be needed by at
   least one endpoint. Adding a new Xero API call or dropping the last user of
   a scope fails this test with instructions.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import requests as real_requests
from werkzeug.security import generate_password_hash

EXPECTED_SCOPES = frozenset(
    {
        "openid",
        "profile",
        "email",
        "offline_access",
        "accounting.settings",
        "accounting.contacts",
        "accounting.invoices",
        "accounting.banktransactions",
        "files",
    }
)

# Scopes that exist only for identity/session handling, not API endpoints.
IDENTITY_SCOPES = frozenset({"openid", "profile", "email", "offline_access"})


# ---------------------------------------------------------------------------
# App/db plumbing (same pattern as test_entity_create.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session(app):
    from models.db import db

    with app.app_context():

        db.session.expire_on_commit = False
        yield db
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(table.delete())
            except Exception:
                pass
        db.session.commit()


def _make_user(db):
    from models.db import User

    user = User(
        id=str(uuid.uuid4()),
        email="scopes@test.com",
        username="scopes@test.com",
        first_name="Scope",
        last_name="Tester",
        password=generate_password_hash("password123"),
        system_role=User.SYSTEM_ROLE_NORMAL,
        approved=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user_id: str) -> None:
    from blueprints.legal.services.gate import TERMS_OK_SESSION_KEY
    from legal import registry

    with client.session_transaction() as sess:
        sess["_user_id"] = user_id
        # A logged-in user who has not accepted the Terms is redirected to
        # /legal/accept by the acceptance gate — correctly, and for every
        # product route. These tests are about Xero scopes, so the session
        # carries the same "already agreed" marker a real accepted user has.
        sess[TERMS_OK_SESSION_KEY] = registry.current_version(registry.TERMS)


def _scopes_from_redirect(response) -> set[str]:
    assert response.status_code == 302, (
        f"expected redirect to Xero authorize, got {response.status_code}"
    )
    location = response.headers["Location"]
    assert "login.xero.com/identity/connect/authorize" in location, location
    query = parse_qs(urlparse(location).query)
    assert "scope" in query, f"no scope param in authorize URL: {location}"
    return set(query["scope"][0].split())


def _connect_scopes(app, client, db_session, monkeypatch) -> set[str]:
    """Log a user in and return the scope set the real /xero_connect requests."""
    from blueprints.xero.routes import routes as xero_routes

    with app.app_context():
        user_id = _make_user(db_session).id
    _login(client, user_id)
    monkeypatch.setattr(xero_routes, "has_permission", lambda *a, **k: True)
    return _scopes_from_redirect(client.get("/xero_connect"))


def _reconnect_scopes(app, client, db_session, monkeypatch) -> set[str]:
    import services.authz as authz

    with app.app_context():
        user_id = _make_user(db_session).id
    _login(client, user_id)
    monkeypatch.setattr(authz, "has_entity_access", lambda *a, **k: True)
    monkeypatch.setattr(authz, "has_permission", lambda *a, **k: True)
    return _scopes_from_redirect(client.get("/xero_reconnect?entity_id=e-1"))


# ---------------------------------------------------------------------------
# Fake Xero API with scope enforcement
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.content = content
        self.text = json.dumps(self._json)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise real_requests.exceptions.HTTPError(f"status {self.status_code}")


def _mint_id_token(claims: dict) -> str:
    def b64(part: dict) -> str:
        raw = json.dumps(part).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}.fakesig"


def _decode_id_token(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


class FakeXero:
    """Intercepts the ``requests`` module and enforces Xero scope rules.

    A GET is satisfied by either the full scope or its ``.read`` variant;
    writes require the full scope — matching Xero's documented behaviour.
    """

    # Matched on the endpoint family, not the base path: most call sites build on
    # app.config["XERO_API_BASE_URL"], while some hardcode the full URL. Ordered: the Attachments rule must run
    # before the transactions rule because attachment URLs contain
    # "/BankTransactions/".
    RULES = (
        (re.compile(r"xero\.com/connections"), None),
        (re.compile(r"/\w+/[^/]+/Attachments/"), "accounting.attachments"),
        (re.compile(r"/Organisation"), "accounting.settings"),
        (re.compile(r"/Accounts"), "accounting.settings"),
        (re.compile(r"/Contacts"), "accounting.contacts"),
        (re.compile(r"/Invoices"), "accounting.invoices"),
        (
            re.compile(r"/(BankTransactions|BankTransfers)"),
            "accounting.banktransactions",
        ),
        (re.compile(r"files\.xro/1\.0/"), "files"),
    )

    # Keeps `except requests.exceptions.X` clauses in production code valid.
    exceptions = real_requests.exceptions

    def __init__(self, granted_scopes):
        self.granted = set(granted_scopes)
        self.exercised: set[str] = set()
        self.unknown_urls: list[str] = []

    def get(self, url, **kwargs):
        return self._handle("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._handle("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self._handle("PUT", url, **kwargs)

    def _handle(self, method, url, **kwargs):
        if "xero.com" not in url:
            # Non-Xero fetch (e.g. downloading the receipt file before upload).
            return _FakeResponse(200, content=b"fake-receipt-bytes")
        if "identity.xero.com/connect/token" in url:
            return self._token_endpoint(kwargs.get("data") or {})
        for pattern, scope in self.RULES:
            if pattern.search(url):
                return self._api(method, url, scope)
        self.unknown_urls.append(f"{method} {url}")
        return _FakeResponse(404, {"Detail": f"unknown endpoint: {url}"})

    def _token_endpoint(self, data):
        if data.get("grant_type") == "refresh_token":
            # Xero only issues refresh tokens when offline_access was granted.
            if "offline_access" not in self.granted:
                return _FakeResponse(400, {"error": "invalid_grant"})
            self.exercised.add("offline_access")
        body = {
            "access_token": "fake-access-token",
            "refresh_token": "fake-refresh-token",
            "expires_in": 1800,
            "token_type": "Bearer",
        }
        if {"openid", "email"} <= self.granted:
            claims = {"email": "owner@test.com"}
            self.exercised.update({"openid", "email"})
            if "profile" in self.granted:
                claims["name"] = "Scope Tester"
                self.exercised.add("profile")
            body["id_token"] = _mint_id_token(claims)
        return _FakeResponse(200, body)

    def _api(self, method, url, scope):
        if scope is None:  # /connections needs only a valid token
            return _FakeResponse(200, [{"tenantId": "tenant-1"}])
        allowed = scope in self.granted or (
            method == "GET" and f"{scope}.read" in self.granted
        )
        if not allowed:
            return _FakeResponse(
                403,
                {
                    "Title": "Forbidden",
                    "Detail": f"AuthorizationUnsuccessful: scope '{scope}' not granted",
                },
            )
        self.exercised.add(scope)
        return _FakeResponse(200, self._payload_for(url))

    @staticmethod
    def _payload_for(url):
        if "files.xro/1.0/Files/Associations/" in url:
            # Nothing previously attached; the republish sweep finds none.
            return []
        if "files.xro/1.0/Files/" in url and "/Associations" in url:
            return {"Id": "assoc-1"}
        if "files.xro/1.0/Files" in url:
            return {"FileId": "file-1"}
        if "/Attachments/" in url:
            return {"Attachments": [{"AttachmentID": "att-1"}]}
        if "/Organisation" in url:
            return {
                "Organisations": [
                    {
                        "OrganisationID": "org-1",
                        # 2024-01-01T00:00:00Z in Xero's /Date(ms)/ format
                        "PeriodLockDate": "/Date(1704067200000+0000)/",
                        "EndOfYearLockDate": "/Date(1704067200000+0000)/",
                    }
                ]
            }
        if "/Accounts" in url:
            return {
                "Accounts": [
                    {"AccountID": "acct-1", "Type": "BANK", "BankAccountNumber": "000-123"}
                ]
            }
        if "/Contacts" in url:
            return {"Contacts": [{"ContactID": "contact-1", "Name": "Supplier Ltd"}]}
        if "/Invoices" in url:
            return {"Invoices": [{"InvoiceID": "inv-1"}]}
        if "/BankTransfers" in url:
            return {"BankTransfers": [{"BankTransferID": "transfer-1"}]}
        if "/BankTransactions" in url:
            return {"BankTransactions": [{"BankTransactionID": "bt-1"}]}
        return {}


# ---------------------------------------------------------------------------
# 1. Route contract
# ---------------------------------------------------------------------------


def test_connect_requests_exact_minimal_scopes(app, client, db_session, monkeypatch):
    scopes = _connect_scopes(app, client, db_session, monkeypatch)
    assert scopes == set(EXPECTED_SCOPES), (
        f"/xero_connect scope drift.\n"
        f"  missing: {sorted(set(EXPECTED_SCOPES) - scopes)}\n"
        f"  extra:   {sorted(scopes - set(EXPECTED_SCOPES))}"
    )


def test_reconnect_requests_same_scopes_as_connect(app, client, db_session, monkeypatch):
    scopes = _reconnect_scopes(app, client, db_session, monkeypatch)
    assert scopes == set(EXPECTED_SCOPES), (
        f"/xero_reconnect must request the same minimal set as /xero_connect.\n"
        f"  missing: {sorted(set(EXPECTED_SCOPES) - scopes)}\n"
        f"  extra:   {sorted(scopes - set(EXPECTED_SCOPES))}"
    )


# ---------------------------------------------------------------------------
# 2. Exercise every Xero call with ONLY the granted scopes
# ---------------------------------------------------------------------------


def test_every_xero_call_succeeds_with_granted_scopes(app, client, db_session, monkeypatch):
    import blueprints.xero.services.integration as integration
    import blueprints.xero.services.publish as publish
    import services.auth.token_service as token_service

    # Grant exactly what the live route requests — nothing hardcoded.
    granted = _connect_scopes(app, client, db_session, monkeypatch)
    fake = FakeXero(granted)
    monkeypatch.setattr(publish, "requests", fake)
    monkeypatch.setattr(integration, "requests", fake)
    monkeypatch.setattr(token_service, "requests", fake)

    org_id = "org-1"
    token = "fake-access-token"

    with app.app_context():
        # offline_access + openid/profile/email: refresh grant returns tokens
        # and an id_token whose claims the login callback depends on.
        token_data = token_service.refresh_access_token_for_user(
            SimpleNamespace(refresh_token="fake-refresh-token"), application=app
        )
        assert token_data is not None, "token refresh failed — offline_access missing?"
        assert token_data["access_token"]
        assert "id_token" in token_data, "no id_token — openid/email scope missing?"
        claims = _decode_id_token(token_data["id_token"])
        assert claims.get("email") == "owner@test.com"
        assert "name" in claims, "no name claim — profile scope missing?"

        # accounting.settings: Organisation lock dates + chart of accounts.
        lock_dates = integration.get_organisation_lock_dates(token, org_id)
        assert lock_dates["period_lock_date"] == date(2024, 1, 1), (
            "GET /Organisation failed — accounting.settings missing?"
        )
        accounts = integration.get_accounts_from_xero(token, org_id, token_validated=True)
        assert accounts and accounts[0]["Type"] == "BANK", (
            "GET /Accounts failed — accounting.settings missing?"
        )

        # accounting.contacts: list + create.
        contacts = integration.get_contacts_from_xero(token, org_id, token_validated=True)
        assert contacts and contacts[0]["ContactID"] == "contact-1", (
            "GET /Contacts failed — accounting.contacts missing?"
        )
        new_contact = publish.create_xero_contact(
            str(uuid.uuid4()), "New Supplier", token, org_id
        )
        assert new_contact == "contact-1", (
            "POST /Contacts failed — accounting.contacts missing?"
        )

        # accounting.banktransactions / accounting.invoices: the publish
        # pipeline's three endpoints. BankTransfers rides on the
        # banktransactions scope, same as BankTransactions.
        resp = publish.bank_transaction_to_xero(org_id, token, {"Type": "SPEND"})
        assert resp.status_code == 200, (
            f"POST /BankTransactions -> {resp.status_code} — accounting.banktransactions missing?"
        )
        resp = publish.bank_transfer_to_xero(org_id, token, {"BankTransfers": []})
        assert resp.status_code == 200, (
            f"POST /BankTransfers -> {resp.status_code} — accounting.banktransactions missing?"
        )
        resp = publish.invoice_to_xero(org_id, token, {"Invoices": []})
        assert resp is not None and resp.status_code == 200, (
            "PUT /Invoices failed — accounting.invoices missing?"
        )

        # files: receipts go through the Files API, not the Accounting
        # attachments endpoint. That endpoint has no DELETE, so a republish
        # could never remove a receipt it had replaced.
        expense = SimpleNamespace(  # C4: the first receipt's key is ``s3_key`` (no ``files``)
            s3_key="https://cdn.example.test/receipt.png",
            remarks="fuel receipt",
            item="fuel",
        )
        entity = SimpleNamespace(id="e-1", xero_org_id=org_id)
        uploaded = publish.upload_each_file(expense, entity, "bt-1", access_token=token)
        assert uploaded is True, (
            "Files API upload/association failed — files scope missing?"
        )

    assert not fake.unknown_urls, (
        f"calls hit endpoints this test doesn't model: {fake.unknown_urls}"
    )
    # `files` is exercised by billing_backend, not this app — the drift-scan
    # test below is what justifies it. Everything else must have been used.
    must_exercise = set(EXPECTED_SCOPES) - {"files"}
    assert must_exercise <= fake.exercised, (
        f"scopes granted but never exercised by these calls: "
        f"{sorted(must_exercise - fake.exercised)}"
    )


def test_harness_detects_missing_scope(app, client, db_session, monkeypatch):
    """Negative control: prove the fake Xero rejects calls lacking a scope,
    so a green run of the test above genuinely means the scopes work."""
    import blueprints.xero.services.publish as publish
    import services.auth.token_service as token_service

    granted = _connect_scopes(app, client, db_session, monkeypatch)

    crippled = FakeXero(granted - {"accounting.invoices"})
    monkeypatch.setattr(publish, "requests", crippled)
    with app.app_context():
        resp = publish.invoice_to_xero("org-1", "fake-access-token", {"Invoices": []})
        assert resp is not None and resp.status_code == 403, (
            "harness failed to reject a call missing accounting.invoices"
        )

    no_refresh = FakeXero(granted - {"offline_access"})
    monkeypatch.setattr(token_service, "requests", no_refresh)
    with app.app_context():
        token_data = token_service.refresh_access_token_for_user(
            SimpleNamespace(refresh_token="fake-refresh-token"), application=app
        )
        assert token_data is None, (
            "harness failed to reject a refresh without offline_access"
        )


# ---------------------------------------------------------------------------
# 3. Drift scan across Minty AND billing_backend
# ---------------------------------------------------------------------------

# Xero endpoint family -> required scope (None = any valid token works).
FAMILY_SCOPE = {
    "Organisation": "accounting.settings",
    "Accounts": "accounting.settings",
    "Contacts": "accounting.contacts",
    "Invoices": "accounting.invoices",
    "BankTransactions": "accounting.banktransactions",
    "BankTransfers": "accounting.banktransactions",
    "Attachments": "accounting.attachments",
    "Files": "files",
    "Associations": "files",
    "connections": None,
}

_ENDPOINT_PATTERNS = (
    re.compile(r"api\.xro/2\.0/([A-Za-z]+)"),
    re.compile(r"files\.xro/1\.0/([A-Za-z]+)"),
    re.compile(r"XERO_API_BASE(?:_URL)?[^\n]*?}/([A-Za-z]+)"),
    re.compile(r"XERO_FILES_API_BASE}/([A-Za-z]+)"),
    re.compile(r"api\.xero\.com/(connections)"),
    re.compile(r"/(Attachments)/"),
)

_SKIP_DIRS = {
    "tests",
    ".archived",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "site-packages",
    ".git",
}


def _scan_endpoint_families(root: Path) -> dict[str, set[str]]:
    """Map each Xero endpoint family found under root -> files referencing it."""
    found: dict[str, set[str]] = {}
    for path in root.rglob("*.py"):
        if _SKIP_DIRS & set(path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in _ENDPOINT_PATTERNS:
            for match in pattern.finditer(text):
                found.setdefault(match.group(1), set()).add(str(path.relative_to(root)))
    return found


def test_all_codebase_xero_endpoints_covered_by_granted_scopes():
    minty_root = Path(__file__).resolve().parents[1]
    billing_root = minty_root.parent / "billing_backend"
    if not billing_root.is_dir():
        pytest.skip(
            "billing_backend not found next to Minty — cannot verify the "
            "'files' scope or billing's endpoint coverage"
        )

    families: dict[str, set[str]] = {}
    for root in (minty_root, billing_root):
        for family, files in _scan_endpoint_families(root).items():
            families.setdefault(family, set()).update(
                f"{root.name}/{f}" for f in files
            )

    unknown = {f: sorted(files) for f, files in families.items() if f not in FAMILY_SCOPE}
    assert not unknown, (
        "New Xero endpoint family in the codebase with no scope mapping — add it "
        f"to FAMILY_SCOPE and, if needed, to the OAuth scope strings: {unknown}"
    )

    required = {FAMILY_SCOPE[f] for f in families if FAMILY_SCOPE[f] is not None}
    missing = required - set(EXPECTED_SCOPES)
    assert not missing, (
        f"the codebase calls endpoints needing scopes we do not request: {sorted(missing)}"
    )

    functional = set(EXPECTED_SCOPES) - IDENTITY_SCOPES
    unused = functional - required
    assert not unused, (
        "scopes requested but no endpoint in Minty or billing_backend needs them — "
        f"remove them from the OAuth scope strings: {sorted(unused)}"
    )
