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

ENV = os.environ.get('ENV')