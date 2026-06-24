"""Utility helper package for app-wide serialization and token helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import jwt
from xero_python.api_client.serializer import serialize

from .entity import (build_entity_acronym,  # noqa: F401
                     build_share_path_segment, ensure_hk_timezone)
from .report import parse_nested_keys, safe_float  # noqa: F401


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, (uuid.UUID, Decimal)):
            return str(o)
        return super(JSONEncoder, self).default(o)


def parse_json(data):
    return json.loads(data, parse_float=Decimal)


def serialize_model(model):
    return jsonify(serialize(model))


def jsonify(data):
    return json.dumps(data, sort_keys=True, indent=4, cls=JSONEncoder)


def decode_jwt(token):
    # Decode id token to get user info to enter to pettycashv2 db
    decoded = jwt.decode(
        token,
        options={
            "verify_signature": False,  # Skip signature verification
            "verify_exp": False,  # Skip expiration check
            "verify_aud": False,  # Skip audience check
            "verify_iss": False,  # Skip issuer check
        },
        algorithms=["RS256"],
    )
    return decoded


def is_token_expired(access_token):
    try:
        decoded_token = decode_jwt(access_token)
        exp_timestamp = decoded_token.get("expires_in")

        if exp_timestamp:
            exp_datetime = datetime.fromtimestamp(exp_timestamp)
            current_datetime = datetime.now()
            buffer_time = timedelta(minutes=5)
            return current_datetime >= (exp_datetime - buffer_time)

        return True
    except Exception:
        return True


def generate_share_token(entity_id, transaction_date, secret_key, expiration_hours=720):
    """
    Generate a shareable token with HMAC signature.
    """
    params = {
        "entity_id": str(entity_id),
        "transaction_date": str(transaction_date),
    }

    expiration = int((datetime.now().timestamp() + (expiration_hours * 3600)))
    params_str = json.dumps(params, sort_keys=True)
    message = f"{params_str}|{expiration}"
    signature = hmac.new(
        secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    token_data = f"{message}|{signature}"
    return base64.b64encode(token_data.encode("utf-8")).decode("utf-8")


def verify_share_token(token, secret_key):
    """
    Verify a shareable token and extract parameters.
    """
    try:
        token_data = base64.b64decode(token.encode("utf-8")).decode("utf-8")
        parts = token_data.split("|")
        if len(parts) != 3:
            return False, None

        params_str, expiration_str, signature = parts
        expiration = int(expiration_str)
        if datetime.now().timestamp() > expiration:
            return False, None

        message = f"{params_str}|{expiration_str}"
        expected_signature = hmac.new(
            secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            return False, None

        params = json.loads(params_str)
        return True, params
    except Exception:
        return False, None
