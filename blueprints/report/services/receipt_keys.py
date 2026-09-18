"""Receipt keys: the name a receipt is stored under, and splitting the comma-separated
``files`` value back into keys. Imports nothing from the app, so the model
(``ShopExpense.files``) and the services can both use it without a cycle.

NEW uploads are normalised (``safe_stem``): the stored name is ``[A-Z0-9_]`` only, so no
filename can ever look like a separator again. EXISTING keys are object names in the
bucket and stay as they are; ``split_receipt_keys`` is what reads them.

A receipt's filename is minted from the expense ITEM ("Staff Welfare - Meal, Transport
etc" -> ``..._MEAL,_TRANSPORT_ETC_547.jpg``), so a comma inside a filename is common -
1,195 rows on the 2026-09-18 production data. Only a comma followed by the start of another
key separates two keys; splitting on every comma turned those receipts into two broken
halves (a ``..._MEAL`` key no object has, and a ``,_TRANSPORT_ETC_547.jpg`` fragment) -
the "Key not found" preview seen on the deployed app on 2026-09-18.
"""

from __future__ import annotations

import re

_KEY_BOUNDARY = re.compile(r",(?=\s*(?:expenses/|attachments/|uploads/|https?://))")


def split_receipt_keys(value: str | None) -> list[str]:
    """The keys in a comma-separated ``files`` value, one per receipt, commas in names kept."""
    if not value:
        return []
    return [k.strip() for k in _KEY_BOUNDARY.split(value) if k.strip()]


_SAFE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "pdf"}
_STEM_MAX = 80


def safe_stem(text: str | None) -> str:
    """A filename stem from free text: uppercase, ``&`` -> ``AND``, every run of anything
    outside ``[A-Z0-9]`` -> one ``_``, no leading/trailing ``_``, at most 80 characters.

    ``"Staff Welfare - Meal, Transport etc"`` -> ``"STAFF_WELFARE_MEAL_TRANSPORT_ETC"``.
    Empty input gives ``""`` so the caller can fall back to something else.
    """
    t = (text or "").upper().replace("&", " AND ")
    t = re.sub(r"[^A-Z0-9]+", "_", t).strip("_")
    return t[:_STEM_MAX].rstrip("_")


def safe_extension(filename: str | None, default: str = "jpg") -> str:
    """The extension to store under, without the dot, from the known set; else the default."""
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    return ext if ext in _SAFE_EXTENSIONS else default
