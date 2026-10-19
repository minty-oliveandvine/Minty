import os

from dotenv import load_dotenv

from services.app_runtime.env import accounts_api_url, app_env

# Load environment variables
load_dotenv()

# Backblaze B2 (S3 API): https://KEY:SECRET@s3.<region>.backblazeb2.com/<bucket>. Parsed by
# services/app_runtime/env.parse_s3_url - the endpoint, bucket, key and region all come from it.
S3_URL = os.environ.get("S3_URL")

SECRET_KEY = os.environ.get('SECRET_KEY')

# ``development`` or ``production`` (the default, and what any other value means).
APP_ENV = app_env()

# The default From address (OTP, password reset, invitations). Flask-Mail's own default
# sender is the same address.
MAIL_FROM = os.environ.get('MAIL_FROM')
MAIL_DEFAULT_SENDER = MAIL_FROM

# This app's own public origin, used to build links in outbound email (the invitation
# and password-reset emails read it from app.config).
#
# Set explicitly rather than derived: an email sent outside a request has no host to take,
# and `url_for(_external=True)` quietly yields http://localhost — a link that is worse than
# no link, because it looks real. Unset, the emails sent from a request use that request's
# host. e.g. https://accounts-api.dailyminty.com
#
# ACCOUNTS_API_URL, else PETTY_CASH_URL (the transitional alias, which still means Flask);
# required outside development (services/app_runtime/env.accounts_api_url).
ACCOUNTS_API_URL = accounts_api_url()

# Xero's OAuth callback (the xero blueprint's /callback), derived from this app's own URL;
# registered with the Xero app as-is. The local default is the dev server's port.
REDIRECT_URI = (ACCOUNTS_API_URL or 'http://localhost:8000') + '/callback'
