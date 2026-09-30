import os

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

S3_BUCKET = os.environ.get("S3_BUCKET")  # Your Backblaze B2 bucket name
S3_KEY = os.environ.get("S3_KEY")  # Your Backblaze B2 application key ID
S3_SECRET = os.environ.get("S3_SECRET")  # Your Backblaze B2 application key
S3_REGION = os.environ.get("S3_REGION")  # Your Backblaze B2 region (e.g., 'us-west-002')

SECRET_KEY = os.environ.get('SECRET_KEY')

WTF_CSRF_SECRET_KEY = os.environ.get('WTF_CSRF_SECRET_KEY')

SQLALCHEMY_LOCAL_DATABASE_URI = os.environ.get('LOCAL_DATABASE_URI')

SQLALCHEMY_RDS_DATABASE_URI = os.environ.get('RDS_DATABASE_URI')

BREVO_EMAIL = os.environ.get('BREVO_EMAIL')

# The From address for BILLING email only — trial warnings, payment failures and
# recoveries, handovers.
# Everything else (OTP, password reset, invitations) keeps BREVO_EMAIL.
#
# Split because the two are different conversations: an invitation comes from a colleague
# and a dunning notice comes from the company that is about to switch your access off.
# Recipients filter and search on the sender, and a customer looking for "that email about
# my payment" should not have to know it arrived from an address with `invite` in it.
#
# MUST be a verified sender in Brevo. An unverified From is either rejected outright by
# the relay or delivered straight to spam, and the failure is silent from here — the send
# is logged and swallowed like any other SMTP error. Falls back to BREVO_EMAIL when unset,
# so an environment that has not added the sender yet keeps working.
SUBSCRIPTION_EMAIL = os.environ.get('SUBSCRIPTION_EMAIL')

# Public origin used to build links in outbound email — the same variable the
# invitation email already reads (blueprints/invitation/services/invite.py), surfaced
# through app.config so it can be overridden in tests.
#
# Set explicitly rather than derived: the billing emails are sent from `flask
# subscriptions ...` CLI jobs, where there is no request to take a host from and
# `url_for(_external=True)` quietly yields http://localhost — a link that is worse than
# no link, because it looks real. Unset simply drops the buttons. e.g. https://app.minty.com
PUBLIC_URL = os.environ.get('PUBLIC_URL')

ENV = os.environ.get('ENV')

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