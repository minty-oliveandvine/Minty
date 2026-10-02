import os

from dotenv import load_dotenv

from services.app_runtime.env import app_env

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

# The From address for BILLING email only — trial warnings, payment failures and
# recoveries, handovers.
# Everything else (OTP, password reset, invitations) keeps MAIL_FROM.
#
# Split because the two are different conversations: an invitation comes from a colleague
# and a dunning notice comes from the company that is about to switch your access off.
# Recipients filter and search on the sender, and a customer looking for "that email about
# my payment" should not have to know it arrived from an address with `invite` in it.
#
# MUST be a verified sender in Brevo. An unverified From is either rejected outright by
# the relay or delivered straight to spam, and the failure is silent from here — the send
# is logged and swallowed like any other SMTP error. Falls back to MAIL_FROM when unset,
# so an environment that has not added the sender yet keeps working.
SUBSCRIPTION_EMAIL = os.environ.get('SUBSCRIPTION_EMAIL') or MAIL_FROM

# This app's own public origin, used to build links in outbound email (the invitation,
# password-reset and billing emails all read it from app.config).
#
# Set explicitly rather than derived: the billing emails are sent from `flask
# subscriptions ...` CLI jobs, where there is no request to take a host from and
# `url_for(_external=True)` quietly yields http://localhost — a link that is worse than
# no link, because it looks real. Unset, the emails sent from a request use that request's
# host and the billing emails drop their buttons. e.g. https://app.minty.com
PETTY_CASH_URL = (os.environ.get('PETTY_CASH_URL') or '').rstrip('/') or None

# Xero's OAuth callback (the xero blueprint's /callback), derived from this app's own URL;
# registered with the Xero app as-is. The local default is the dev server's port.
REDIRECT_URI = (PETTY_CASH_URL or 'http://localhost:8010') + '/callback'

# Stripe — the payment RAIL, not the source of truth: the local tables own the catalog
# and every entity's subscription and access state. The secret key authorizes API calls
# (server-side only); the publishable key is safe to expose to the frontend.
#
# There is no webhook secret here any more. The receiver was deleted with the Stripe
# biller and nothing read the setting, so it was a configured value with no reader. The
# .env files still carry a STRIPE_WEBHOOK_SECRET line; it is inert, and goes whenever
# .env.example is next regenerated.
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')