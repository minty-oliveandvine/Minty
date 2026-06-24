import os

from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.urandom(16)
# Database settings
SQLALCHEMY_DATABASE_URI = os.environ.get('RDS_DATABASE_URI')
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Session settings
SESSION_TYPE = os.environ.get('SESSION_TYPE')
SESSION_SQLALCHEMY_TABLE = os.environ.get('SESSION_SQLALCHEMY_TABLE')

# configure flask app for local development
ENV = os.environ.get('ENV')
SESSION_TYPE = os.environ.get('SESSION_TYPE')
SESSION_SQLALCHEMY_TABLE = os.environ.get('SESSION_SQLALCHEMY_TABLE')

