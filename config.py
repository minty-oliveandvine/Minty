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

# Stripe — the live source of truth for the subscription module. The secret key
# authorizes API calls (server-side only); the webhook secret verifies incoming
# events; the publishable key is safe to expose to the frontend.
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')