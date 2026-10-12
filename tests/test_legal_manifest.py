"""The legal MANIFEST: which versions exist, their dates, and their fingerprints.

What this file used to be (`test_legal_documents.py`) tested the documents themselves —
the `.md` files, the newline normalisation, the renderer, the public pages. All of that
moved to minty-web on 2026-10-12 and is tested there
(`minty-web/lib/legal/__tests__/registry.test.ts`, which re-hashes every file and holds the
same `c90a335e…` literal this file does).

What is left here is the half this app must own, because it writes `terms_consent`:

  * the version a consent row may name (`CURRENT_TERMS_VERSION`), and
  * the fingerprint stamped into that row (`MANIFEST[...].sha256`).

THE FROZEN LITERAL BELOW IS THE CONTRACT WITH MINTY-WEB. If it has to change to make this
pass, something is wrong: a wording change is a new version, never an edit of a published
one. The two repos are compared live by the stack e2e job; this is the cheap half.
"""

import pytest

from legal import registry

#: The fingerprint of `terms/beta-1`, pinned 2026-09-18. Must equal minty-web's
#: `TERMS_BETA_1_SHA256` in lib/legal/__tests__/registry.test.ts.
TERMS_BETA_1_SHA256 = "c90a335ed1b5b8cf5d8f5dc6702117418878594053ef3c0720b7816182c7c438"


# --------------------------------------------------------------------------
# The manifest
# --------------------------------------------------------------------------

def test_the_live_terms_version_is_in_the_manifest():
    """Without an entry, nobody can be asked to agree.

    `record_consent` refuses (it would have no fingerprint to record) and the gate stops
    enforcing and says so — the lock-out the runbook describes, in the other direction.
    """
    assert registry.get_current(registry.TERMS) is not None


def test_the_live_privacy_version_is_in_the_manifest():
    assert registry.get_current(registry.PRIVACY) is not None


def test_every_terms_version_has_a_fingerprint():
    """A `terms` version with no hash could be agreed to but not recorded."""
    for (kind, version), entry in registry.MANIFEST.items():
        if kind == registry.TERMS:
            assert entry.sha256, f"{kind}/{version} has no fingerprint"


def test_fingerprints_are_sha256_shaped():
    """64 hex characters — the width of `terms_consent.document_hash`."""
    for (kind, version), entry in registry.MANIFEST.items():
        if entry.sha256 is None:
            continue
        assert len(entry.sha256) == 64, f"{kind}/{version}"
        assert all(c in "0123456789abcdef" for c in entry.sha256), f"{kind}/{version}"


def test_terms_beta_1_is_pinned_to_the_wording_minty_web_holds():
    """The contract with minty-web, frozen.

    Pinned on 2026-09-18 once the header date and the §23 contact details were filled in.
    From here a wording change is a new file in minty-web, never an edit of this one, or
    every consent row pointing at it looks tampered with.
    """
    entry = registry.get_version(registry.TERMS, "beta-1")
    assert entry.sha256 == TERMS_BETA_1_SHA256
    assert entry.is_pinned
    assert entry.show_draft_notice is False
    assert entry.effective_date == "18 September 2026"


def test_privacy_beta_1_is_still_an_unpinned_draft():
    """A placeholder awaiting the actual policy text (runbook open decision #1).

    Unpinned, so it shows the draft notice. It needs no fingerprint: no consent row is ever
    written for the Privacy Policy, and minty-web's own registry supplies the fingerprint
    its `/privacy` page prints.
    """
    entry = registry.get_version(registry.PRIVACY, "beta-1")
    assert entry.is_pinned is False
    assert entry.sha256 is None


def test_verify_manifest_reports_no_problems():
    """An unpinned draft warns; it is not a problem. A live version missing from the
    manifest, or a Terms version with no fingerprint, is — and there should be none."""
    assert registry.verify_manifest() == []


def test_verify_manifest_reports_a_live_version_it_does_not_know():
    """The one thing it can still catch at startup: a mistyped CURRENT_TERMS_VERSION."""
    live = registry.CURRENT_TERMS_VERSION
    registry.CURRENT_TERMS_VERSION = "beta-99"
    try:
        problems = registry.verify_manifest()
    finally:
        registry.CURRENT_TERMS_VERSION = live
    assert any("beta-99" in p for p in problems)


def test_previous_version_is_none_for_the_first_published_version():
    assert registry.previous_version(registry.TERMS, "beta-1") is None


# --------------------------------------------------------------------------
# What this app still answers
# --------------------------------------------------------------------------

@pytest.fixture
def client(app):
    """Through the `app` fixture, which builds the test database: importing `main` on its own
    connects to a database that may not exist yet."""
    return app.test_client()


def test_current_endpoint_is_readable_without_logging_in(client):
    """minty-web's sign-up screen asks this before anyone has an account, and someone held
    at the gate may be asked it too — so it must not require a session, and must stay on the
    gate's allow-list."""
    assert client.get("/legal/current").status_code == 200


def test_current_endpoint_reports_the_live_version_and_no_urls(client):
    """This app names the version; minty-web supplies the text and owns the links.

    `terms_url`/`privacy_url` were dropped with the pages they pointed at (2026-10-12) — a
    client linking to `/legal/terms` here would send people to a 404.
    """
    body = client.get("/legal/current").get_json()
    assert body["terms_version"] == registry.current_version(registry.TERMS)
    assert body["privacy_version"] == registry.current_version(registry.PRIVACY)
    # The header date, verbatim — every surface prints this string as-is. Asserted so a
    # change of the live version's date is deliberate.
    assert body["effective_date"] == "18 September 2026"
    assert "terms_url" not in body
    assert "privacy_url" not in body


@pytest.mark.parametrize(
    "url",
    [
        "/legal/accept",
        "/legal/terms",
        "/legal/terms/beta-1",
        "/legal/privacy",
        "/legal/privacy/beta-1",
        "/legal/content/terms",
    ],
)
def test_the_document_pages_are_gone(client, url):
    """They are minty-web's now (`/terms`, `/privacy`), by the owner's decision: no redirect,
    and nothing in any repo links here any more."""
    assert client.get(url).status_code == 404
