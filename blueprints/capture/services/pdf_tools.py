"""PDF page counting and page extraction, on pikepdf.

Two jobs, both small, both on the critical path:

  ``page_count``     runs on every PDF upload, BEFORE anything is stored and
                     before any model call, so a 40-page bank statement is
                     refused for free.

  ``extract_pages``  cuts one document out of a multi-document file so Pass 2
                     sees only the pages it is meant to read. Sending the whole
                     file five times would cost five times the input tokens and
                     invite the model to read the wrong receipt.

pikepdf 9.4.0 is already a dependency — Stage 1 uses it for its first-page
trim. Nothing new is being added to the stack here.

WHY THESE RAISE AND STAGE 1'S EQUIVALENT DOES NOT

Stage 1's ``_first_page_only`` swallows every error and returns the original
bytes, because a slightly larger request beats no suggestion. That is right
there and wrong here. A file we cannot open is a file the user must be told
about, at upload time, in plain English — not one we quietly send to a model
that will fail on it a few seconds later at our expense.
"""

from __future__ import annotations

import io

from loguru import logger


class PdfUnreadable(Exception):
    """The bytes claim to be a PDF but pikepdf cannot open them."""


def page_count(data: bytes) -> int:
    """Number of pages in a PDF.

    Raises ``PdfUnreadable`` if it cannot be opened — a corrupt file, an
    encrypted one, or something that merely starts with %PDF.
    """
    import pikepdf

    try:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            return len(pdf.pages)
    except Exception as exc:
        logger.info("capture pdf_tools: page count failed: {}", type(exc).__name__)
        raise PdfUnreadable(str(exc)) from exc


def clamp_range(start, end, total: int) -> tuple[int, int]:
    """Force a page range returned by the model into something real.

    The model will occasionally return page 4 of a 3-page PDF, or an end before
    its start. Unclamped, either one crashes pikepdf inside a background thread
    — where the traceback is a long way from the cause. Clamping here turns a
    model mistake into a slightly wrong page range, which the user can see and
    correct, rather than a lost upload.

    Pages are 1-based and inclusive, matching how the model is asked to count
    and how the queue displays them.
    """
    try:
        start = int(start)
    except (TypeError, ValueError):
        start = 1
    try:
        end = int(end)
    except (TypeError, ValueError):
        end = start

    start = max(1, min(start, total))
    end = max(1, min(end, total))
    if end < start:
        end = start
    return start, end


def extract_pages(data: bytes, start: int, end: int) -> bytes:
    """A new PDF holding only pages ``start``..``end`` (1-based, inclusive).

    Returns the input unchanged when the range already covers the whole
    document — re-saving a one-page PDF to get an identical one-page PDF is
    work for nothing.

    Raises ``PdfUnreadable`` if the source cannot be opened.
    """
    import pikepdf

    try:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            total = len(pdf.pages)
            start, end = clamp_range(start, end, total)
            if start == 1 and end == total:
                return data

            out_pdf = pikepdf.Pdf.new()
            # pikepdf pages are 0-indexed; the arguments are 1-based.
            for index in range(start - 1, end):
                out_pdf.pages.append(pdf.pages[index])
            buffer = io.BytesIO()
            out_pdf.save(buffer)
            return buffer.getvalue()
    except PdfUnreadable:
        raise
    except Exception as exc:
        logger.warning(
            "capture pdf_tools: page extraction {}-{} failed: {}",
            start, end, type(exc).__name__,
        )
        raise PdfUnreadable(str(exc)) from exc
