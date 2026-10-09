"""Every receipt opens in the full-screen viewer - never a new tab, never a download.

These read the templates and `scripts.js` off disk rather than rendering a page. That is
deliberate: a `target="_blank"` sitting in a branch no test happens to render is exactly the
kind of thing that came back twice before, and the only way to see all of them at once is to
look at the source. The one rendered test at the bottom proves the markup the user clicks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
PARTIAL = "components/receipt_viewer_modal.html"

#: Every page that shows a receipt and so must include the viewer partial.
RECEIPT_PAGES = [
    "report/expense.html",
    "report_detail.html",
    "edit_report.html",
    "index.html",
]


def read(rel: str) -> str:
    return (TEMPLATES / rel).read_text(encoding="utf-8")


def handle_file_preview(scripts_js: str) -> str:
    """Just the receipt-preview function, so the statements export is not in the frame.

    They both happen to name a variable `downloadLink`, and only one of them is allowed to.
    """
    start = scripts_js.index("function handleFilePreview(")
    end = scripts_js.index("// Attach event listeners to preview buttons", start)
    return scripts_js[start:end]


@pytest.fixture(scope="module")
def scripts_js() -> str:
    return (ROOT / "static" / "js" / "scripts.js").read_text(encoding="utf-8")


class TestThePartial:
    def test_exists_and_brings_its_own_renderer(self) -> None:
        partial = read(PARTIAL)

        assert "js/receipt_preview.js" in partial
        assert 'id="receiptViewerModal"' in partial
        assert "function openReceiptViewer(" in partial
        assert "function openReceiptByKey(" in partial
        assert "function toPreviewUrl(" in partial

    def test_carries_plain_css_for_the_bootstrap_only_pages(self) -> None:
        # report_detail.html and edit_report.html load Bootstrap, not Tailwind, so the
        # modal's Tailwind classes are inert there and the geometry has to be real CSS.
        partial = read(PARTIAL)

        assert "#receiptViewerModal {" in partial
        assert "#receiptViewerModal.hidden { display: none; }" in partial
        assert "z-index: 200;" in partial

    def test_binds_one_delegated_listener_so_no_page_needs_its_own_js(self) -> None:
        partial = read(PARTIAL)

        assert "data-receipt-key], [data-receipt-url]" in partial

    @pytest.mark.parametrize("page", RECEIPT_PAGES)
    def test_is_included_exactly_once_per_receipt_page(self, page: str) -> None:
        assert read(page).count(PARTIAL) == 1


class TestNothingLeavesThePage:
    @pytest.mark.parametrize("page", RECEIPT_PAGES)
    def test_no_receipt_opens_in_a_new_tab(self, page: str) -> None:
        offenders = [
            line.strip()
            for line in read(page).splitlines()
            if "_blank" in line and ("download_file" in line or "fileUrl" in line or "receipt" in line.lower())
        ]

        assert offenders == []

    @pytest.mark.parametrize("page", RECEIPT_PAGES)
    def test_no_receipt_links_straight_at_the_download_route(self, page: str) -> None:
        # download_file 302s to a presigned B2 URL: cross-origin, so pdf.js and an iframe
        # cannot read it, and the browser decides whether to show or save it. Receipts go
        # through report.preview_file instead (same origin, Content-Disposition: inline).
        assert "report.download_file" not in read(page) or page == "report/expense.html"

    def test_expense_page_keeps_no_window_open_and_no_dead_viewers(self) -> None:
        page = read("report/expense.html")

        assert "window.open" not in page
        assert 'target="_blank"' not in page
        for dead in ("openFileViewer", "fileViewerModal", "expenseImagePreviewModal"):
            assert dead not in page, f"{dead} is dead code and should be gone"

    def test_scripts_js_previews_rather_than_downloading(self, scripts_js: str) -> None:
        body = handle_file_preview(scripts_js)

        assert ".download" not in body
        assert "_blank" not in body
        assert "FileReader" not in body
        assert "window.ReceiptPreview.render" in body
        assert "dataset.receiptUrl" in body

    def test_scripts_js_still_exports_statements(self, scripts_js: str) -> None:
        # The one deliberate download in this file: the admin statements XLSX. A sweep for
        # ".download =" must not take it with it.
        assert "downloadLink.download = filename" in scripts_js
        assert "statements.xlsx" in scripts_js


class TestTheMarkupTheUserClicks:
    def test_report_detail_offers_each_receipt_as_a_viewer_button(self) -> None:
        page = read("report_detail.html")

        assert 'data-receipt-key="{{ file }}"' in page
        assert "report.download_file" not in page

    def test_edit_report_offers_each_receipt_as_a_viewer_button(self) -> None:
        page = read("edit_report.html")

        assert "data-receipt-key=" in page
        assert "report.download_file" not in page

    def test_edit_report_drops_the_handlers_that_could_never_have_run(self) -> None:
        # handleFilePreview is closure-scoped inside scripts.js, so edit_report's two inline
        # callers referenced an undefined global and threw; scripts.js binds the rows itself.
        assert "handleFilePreview(" not in read("edit_report.html")


class TestItRenders:
    """The partial is included on pages no test renders, so prove it stands up on its own.

    Both of its `url_for` calls have to resolve, or every page carrying it 500s.
    """

    def test_renders_with_both_routes_resolved(self, app) -> None:
        from flask import render_template

        with app.test_request_context("/"):
            html = render_template(PARTIAL)

        assert 'id="receiptViewerModal"' in html
        assert "/preview/" in html, "report.preview_file did not resolve"
        assert "/download/" in html, "report.download_file did not resolve"
        # and it must not have grown a way out of the app
        assert "_blank" not in html
        assert "download=" not in html
