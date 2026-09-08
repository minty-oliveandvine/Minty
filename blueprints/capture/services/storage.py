"""S3 for capture files.

This does NOT reuse ``s3_storage.upload_file_to_s3``. That helper takes a
Werkzeug FileStorage and a ``report_id`` and builds a key out of the report's
transaction date, description and amount — none of which exist at the moment a
file lands in the capture hub. Bending it to fit would mean passing four
placeholder arguments to get a key we then have to work around.

What IS reused is the client itself: ``get_s3_client`` and ``get_s3_bucket``
from that module, so credentials, region and bucket resolution stay in one
place and there is only ever one S3 configuration to get wrong.

KEY LAYOUT

    capture/{entity_id}/{yyyy}/{mm}/{upload_id}/original.{ext}
    capture/{entity_id}/{yyyy}/{mm}/{upload_id}/doc-{sequence}.{ext}

The entity comes first so a per-customer lifecycle rule or a data-deletion
request is a prefix operation rather than a scan. The year and month make the
retention sweep cheap to reason about by eye.

Keys contain a UUID, so they are not guessable. That is a SECOND line of
defence, not the first: the file endpoint re-authorises on every request and
streams the bytes itself. A key is never handed to the browser.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from loguru import logger

from blueprints.report.services.s3_storage import (get_s3_bucket,
                                                   get_s3_client)

# Extension per sniffed mime type. Driven by the SNIFFED type, never by the
# name the browser sent, so the extension on the key always matches the actual
# bytes behind it.
_EXTENSIONS = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}


def extension_for(mime: str) -> str:
    return _EXTENSIONS.get(mime, "bin")


def _prefix(entity_id: str, upload_id: str, when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    return f"capture/{entity_id}/{when:%Y}/{when:%m}/{upload_id}"


def original_key(entity_id: str, upload_id: str, mime: str, when=None) -> str:
    return f"{_prefix(entity_id, upload_id, when)}/original.{extension_for(mime)}"


def document_key(
    entity_id: str, upload_id: str, sequence: int, mime: str, when=None
) -> str:
    return (
        f"{_prefix(entity_id, upload_id, when)}"
        f"/doc-{sequence}.{extension_for(mime)}"
    )


def put_bytes(key: str, data: bytes, mime: str) -> str:
    """Store ``data`` at ``key``. Raises on failure.

    Raising is deliberate. If the file did not store, there is nothing to read
    later, and creating a capture_upload row that points at a key holding
    nothing would turn a clear upload failure into a mystery in the queue an
    hour later.
    """
    get_s3_client().put_object(
        Bucket=get_s3_bucket(),
        Key=key,
        Body=io.BytesIO(data),
        ContentType=mime,
    )
    return key


def get_bytes(key: str) -> bytes | None:
    """Read an object back, or None if it is not there."""
    try:
        response = get_s3_client().get_object(Bucket=get_s3_bucket(), Key=key)
        return response["Body"].read()
    except Exception as exc:
        logger.warning("capture storage: could not read {}: {}", key, exc)
        return None


def delete_keys(keys) -> None:
    """Best-effort delete. Never raises.

    Used by the retention sweeper, which deletes the S3 objects FIRST and the
    row second. That order is on purpose: an orphaned object costs a fraction
    of a cent, while a row pointing at a deleted object is a broken page.
    """
    keys = [key for key in (keys or []) if key]
    if not keys:
        return
    try:
        get_s3_client().delete_objects(
            Bucket=get_s3_bucket(),
            Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
        )
    except Exception as exc:
        logger.warning("capture storage: delete failed for {} keys: {}", len(keys), exc)
