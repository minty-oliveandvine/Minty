"""Phase 1 of the Terms of Use work: the documents, their fingerprints, and
the public pages that show them.

The fingerprint tests are the point of this file. A consent record stores the
SHA-256 of the wording the person saw, so if the hash function, the newline
normalisation, or a published file ever changes, every record pointing at it
becomes unverifiable. These tests are what make that change loud.
"""

import pytest

from legal import registry
from legal.render import render_markdown


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------

def test_current_terms_document_exists():
    """The version the app advertises must actually have a file behind it.

    If this fails, /legal/terms 404s and the Phase 4 gate redirects people to
    a page that cannot render — the lock-out described in the runbook.
    """
    assert registry.get_current(registry.TERMS) is not None


def test_current_privacy_document_exists():
    assert registry.get_current(registry.PRIVACY) is not None


def test_fingerprint_is_sha256_shaped():
    """64 hex characters — the width of terms_consent.document_hash."""
    document = registry.get_current(registry.TERMS)
    assert len(document.sha256) == 64
    assert all(c in "0123456789abcdef" for c in document.sha256)


def test_fingerprint_is_stable_across_line_endings():
    """CRLF and LF must hash identically.

    Without this, a Windows checkout with core.autocrlf writes consent rows
    that look tampered with when read on the Linux host, and vice versa.
    """
    lf = "# Title\n\nA line.\n"
    crlf = "# Title\r\n\r\nA line.\r\n"
    assert registry._fingerprint(registry._normalise(lf)) == registry._fingerprint(
        registry._normalise(crlf)
    )


def test_fingerprint_changes_when_one_letter_changes():
    """The whole point of storing a hash — prove the wording, not just the name."""
    a = registry._fingerprint(registry._normalise("The cap is HKD100."))
    b = registry._fingerprint(registry._normalise("The cap is HKD200."))
    assert a != b


def test_verify_pinned_hashes_reports_no_problems():
    """Unpinned drafts warn; they are not problems. A mismatch or a missing
    current file is a problem, and there should be none."""
    assert registry.verify_pinned_hashes() == []


# --------------------------------------------------------------------------
# The renderer
# --------------------------------------------------------------------------

def test_renderer_escapes_html():
    """The legal text is escaped before any markup is applied.

    A document is quoted verbatim in a dispute, so it must never be able to
    inject markup into the page that displays it — including a future revision
    written by someone not thinking about that.
    """
    html = render_markdown("- <script>alert(1)</script>\n")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_renderer_handles_the_four_constructs():
    html = render_markdown("# T\n\n## S\n\n- one\n- two\n\n**b** rest\n")
    assert "<h1>T</h1>" in html
    assert "<h2>S</h2>" in html
    assert html.count("<li>") == 2
    assert "<ul>" in html and "</ul>" in html
    assert "<strong>b</strong>" in html


def test_terms_renders_every_section_and_bullet():
    """Guards the docx -> markdown conversion. The source document has 23
    numbered sections and 106 bullets; a conversion that silently drops
    clauses is the failure mode worth catching."""
    document = registry.get_current(registry.TERMS)
    assert document.html.count("<h2>") == 23
    assert document.html.count("<li>") == 106


# --------------------------------------------------------------------------
# The public pages
# --------------------------------------------------------------------------

@pytest.fixture
def client():
    import main

    return main.app.test_client()


@pytest.mark.parametrize(
    "url",
    [
        "/legal/current",
        "/legal/terms",
        "/legal/terms/beta-1",
        "/legal/privacy",
        "/legal/privacy/beta-1",
    ],
)
def test_legal_pages_are_readable_without_logging_in(client, url):
    """None of these may require a session.

    Someone signing up has no account yet, and someone held at the Phase 4
    gate must be able to read what they are being asked to agree to. Phase 4
    must allow-list exactly this set.
    """
    assert client.get(url).status_code == 200


def test_unknown_version_is_404(client):
    assert client.get("/legal/terms/beta-9").status_code == 404


def test_current_endpoint_reports_the_live_version(client):
    body = client.get("/legal/current").get_json()
    assert body["terms_version"] == registry.current_version(registry.TERMS)
    assert body["terms_url"] == "/legal/terms"
    # Null until the legal owner fills in `Last Updated: [DATE]`. Asserted so
    # that resolving the blank is a deliberate change, not a silent one.
    assert body["effective_date"] is None


def test_terms_page_shows_the_fingerprint(client):
    """Shown on the page so a consent record can be checked against what is
    displayed, without database access."""
    document = registry.get_current(registry.TERMS)
    assert document.sha256 in client.get("/legal/terms").get_data(as_text=True)
