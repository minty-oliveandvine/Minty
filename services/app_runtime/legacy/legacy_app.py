"""Compatibility shim for legacy imports."""

from services.app_runtime.legacy.compat import app, login_manager
from services.auth.session import load_user
from services.helpers.formatter import comma_format

app.add_template_filter(comma_format, "comma_format")
login_manager.user_loader(load_user)
