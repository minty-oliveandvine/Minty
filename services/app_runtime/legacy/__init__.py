"""Legacy runtime entrypoint compatibility package."""

from . import compat, legacy_app

app = compat.app
db = compat.db
login_manager = compat.login_manager
csrf = compat.csrf
mail = compat.mail
migrate = compat.migrate
s3 = compat.s3
s3_client = compat.s3_client
S3_BUCKET = compat.S3_BUCKET
xero_sync_status = compat.xero_sync_status
tz = compat.tz

load_user = legacy_app.load_user
comma_format = legacy_app.comma_format

__all__ = (
    "app",
    "db",
    "login_manager",
    "csrf",
    "mail",
    "migrate",
    "s3",
    "s3_client",
    "S3_BUCKET",
    "xero_sync_status",
    "tz",
    "load_user",
    "comma_format",
)
