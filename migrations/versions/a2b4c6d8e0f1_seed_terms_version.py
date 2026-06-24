"""seed the initial active terms_version

Inserts one active ``terms_version`` row (``superseded_at IS NULL``) populated
from ``static/doc/terms_and_conditions.txt`` so the consent flow has a version
to record consents against (``consent_record.terms_ver_id`` is a RESTRICT FK).

Idempotent: does nothing if an active version already exists. The UUID is
generated in Python (no ``gen_random_uuid()`` dependency), mirroring
``b8f3a2c1d4e5_seed_modules_and_backfill.py``.

Revision ID: a2b4c6d8e0f1
Revises: 093b4bd031f1
Create Date: 2026-06-19 00:00:00.000000

"""

import os
import uuid

from alembic import op
from sqlalchemy import text

revision = "a2b4c6d8e0f1"
down_revision = "093b4bd031f1"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

VER_LABEL = "v1.0"
JURISDICTION = "HK"
DOC_URL = "/static/doc/terms_and_conditions.txt"


def _terms_text() -> str:
    """Read the terms text shipped in the repo at migration time."""
    here = os.path.dirname(__file__)
    path = os.path.abspath(
        os.path.join(here, "..", "..", "static", "doc", "terms_and_conditions.txt")
    )
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def upgrade():
    conn = op.get_bind()
    existing = conn.execute(
        text(
            f"SELECT 1 FROM {SCHEMA}.terms_version "
            "WHERE superseded_at IS NULL LIMIT 1"
        )
    ).first()
    if existing:
        return

    conn.execute(
        text(
            f"""
            INSERT INTO {SCHEMA}.terms_version
                (terms_ver_id, doc_url, ver_label, jurisdiction,
                 content_text, published_at)
            VALUES (:id, :doc_url, :ver_label, :jurisdiction,
                    :content_text, now())
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "doc_url": DOC_URL,
            "ver_label": VER_LABEL,
            "jurisdiction": JURISDICTION,
            "content_text": _terms_text(),
        },
    )


def downgrade():
    conn = op.get_bind()
    # Only remove the seeded row if nothing consented against it (RESTRICT FK).
    conn.execute(
        text(
            f"""
            DELETE FROM {SCHEMA}.terms_version tv
            WHERE tv.ver_label = :ver_label
              AND NOT EXISTS (
                  SELECT 1 FROM {SCHEMA}.consent_record cr
                  WHERE cr.terms_ver_id = tv.terms_ver_id
              )
            """
        ),
        {"ver_label": VER_LABEL},
    )
