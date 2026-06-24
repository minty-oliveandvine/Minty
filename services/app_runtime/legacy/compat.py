"""Legacy compatibility exports.

Keep the runtime singletons (`app`, `db`, `login_manager`, etc.) in one
module-level import surface while `legacy_app.py` remains the implementation
container.
"""

from __future__ import annotations

from .bootstrap import create_app

(
    app,
    db,
    login_manager,
    csrf,
    mail,
    migrate,
    s3,
    s3_client,
    S3_BUCKET,
    xero_sync_status,
    tz,
) = create_app()

