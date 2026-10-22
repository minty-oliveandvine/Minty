from __future__ import annotations

from minty_shared import logctx

from models.db import User


def load_user(user_id):
    user = User.query.get(user_id)
    if user is not None:
        # A signed-in session: the person goes on this request's log lines.
        logctx.bind(user=user.id)
    return user
