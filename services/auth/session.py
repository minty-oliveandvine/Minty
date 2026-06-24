from __future__ import annotations

from models.db import User


def load_user(user_id):
    return User.query.get(user_id)
