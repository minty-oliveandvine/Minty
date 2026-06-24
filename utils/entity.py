"""Entity-related utility helpers."""

from __future__ import annotations

import re
from datetime import datetime

import pytz

from models.db import tz


def ensure_hk_timezone(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(tz)


def build_entity_acronym(name):
    if not name:
        return ""
    words = name.split()
    return "".join([word[0].upper() for word in words if word and re.match(r"[A-Za-z]", word[0])])


def build_share_path_segment(entity_name, transaction_date):
    entity_acronym = build_entity_acronym(entity_name)
    if isinstance(transaction_date, datetime):
        date_obj = transaction_date
    else:
        date_obj = datetime.strptime(transaction_date, "%Y-%m-%d")
    return f"{entity_acronym}/{date_obj.strftime('%d %b %Y').replace(' ', '_')}"
