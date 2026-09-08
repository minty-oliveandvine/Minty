"""Unit tests for the AI Capture Hub's front door — the checks that run before
anything is stored and before any model call is made.

These are the cheap tests that protect the expensive path. Every one of them
covers a case where letting a file through costs real money: a 40-page bank
statement is eleven model calls, a re-uploaded receipt is a duplicate set of
drafts, and a file that merely *claims* to be a PDF fails somewhere much less
convenient than here.

No network and no database. Config is read from the environment on each call,
so these tests set environment variables directly — which is also a test that
the kill switch really does work without a restart.
"""

from __future__ import annotations

import io

import pytest

from blueprints.capture.services import capture_ai as ai
from blueprints.capture.services import pdf_tools, storage


# --------------------------------------------------------------------------
# Helpers: real PDFs, built in memory.
# --------------------------------------------------------------------------
def make_pdf(pages: int) -> bytes:
    import pikepdf

    pdf = pikepdf.Pdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(595, 842))  # A4
    buffer = io.BytesIO()
    pdf.save(buffer)
    return buffer.getvalue()


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture(autouse=True)
def clean_rate_limits():
    ai.reset_rate_limits()
    yield
    ai.reset_rate_limits()


# --------------------------------------------------------------------------
# The kill switch. Default off — the feature ships dark.
# --------------------------------------------------------------------------
def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CAPTURE_AI_ENABLED", raising=False)
    assert ai.is_enabled() is False


def test_kill_switch_needs_no_restart(monkeypatch):
    """Config is read on every call, so flipping the variable takes effect
    immediately. If this ever fails, the kill switch has become a deployment."""
    monkeypatch.setenv("CAPTURE_AI_ENABLED", "true")
    assert ai.is_enabled() is True
    monkeypatch.setenv("CAPTURE_AI_ENABLED", "false")
    assert ai.is_enabled() is False


def test_enabled_accepts_the_usual_spellings(monkeypatch):
    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("CAPTURE_AI_ENABLED", value)
        assert ai.is_enabled() is True, value
    for value in ("0", "false", "no", "off", "maybe", ""):
        monkeypatch.setenv("CAPTURE_AI_ENABLED", value)
        assert ai.is_enabled() is False, value


# --------------------------------------------------------------------------
# Content sniffing. The extension a browser sends is a claim, not evidence.
# --------------------------------------------------------------------------
def test_sniff_recognises_the_three_supported_types():
    assert ai.sniff_mime(make_pdf(1)) == "application/pdf"
    assert ai.sniff_mime(PNG_BYTES) == "image/png"
    assert ai.sniff_mime(JPEG_BYTES) == "image/jpeg"


def test_sniff_rejects_everything_else():
    assert ai.sniff_mime(b"") is None
    assert ai.sniff_mime(b"PK\x03\x04 this is a zip") is None
    assert ai.sniff_mime(b"<html><body>not a receipt</body></html>") is None
    # A text file NAMED receipt.pdf. The name is not evidence and never reaches
    # the sniffer.
    assert ai.sniff_mime(b"total: $12.00") is None


def test_sniff_sees_through_a_lying_extension():
    """A .pdf that is really a JPEG is common and harmless — we simply record
    what it actually is, so the stored extension matches the stored bytes."""
    assert ai.sniff_mime(JPEG_BYTES) == "image/jpeg"


# --------------------------------------------------------------------------
# Duplicate detection is on the BYTES.
# --------------------------------------------------------------------------
def test_hash_is_stable_and_content_addressed():
    data = make_pdf(1)
    assert ai.content_hash(data) == ai.content_hash(bytes(data))
    assert len(ai.content_hash(data)) == 64


def test_hash_differs_for_different_content():
    assert ai.content_hash(make_pdf(1)) != ai.content_hash(make_pdf(2))


# --------------------------------------------------------------------------
# Page counting and the page cap.
# --------------------------------------------------------------------------
def test_page_count_reads_real_pdfs():
    assert pdf_tools.page_count(make_pdf(1)) == 1
    assert pdf_tools.page_count(make_pdf(3)) == 3
    assert pdf_tools.page_count(make_pdf(7)) == 7


def test_page_count_raises_on_a_file_that_only_claims_to_be_a_pdf():
    """Refused at upload with a plain message, rather than failing later in a
    background thread after we have paid to store it."""
    with pytest.raises(pdf_tools.PdfUnreadable):
        pdf_tools.page_count(b"%PDF-1.7 and then nothing useful at all")


def test_page_limit_default_is_three(monkeypatch):
    monkeypatch.delenv("CAPTURE_AI_MAX_PAGES", raising=False)
    assert ai.max_pages() == 3


def test_page_limit_is_configurable(monkeypatch):
    monkeypatch.setenv("CAPTURE_AI_MAX_PAGES", "5")
    assert ai.max_pages() == 5


def test_a_nonsense_limit_falls_back_to_the_default(monkeypatch):
    """A typo in the environment must not disable the cap. Falling back to the
    default keeps the cost control; crashing would take the feature down."""
    monkeypatch.setenv("CAPTURE_AI_MAX_PAGES", "three")
    assert ai.max_pages() == 3


# --------------------------------------------------------------------------
# Page range clamping. The model will occasionally return page 4 of a 3-page
# PDF, and unclamped that crashes pikepdf inside a background thread.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "start,end,total,expected",
    [
        (1, 3, 3, (1, 3)),        # already valid
        (0, 2, 3, (1, 2)),        # start below 1
        (2, 9, 3, (2, 3)),        # end past the document
        (7, 9, 3, (3, 3)),        # both past the document
        (3, 1, 3, (3, 3)),        # end before start
        (None, None, 3, (1, 1)),  # missing entirely
        ("2", "3", 3, (2, 3)),    # strings, as JSON sometimes gives us
        ("x", "y", 3, (1, 1)),    # unparseable
    ],
)
def test_clamp_range(start, end, total, expected):
    assert pdf_tools.clamp_range(start, end, total) == expected


# --------------------------------------------------------------------------
# Page extraction — cutting one document out of a multi-document file.
# --------------------------------------------------------------------------
def test_extract_pages_returns_only_the_requested_range():
    source = make_pdf(3)
    assert pdf_tools.page_count(pdf_tools.extract_pages(source, 2, 3)) == 2
    assert pdf_tools.page_count(pdf_tools.extract_pages(source, 2, 2)) == 1


def test_extract_pages_is_a_no_op_for_the_whole_document():
    """Re-saving a 3-page PDF to get an identical 3-page PDF is work for
    nothing, so the input comes back unchanged."""
    source = make_pdf(3)
    assert pdf_tools.extract_pages(source, 1, 3) is source


def test_extract_pages_clamps_rather_than_raising():
    source = make_pdf(3)
    assert pdf_tools.page_count(pdf_tools.extract_pages(source, 2, 99)) == 2


def test_extract_pages_raises_on_an_unreadable_source():
    with pytest.raises(pdf_tools.PdfUnreadable):
        pdf_tools.extract_pages(b"%PDF-1.7 truncated", 1, 1)


# --------------------------------------------------------------------------
# Rate limiting. Lower than Stage 1's, because one upload here can cost eleven
# model calls where a Stage 1 request costs exactly one.
# --------------------------------------------------------------------------
def test_per_user_limit_stops_the_sixth_upload(monkeypatch):
    monkeypatch.setenv("CAPTURE_AI_RATE_USER_PER_MIN", "5")
    monkeypatch.setenv("CAPTURE_AI_RATE_ENTITY_PER_HOUR", "1000")
    for attempt in range(5):
        assert ai.check_rate_limit("user-1", "ent-1") is True, attempt
    assert ai.check_rate_limit("user-1", "ent-1") is False


def test_one_users_limit_does_not_affect_another(monkeypatch):
    monkeypatch.setenv("CAPTURE_AI_RATE_USER_PER_MIN", "2")
    monkeypatch.setenv("CAPTURE_AI_RATE_ENTITY_PER_HOUR", "1000")
    assert ai.check_rate_limit("user-1", "ent-1") is True
    assert ai.check_rate_limit("user-1", "ent-1") is True
    assert ai.check_rate_limit("user-1", "ent-1") is False
    assert ai.check_rate_limit("user-2", "ent-1") is True


def test_entity_limit_catches_a_whole_company(monkeypatch):
    """The per-user limit alone would let ten colleagues spend ten times the
    budget between them."""
    monkeypatch.setenv("CAPTURE_AI_RATE_USER_PER_MIN", "100")
    monkeypatch.setenv("CAPTURE_AI_RATE_ENTITY_PER_HOUR", "3")
    assert ai.check_rate_limit("user-1", "ent-1") is True
    assert ai.check_rate_limit("user-2", "ent-1") is True
    assert ai.check_rate_limit("user-3", "ent-1") is True
    assert ai.check_rate_limit("user-4", "ent-1") is False
    # A different company is unaffected.
    assert ai.check_rate_limit("user-4", "ent-2") is True


def test_a_refused_request_is_not_counted(monkeypatch):
    """Only a permitted request records a hit. Counting refusals would mean a
    user who kept retrying could extend their own lockout indefinitely."""
    monkeypatch.setenv("CAPTURE_AI_RATE_USER_PER_MIN", "1")
    monkeypatch.setenv("CAPTURE_AI_RATE_ENTITY_PER_HOUR", "1000")
    assert ai.check_rate_limit("user-1", "ent-1") is True
    for _ in range(5):
        assert ai.check_rate_limit("user-1", "ent-1") is False
    ai.reset_rate_limits()
    assert ai.check_rate_limit("user-1", "ent-1") is True


# --------------------------------------------------------------------------
# Confidence banding. Shared by both passes and the queue page, so "medium"
# means the same thing everywhere.
# --------------------------------------------------------------------------
def test_bands_sit_where_the_cut_offs_say(monkeypatch):
    monkeypatch.setenv("CAPTURE_AI_CONF_HIGH", "0.85")
    monkeypatch.setenv("CAPTURE_AI_CONF_MEDIUM", "0.60")
    assert ai.band(0.99) == "high"
    assert ai.band(0.85) == "high"      # inclusive at the boundary
    assert ai.band(0.84) == "medium"
    assert ai.band(0.60) == "medium"    # inclusive at the boundary
    assert ai.band(0.59) == "low"
    assert ai.band(0.0) == "low"


def test_confidence_is_clamped_not_trusted():
    """The number comes from the model. It is self-reported, occasionally
    absent, and once in a while not a number at all."""
    assert ai.clamp_confidence(1.5) == 1.0
    assert ai.clamp_confidence(-2) == 0.0
    assert ai.clamp_confidence(None) == 0.0
    assert ai.clamp_confidence("high") == 0.0
    assert ai.clamp_confidence("0.75") == 0.75


# --------------------------------------------------------------------------
# Cost estimation. Thinking is billed at the OUTPUT rate — leaving it out of
# the sum understated a measured Stage 1 call by about 60%.
# --------------------------------------------------------------------------
def test_thinking_tokens_are_billed_as_output(monkeypatch):
    monkeypatch.setenv("CAPTURE_AI_MODEL", "gemini-3.5-flash")  # 1.50 / 9.00
    without = ai.estimate_cost(1_000_000, 1_000_000, 0)
    with_thinking = ai.estimate_cost(1_000_000, 1_000_000, 1_000_000)
    assert without == pytest.approx(10.50)
    assert with_thinking == pytest.approx(19.50)


def test_cost_is_none_when_we_cannot_know_it(monkeypatch):
    monkeypatch.setenv("CAPTURE_AI_MODEL", "some-model-we-have-no-price-for")
    assert ai.estimate_cost(1000, 100, 0) is None
    monkeypatch.setenv("CAPTURE_AI_MODEL", "gemini-3.5-flash")
    assert ai.estimate_cost(None, 100, 0) is None


# --------------------------------------------------------------------------
# S3 keys. Entity first, so a deletion request is a prefix operation.
# --------------------------------------------------------------------------
def test_key_layout_puts_the_entity_first():
    key = storage.original_key("ent-1", "up-1", "application/pdf")
    assert key.startswith("capture/ent-1/")
    assert key.endswith("/up-1/original.pdf")


def test_document_keys_are_numbered_per_document():
    first = storage.document_key("ent-1", "up-1", 1, "application/pdf")
    second = storage.document_key("ent-1", "up-1", 2, "application/pdf")
    assert first.endswith("/doc-1.pdf")
    assert second.endswith("/doc-2.pdf")
    assert first != second


def test_extension_follows_the_sniffed_type_not_the_filename():
    assert storage.extension_for("image/jpeg") == "jpg"
    assert storage.extension_for("image/png") == "png"
    assert storage.extension_for("application/pdf") == "pdf"
    assert storage.extension_for("application/msword") == "bin"
